<script lang="ts">
  /**
   * SVG plot renderer + pointer interaction. Measures its own box
   * with a ResizeObserver, delegates ALL geometry to `buildPlot`
   * (src/lib/plot/build.ts) and renders the result verbatim; gesture
   * MATHS live in src/lib/plot/zoom.ts — only the pointer wiring is
   * here.
   *
   * Interaction (design spec §6), active only when a `viewState`
   * store is supplied (omit it for a static, non-interactive plot):
   * - box-zoom mode: drag draws a dashed rubber band; releasing
   *   commits `rubberBandToRange` → `clampToData` → `setRange`.
   *   Sub-6-px drags are clicks (no-op).
   * - pan mode: dragging pans a LOCAL preview range (rAF-throttled,
   *   no store writes); releasing commits EXACTLY ONE `setRange` —
   *   gesture coalescing that the store's 50-entry history cap
   *   depends on (plan amendment A3). A pan under 6 px total travel is
   *   a click and commits nothing (matches box mode's click dead-zone).
   * - the drag `mode` is latched at pointerdown, so a mid-drag mode flip
   *   can't reroute an in-flight gesture onto the wrong branch.
   * - pointercancel / lostpointercapture (interrupted gesture: touch
   *   stolen, OS focus loss) clears the band / pan preview and resets
   *   state WITHOUT committing — a fresh pointerdown then starts clean.
   * - double-click anywhere on the plot → `autoFit`.
   * - the guardrail extent is recomputed from the model's lines via
   *   `dataExtent` (cheap: only runs when the model changes), so
   *   zoom/pan clamp to the lines currently shown.
   * - drag gestures are DISABLED on `squareAspect` (Nyquist) models — the
   *   aspect-locked view is navigated by the frequency-band brush above it
   *   (windows the locus) and the toolbar's Real/Imag limits + Auto X/Y
   *   (round-5 item 4), not by dragging on the square itself.
   *
   * The parent must derive `model.xRange`/`model.yRange` from
   * `viewState.current.range` for committed gestures to take effect.
   *
   * Export hooks: the root <svg> carries `data-testid="plot-svg"`,
   * each line `data-testid="plot-line"`, the rubber band
   * `data-testid="rubber-band"` (Playwright), the background rect
   * `data-role="plot-bg"` and every piece of axis chrome
   * `data-role="axis"` (the figure exporter restyles by these tags).
   *
   * Self-contained-SVG rule (Task 14, decision A): the plot-bg and axis
   * chrome carry INLINE fill/stroke hexes (CHROME.*) in ADDITION to their
   * scoped CSS classes. On-screen the scoped CSS wins (CSS beats
   * presentation attributes), so the visible plot is unchanged; but a
   * standalone `getSvgElement().outerHTML` — which loses the scoped
   * style block — still renders correctly, and the figure exporter's
   * regexes find real hexes to restyle. The hexes come from the shared
   * CHROME (../lib/plot/chrome), which figure.ts also keys its dark map off.
   *
   * Visual treatment ported from dev/mockups/round2-bench.html:
   * margins L58/T16/B42, R18 (56 with a right axis), #eef0f4
   * gridlines, mono tick labels and muted axis labels.
   */
  import { buildPlot, dataExtent, type PlotModel } from '../lib/plot/build';
  import { fmtTick } from '../lib/plot/scales';
  import { rubberBandToRange, clampToData, panBy } from '../lib/plot/zoom';
  import { CHROME } from '../lib/plot/chrome';
  import type { ViewState } from '../lib/stores/viewstate';
  import { get } from 'svelte/store';

  let {
    model,
    mode = 'box',
    viewState = undefined,
    overlay = false,
    onCommit = undefined,
    onAutoFit = undefined,
  }: {
    model: PlotModel;
    /** Active drag tool; bind ZoomToolbar's `mode` to this. */
    mode?: 'box' | 'pan';
    /** View-state store; when absent the plot is non-interactive. */
    viewState?: ViewState;
    /**
     * Axis-overlay mode: draw the frame/ticks/labels but make the plot-area
     * background TRANSPARENT and omit gridlines, so a heat layer (the
     * sonogram `<canvas>`) mounted BEHIND this surface shows through. Without
     * this the opaque `plot-bg` rect hides the canvas entirely.
     *
     * NB the inline `fill="transparent"` on the plot-bg rect is not sufficient
     * on its own: the scoped `.plot-bg { fill: var(--surface) }` rule beats a
     * presentation attribute (CSS > presentation attrs), so on screen the rect
     * would render OPAQUE and hide the heat. Overlay mode therefore also adds
     * the `overlay-bg` class, whose higher-specificity `.plot-bg.overlay-bg`
     * rule forces the on-screen fill transparent. (This was the longstanding
     * white-sonogram bug: the canvas painted correctly but sat beneath an
     * opaque surface.)
     */
    overlay?: boolean;
    /**
     * Override where a committed box-zoom / pan gesture WRITES its range
     * (round-5 item 5). Absent ⇒ the default `viewState.setRange(active, …)`.
     * The Bode PHASE pane supplies this so its gestures route the shared x to
     * `range.x` and the y to the phase pane's OWN axis (`phaseRange.y`) in one
     * undo step, instead of clobbering the magnitude pane's y. Receives the
     * gesture's committed range (x may be null when unconstrained).
     */
    onCommit?: (range: { x: [number, number] | null; y: [number, number] | null }) => void;
    /**
     * Override the double-click auto-fit target (round-5 item 5). Absent ⇒
     * `viewState.autoFit(active)`. The Bode phase pane uses it to auto-fit ITS
     * axis (`phaseRange`) rather than the shared primary range.
     */
    onAutoFit?: () => void;
  } = $props();

  /** Commit a gesture range to the override callback, else the default setRange. */
  function commitRange(range: { x: [number, number] | null; y: [number, number] | null }): void {
    if (onCommit) onCommit(range);
    else if (viewState) viewState.setRange(get(viewState.active), range);
  }
  /** Auto-fit via the override callback, else the default autoFit. */
  function autoFitNow(): void {
    if (onAutoFit) onAutoFit();
    else if (viewState) viewState.autoFit(get(viewState.active));
  }

  const uid = $props.id();
  const clipId = `plot-clip-${uid}`;

  // CHROME (from ../lib/plot/chrome) holds the inline fill/stroke hexes stamped
  // on plot-bg + axis elements (decision A) so a serialised export SVG is self-
  // contained; on-screen the scoped CSS still governs. figure.ts's DARK_MAP is
  // keyed off these same values — one source, no drift.

  let host: HTMLDivElement | undefined = $state();
  let svgEl: SVGSVGElement | undefined = $state();
  let width = $state(0);
  let height = $state(0);

  /** Root <svg> element, serialised by the figure exporter (Task 14). */
  export function getSvgElement(): SVGSVGElement | undefined {
    return svgEl;
  }

  $effect(() => {
    if (!host) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[entries.length - 1].contentRect;
      // Round to whole px: sub-pixel resize deltas would otherwise
      // churn a full plot rebuild for invisible size changes.
      width = Math.round(r.width);
      height = Math.round(r.height);
    });
    ro.observe(host);
    return () => ro.disconnect();
  });

  // Margins from the mockup's plot engine (L=58, T=16, B=42; R widens
  // to make room for right-axis tick labels when coherence is shown).
  const ML = 58, MT = 16, MB = 42;
  const MR = $derived(model.y2Range ? 56 : 18);

  const iw = $derived(Math.max(50, width - ML - MR));
  const ih = $derived(Math.max(50, height - MT - MB));
  // squareAspect: drawing area is a centred square of side min(iw, ih).
  const side = $derived(Math.min(iw, ih));
  const pw = $derived(model.squareAspect ? side : iw);
  const ph = $derived(model.squareAspect ? side : ih);
  const ox = $derived(ML + (model.squareAspect ? (iw - side) / 2 : 0));
  const oy = $derived(MT + (model.squareAspect ? (ih - side) / 2 : 0));

  // Local pan-preview range: while a pan gesture is live, the render
  // uses THIS instead of model.xRange/yRange so the plot tracks the
  // drag with zero store writes (the single commit happens on release —
  // plan amendment A3, the store's 50-entry history cap). null between
  // gestures → the plot renders straight from the model.
  type PanRange = { x: [number, number]; y: [number, number] };
  let panPreview = $state<PanRange | null>(null);

  // Feed the preview into the builder: override the model's ranges only
  // while a pan is in progress. Everything else (labels, lines, aspect)
  // is untouched, so committed box-zoom/pan still flow via model.xRange.
  const renderModel = $derived<PlotModel>(
    panPreview ? { ...model, xRange: panPreview.x, yRange: panPreview.y } : model
  );

  const built = $derived(width > 0 && height > 0 ? buildPlot(renderModel, pw, ph) : null);
  const xSpan = $derived(built ? built.xDomain[1] - built.xDomain[0] : 1);
  const ySpan = $derived(built ? built.yDomain[1] - built.yDomain[0] : 1);
  const y2Span = $derived(model.y2Range ? model.y2Range[1] - model.y2Range[0] : 1);

  // ---- Pointer interaction (only when a viewState store is wired) ----

  /** Rubber-band rect in inner-plot-rect pixels, or null when idle. */
  let band: { x0: number; y0: number; x1: number; y1: number } | null = $state(null);

  // Log-x gesture support (R3): the pixel↔data mapping is log10 on the x
  // axis when the model's xScale is 'log' (never on Nyquist). The zoom /
  // pan / clamp maths are pure LINEAR functions, so we run them in
  // LOG-SPACE for x (pixels are linear in log-space, exactly how the
  // scale renders) and exponentiate the committed x range back. y is
  // always linear. `tx`/`itx` are identity for a linear x axis, so the
  // linear path is byte-for-byte unchanged.
  const logX = $derived(renderModel.xScale === 'log' && !model.squareAspect);
  const tx = (v: number): number => (logX ? Math.log10(v) : v);
  const itx = (v: number): number => (logX ? 10 ** v : v);
  /** Transform a data-space {x,y} window into the gesture math space. */
  const toGesture = (r: { x: [number, number]; y: [number, number] }) =>
    ({ x: [tx(r.x[0]), tx(r.x[1])] as [number, number], y: r.y });
  /** Invert a gesture-space x range back to data space (y untouched). */
  const fromGestureX = (x: [number, number]): [number, number] => [itx(x[0]), itx(x[1])];

  /** Full data extent (guardrail for clampToData); recomputed per model. */
  const fullExtent = $derived({
    x: dataExtent(model.lines, 'x', 'any'),
    y: dataExtent(model.lines, 'y', 'left'),
  });
  /**
   * The clamp guardrail extent in GESTURE space. For log-x the raw data
   * extent can reach the DC (f=0) bin, which has no log; use the built
   * domain's clamped-positive lower bound so the guardrail stays finite.
   */
  const gestureExtent = $derived({
    x: [tx(logX ? (built?.xDomain[0] ?? fullExtent.x[0]) : fullExtent.x[0]), tx(fullExtent.x[1])] as [number, number],
    y: fullExtent.y,
  });

  // Pan-gesture bookkeeping (not reactive state — plain closures).
  let dragging = false;              // a drag gesture is active
  let panStartX = 0, panStartY = 0;  // pointer origin (inner-rect px)
  let panStartDom: { x: [number, number]; y: [number, number] } | null = null;
  let rafId = 0;                     // pending rAF for coalesced pan moves
  let pendingPan: { dxPx: number; dyPx: number } | null = null;
  let activePointer = 0;
  // `mode` latched at pointerdown: the whole gesture's move/up handlers
  // branch on THIS, not the live prop, so a mid-drag mode flip
  // (programmatic/keyboard) can't route a pan-started gesture through the
  // box branch on release and strand `panPreview`.
  let gestureMode: 'box' | 'pan' = 'box';

  /** Drags below this many px (total travel) are treated as clicks. */
  const MIN_DRAG_PX = 6;

  /**
   * Toggle a global `plot-gesture-active` class on the document root for the
   * duration of a drag gesture (round-6 item 4). The plot surfaces already
   * carry a baseline `user-select: none`, so a selection can never ANCHOR in
   * the plot; this global flag is the belt-and-suspenders that also suppresses
   * selection which a fast diagonal drag would otherwise paint across the tray
   * / legend / page (the "everything flashes selection-blue" bug). Removed on
   * pointerup / cancel / lost-capture so text stays normally selectable
   * between gestures (rename inputs included). No-op outside the browser (SSR).
   */
  function setGestureActive(on: boolean) {
    if (typeof document !== 'undefined') {
      document.documentElement.classList.toggle('plot-gesture-active', on);
    }
  }

  /**
   * Abandon the in-flight gesture WITHOUT committing a setRange: clear
   * the rubber band, cancel any pending pan rAF, drop the pan preview,
   * and reset all drag bookkeeping. Shared by pointercancel and
   * lostpointercapture (interrupted gestures — touch stolen, OS focus
   * loss — deliver no pointerup, so without this the dashed band or an
   * applied panPreview would stay painted). A fresh pointerdown then
   * starts from clean state.
   */
  function abortGesture() {
    dragging = false;
    activePointer = 0;
    setGestureActive(false);
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    band = null;
    panPreview = null;
    pendingPan = null;
    panStartDom = null;
  }

  /** Pointer position relative to the inner plot rect (data area). */
  function localXY(e: PointerEvent): { x: number; y: number } | null {
    if (!svgEl) return null;
    const r = svgEl.getBoundingClientRect();
    // Map client px → viewBox px (viewBox is 0..width, 0..height) then
    // subtract the inner-rect origin so (0,0) is the data area's corner.
    const sxr = r.width ? width / r.width : 1;
    const syr = r.height ? height / r.height : 1;
    return { x: (e.clientX - r.left) * sxr - ox, y: (e.clientY - r.top) * syr - oy };
  }

  /** Interaction is live only with a store AND a ready, non-Nyquist plot. */
  function interactive(): boolean {
    return !!viewState && !!built && pw > 0 && ph > 0 && !model.squareAspect;
  }

  function onPointerDown(e: PointerEvent) {
    if (!interactive() || e.button !== 0) return;
    const p = localXY(e);
    if (!p) return;
    dragging = true;
    activePointer = e.pointerId;
    setGestureActive(true);
    // Latch the mode for the whole gesture (fix: mid-drag mode flips must
    // not switch which branch move/up take).
    gestureMode = mode;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    if (gestureMode === 'pan') {
      panStartX = p.x; panStartY = p.y;
      // Captured in GESTURE space (log-x → log10) so panBy's linear delta
      // is correct on a log axis; committed values are inverted back.
      panStartDom = toGesture({ x: [built!.xDomain[0], built!.xDomain[1]], y: [built!.yDomain[0], built!.yDomain[1]] });
    } else {
      band = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
    }
  }

  function onPointerMove(e: PointerEvent) {
    if (!dragging || e.pointerId !== activePointer) return;
    const p = localXY(e);
    if (!p) return;
    if (gestureMode === 'pan') {
      // Coalesce moves: stash the latest delta, apply once per frame.
      pendingPan = { dxPx: p.x - panStartX, dyPx: p.y - panStartY };
      if (!rafId) {
        rafId = requestAnimationFrame(() => {
          rafId = 0;
          if (!pendingPan || !panStartDom) return;
          const r = panBy(panStartDom, pendingPan, { width: pw, height: ph });
          const c = clampToData(r as { x: [number, number]; y: [number, number] }, gestureExtent);
          // Invert x back to data space for the render preview (y is linear).
          panPreview = { x: fromGestureX(c.x!), y: c.y! };
        });
      }
    } else if (band) {
      band = { ...band, x1: p.x, y1: p.y };
    }
  }

  function onPointerUp(e: PointerEvent) {
    if (!dragging || e.pointerId !== activePointer) return;
    dragging = false;
    activePointer = 0;
    setGestureActive(false);
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch { /* already released */ }
    if (gestureMode === 'pan') {
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      // Commit EXACTLY ONE setRange for the whole gesture. Use the final
      // pointer position (not a stale rAF preview) so the commit matches
      // where the pointer actually released.
      if (panStartDom && viewState) {
        const p = localXY(e);
        const delta = p
          ? { dxPx: p.x - panStartX, dyPx: p.y - panStartY }
          : (pendingPan ?? { dxPx: 0, dyPx: 0 });
        // Dead-zone (fix): a pan that never travelled past MIN_DRAG_PX is a
        // click, not a pan — committing it would push a no-op history entry
        // (a click pushes 1, a double-click ~3). Below threshold: commit
        // nothing. (Box mode already rejects sub-threshold drags upstream
        // via rubberBandToRange returning null.)
        if (Math.hypot(delta.dxPx, delta.dyPx) >= MIN_DRAG_PX) {
          const r = panBy(panStartDom, delta, { width: pw, height: ph });
          const c = clampToData(r as { x: [number, number]; y: [number, number] }, gestureExtent);
          commitRange({ x: fromGestureX(c.x!), y: c.y! });
        }
      }
      panPreview = null;
      pendingPan = null;
      panStartDom = null;
    } else if (band) {
      const rect = { x0: band.x0, y0: band.y0, x1: band.x1, y1: band.y1 };
      band = null;
      if (viewState && built) {
        // Run the band→range maths in GESTURE space (log-x → log10) so a
        // box on a log axis maps correctly, then invert x back to data.
        const range = rubberBandToRange(
          rect,
          toGesture({ x: built.xDomain, y: built.yDomain }),
          { width: pw, height: ph }
        );
        if (range) {
          const c = clampToData(range, gestureExtent);
          commitRange({ x: c.x ? fromGestureX(c.x) : null, y: c.y });
        }
      }
    }
  }

  /**
   * Interrupted gesture (touch stolen, OS focus loss, capture lost): no
   * pointerup arrives, so run the shared cleanup and commit nothing. The
   * `activePointer` guard means a stale event for a non-active pointer is
   * ignored (except lostpointercapture, which the browser fires without a
   * usable pointerId match — it always means our capture is gone).
   */
  function onPointerCancel(e: PointerEvent) {
    if (!dragging || e.pointerId !== activePointer) return;
    abortGesture();
  }

  function onLostPointerCapture() {
    if (!dragging) return;
    abortGesture();
  }

  function onDblClick() {
    if (!interactive() || !viewState) return;
    autoFitNow();
  }

  // Cancel any pending pan rAF and clear the global gesture flag if the
  // component unmounts mid-gesture (else a stranded `plot-gesture-active`
  // would keep the page's text unselectable).
  $effect(() => () => { if (rafId) cancelAnimationFrame(rafId); setGestureActive(false); });
</script>

<div class="plot-surface" bind:this={host}>
  {#if built}
    <svg
      bind:this={svgEl}
      data-testid="plot-svg"
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 {width} {height}"
      role="img"
      aria-label={model.yLabel + ' vs ' + model.xLabel}
    >
      <rect data-role="plot-bg" class="plot-bg" class:overlay-bg={overlay} x="0" y="0" width={width} height={height}
        fill={overlay ? 'transparent' : CHROME.bg} />
      <defs>
        <clipPath id={clipId}><rect x="0" y="0" width={pw} height={ph} /></clipPath>
      </defs>

      {#each built.xTicks as t (t.v)}
        {#if !overlay}
          <line data-role="axis" class="grid" x1={ox + t.px} y1={oy} x2={ox + t.px} y2={oy + ph} stroke={CHROME.grid} />
        {/if}
        <text data-role="axis" class="tick" x={ox + t.px} y={oy + ph + 15} text-anchor="middle" fill={CHROME.axis}
          >{fmtTick(t.v, xSpan)}</text>
      {/each}
      {#each built.yTicks as t (t.v)}
        {#if !overlay}
          <line data-role="axis" class="grid" x1={ox} y1={oy + t.px} x2={ox + pw} y2={oy + t.px} stroke={CHROME.grid} />
        {/if}
        <text data-role="axis" class="tick" x={ox - 7} y={oy + t.px + 3.5} text-anchor="end" fill={CHROME.axis}
          >{fmtTick(t.v, ySpan)}</text>
      {/each}
      {#each built.y2Ticks as t (t.v)}
        <text data-role="axis" class="tick" x={ox + pw + 7} y={oy + t.px + 3.5} text-anchor="start" fill={CHROME.axis}
          >{fmtTick(t.v, y2Span)}</text>
      {/each}

      <rect data-role="axis" class="frame" x={ox} y={oy} width={pw} height={ph} fill="none" stroke={CHROME.frame} />

      <text data-role="axis" class="axlab" x={ox + pw / 2} y={height - 6} text-anchor="middle" fill={CHROME.axis}
        >{model.xLabel}</text>
      <text data-role="axis" class="axlab" transform="translate(14 {oy + ph / 2}) rotate(-90)"
        text-anchor="middle" fill={CHROME.axis}>{model.yLabel}</text>
      {#if model.y2Label && built.y2Ticks.length > 0}
        <text data-role="axis" class="axlab" transform="translate({width - 8} {oy + ph / 2}) rotate(90)"
          text-anchor="middle" fill={CHROME.axis}>{model.y2Label}</text>
      {/if}

      <g transform="translate({ox} {oy})">
        <g clip-path="url(#{clipId})">
          {#each built.paths as p, i (i)}
            {#if p.d}
              <path
                data-testid="plot-line"
                d={p.d}
                fill="none"
                stroke={p.color}
                stroke-width={p.width}
                opacity={p.opacity}
                stroke-dasharray={p.dashed ? '4 3' : undefined}
              />
            {/if}
          {/each}
          {#if band}
            <rect
              data-testid="rubber-band"
              class="rubber-band"
              x={Math.min(band.x0, band.x1)}
              y={Math.min(band.y0, band.y1)}
              width={Math.abs(band.x1 - band.x0)}
              height={Math.abs(band.y1 - band.y0)}
            />
          {/if}
        </g>
        {#if viewState && !model.squareAspect}
          <!-- Transparent capture layer over the data area; pointer
               gestures are measured relative to this rect's origin.
               fill="transparent" is INLINE (not just scoped CSS): it is
               the last-painted element over the data, so in a standalone
               export SVG — where the scoped CSS is gone — a missing fill
               would default to opaque BLACK and hide the whole plot. -->
          <rect
            class="capture"
            data-role="capture"
            fill="transparent"
            role="application"
            aria-label="Plot area — drag to {mode === 'pan' ? 'pan' : 'box-zoom'}, double-click to auto-fit"
            x="0"
            y="0"
            width={pw}
            height={ph}
            onpointerdown={onPointerDown}
            onpointermove={onPointerMove}
            onpointerup={onPointerUp}
            onpointercancel={onPointerCancel}
            onlostpointercapture={onLostPointerCapture}
            ondblclick={onDblClick}
          />
        {/if}
      </g>
    </svg>
  {/if}
</div>

<style>
  .plot-surface {
    position: relative;
    width: 100%;
    height: 100%;
    min-height: 220px;
    min-width: 180px;
    /* A plot gesture must never anchor a native text selection in the SVG
       chrome (tick labels, axis labels). Without this, a fast box-zoom /
       pan drag paints the plot text selection-blue (round-6 item 4). */
    user-select: none;
    -webkit-user-select: none;
  }
  svg {
    display: block;
    width: 100%;
    height: 100%;
  }
  .plot-bg {
    fill: var(--surface, #ffffff);
  }
  /* Overlay mode (sonogram): the heat <canvas> is mounted BEHIND this SVG, so
     the background rect MUST be transparent ON SCREEN for the heat to show
     through. The inline fill="transparent" alone is NOT enough — a scoped CSS
     rule beats a presentation attribute (CSS > presentation attrs), so the
     `.plot-bg` rule above renders the rect opaque `--surface` and hides the heat
     entirely. This higher-specificity rule (matches only when `overlay`) is what
     actually makes the overlay transparent — without it the sonogram is a blank
     white/dark plot (the longstanding white-sonogram bug). The serialised export
     SVG still carries the inline fill="transparent", so decision A is unaffected. */
  .plot-bg.overlay-bg {
    fill: transparent;
  }
  .frame {
    fill: none;
    stroke: var(--border, #e3e6eb);
  }
  .grid {
    /* On-screen only; the exported SVG carries the fixed CHROME.grid inline
       attr (theme-independent export). */
    stroke: var(--grid);
  }
  .tick {
    fill: var(--muted, #66708a);
    font: 10.5px var(--font-mono, ui-monospace, Menlo, monospace);
  }
  .axlab {
    fill: var(--muted, #66708a);
    font-size: 11.5px;
    font-family: var(--font-body, system-ui, sans-serif);
  }
  .rubber-band {
    fill: var(--indigo, #4f46e5);
    fill-opacity: 0.08;
    stroke: var(--indigo, #4f46e5);
    stroke-width: 1;
    stroke-dasharray: 4 3;
    pointer-events: none;
  }
  .capture {
    fill: transparent;
    cursor: crosshair;
    touch-action: none;
    user-select: none;
    -webkit-user-select: none;
  }
</style>
