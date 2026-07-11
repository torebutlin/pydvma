<script lang="ts">
  /**
   * FREQUENCY NAVIGATOR — the frequency-navigation strip for ALL frequency-x
   * views (the frequency view + every tf plotType; the Nyquist view mounts it
   * exactly as before). Design: dev/plans/2026-07-11-freq-navigator-design.md.
   * Grew out of the round-5 Nyquist brush (item 4, Tore's design; round-6 item
   * 6 v2), which is why the gesture code below is unchanged.
   *
   * A narrow magnitude strip rendered ABOVE the plot, spanning the strip's
   * DOMAIN (the `scope` bandwidth-of-interest if set, else the full extent),
   * with a highlighted draggable band that is the CURRENT shared/committed
   * frequency window — the SAME `tf.range.x` that Calc, Fit and the windowed
   * Nyquist locus all read. Interacting with the band scrubs that window, so
   * the locus (and the fit window) can be steered directly from here:
   *   - drag the band BODY → TRANSLATE the range (cursor: grab/grabbing;
   *     the interior is a generous target — the edge grips never swallow it);
   *   - drag either edge handle → RESIZE that end (cursor: ew-resize);
   *   - drag on empty strip → CREATE a fresh band (cursor: crosshair);
   *   - double-click the strip → HOME: window → scope (or the full extent
   *     when unscoped) — the parent's `onhome` decides;
   *   - the two numeric fields in the head → type an exact min/max (Hz),
   *     committed on change / Enter;
   *   - the ‹ › head buttons → STEP the window to the previous/next detected
   *     magnitude peak (keeping its width; disabled when there is none that
   *     way — see lib/plot/peaks).
   * Fitted-mode fn markers (the `modeTicks` prop) are drawn as small triangles
   * along the strip so it doubles as a mode map (dimmed for muted modes).
   *
   * SCOPE (bandwidth-of-interest): when a `scope` is set the strip zooms to
   * span it, and a thin context ribbon appears above — the full extent in
   * miniature with the scope as its own draggable band (double-click the ribbon
   * clears the scope). The ⤢ head button scopes the strip to the current
   * window; when the window lies wholly outside the scoped strip an off-scope
   * arrow points toward it. Scope changes are NOT undoable, so the ribbon needs
   * no transient protocol — `onscope` fires once on release.
   *
   * v2 LIVE re-windowing (round-6 item 6): a drag no longer waits for release.
   * While the pointer moves the strip emits `onpreview` (throttled to one
   * animation frame) so the main plot re-windows CONTINUOUSLY; on release it
   * emits `onchange` once. The parent routes the live frames through
   * `viewState.setRangeLive` (no history) and the release through
   * `commitTransient`, so the whole gesture is a SINGLE undo step — the round-5
   * snapshot history never fills with 60 entries per drag. The drag math is
   * anchored to the band captured at pointer-down (`baseLo`/`baseHi`), NOT the
   * live `band` prop, so live re-windowing under the pointer can't feed back
   * into the reference frame.
   *
   * The strip is intentionally minimal + fast: the magnitude curves are
   * decimated to ~2 samples per pixel before the path is built.
   */
  import { fmtTick } from '../lib/plot/scales';
  import { detectPeaks, stepWindow } from '../lib/plot/peaks';

  interface StripLine { x: ArrayLike<number>; y: ArrayLike<number>; color: string; }

  let {
    lines,
    fullExtent,
    band,
    scope = null,
    xScale = 'lin',
    modeTicks = [],
    onchange,
    onpreview,
    onstart,
    oncancel,
    onhome,
    onscope,
  }: {
    /** Magnitude lines (y in the strip's own units) over the FULL extent. */
    lines: StripLine[];
    /** Full frequency extent [fmin, fmax] of the data. */
    fullExtent: [number, number];
    /** Current committed frequency window [lo, hi] (the highlighted band). */
    band: [number, number];
    /** Bandwidth-of-interest the strip spans; null ⇒ full extent (no ribbon). */
    scope?: [number, number] | null;
    /** Frequency axis scale, matched to the main plot's x scale. */
    xScale?: 'lin' | 'log';
    /** Fitted-mode markers (fn in Hz + muted flag); empty ⇒ no ticks. */
    modeTicks?: { fn: number; muted: boolean }[];
    /** Fired once on release (numeric-field commit / peak-step) with the new window. */
    onchange: (lo: number, hi: number) => void;
    /** Per-animation-frame live band while dragging (no history entry). */
    onpreview?: (lo: number, hi: number) => void;
    /** Fired at drag start so the parent can open a transient (one-undo) gesture. */
    onstart?: () => void;
    /** Fired when a drag is abandoned — parent reverts any live preview. */
    oncancel?: () => void;
    /** Double-click the strip: window → scope (or full extent when unscoped). */
    onhome: () => void;
    /** Scope commit: ⤢ button / ribbon drag release; null clears the scope. */
    onscope: (s: [number, number] | null) => void;
  } = $props();

  const H = 58;                 // strip height (px)
  const PAD_L = 8, PAD_R = 8;   // horizontal insets so edge handles never clip
  const TOP = 4, BOT = 16;      // vertical insets (BOT leaves room for tick labels)
  const HANDLE_PX = 6;          // max edge-grab tolerance (px)

  let width = $state(0);
  let svgEl: SVGSVGElement | undefined = $state();

  const innerW = $derived(Math.max(1, width - PAD_L - PAD_R));
  const plotH = $derived(H - TOP - BOT);

  /** The interval the strip spans: the scope, else the full extent. */
  const domain = $derived<[number, number]>(scope ?? fullExtent);

  // Log-x mapping (matches the plot) when requested and the domain is positive.
  const log = $derived(xScale === 'log' && domain[0] > 0 && domain[1] > 0);
  const lfmin = $derived(log ? Math.log10(domain[0]) : 0);
  const lfmax = $derived(log ? Math.log10(domain[1]) : 1);

  // Peak-step targets (design §peak-stepping): detection runs on the strip's
  // own lines within the domain; a null target disables that button. Uses the
  // COMMITTED band (not the live preview) so targets are stable mid-drag.
  // (Declared after `log` so the derived reads a value that's already in scope.)
  const peaks = $derived(detectPeaks(lines, domain, log));
  const prevTarget = $derived(stepWindow(peaks, band, domain, -1, log));
  const nextTarget = $derived(stepWindow(peaks, band, domain, 1, log));

  /** Frequency → strip px (clamped to the plot area). */
  function toPx(f: number): number {
    const [fmin, fmax] = domain;
    let t: number;
    if (log) {
      const lf = Math.log10(Math.max(f, domain[0]));
      t = (lf - lfmin) / (lfmax - lfmin || 1);
    } else {
      t = (f - fmin) / (fmax - fmin || 1);
    }
    return PAD_L + Math.min(1, Math.max(0, t)) * innerW;
  }

  /** Strip px → frequency (clamped to the strip's domain). */
  function toF(px: number): number {
    const [fmin, fmax] = domain;
    const t = Math.min(1, Math.max(0, (px - PAD_L) / (innerW || 1)));
    const f = log ? 10 ** (lfmin + t * (lfmax - lfmin)) : fmin + t * (fmax - fmin);
    return Math.min(fmax, Math.max(fmin, f));
  }

  // ---- magnitude curves (auto-scaled to their dB/linear extent) ----
  // Only IN-DOMAIN samples set the y-extent, so a scoped strip auto-scales to
  // the shape it actually shows — not to peaks that lie outside the scope.
  const yExtent = $derived.by<[number, number]>(() => {
    let lo = Infinity, hi = -Infinity;
    for (const l of lines) {
      for (let i = 0; i < l.y.length; i++) {
        if (l.x[i] < domain[0] || l.x[i] > domain[1]) continue;
        const v = l.y[i];
        if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
      }
    }
    if (lo === Infinity) return [0, 1];
    if (lo === hi) return [lo - 1, hi + 1];
    return [lo, hi];
  });

  /** Magnitude value → strip py (inverted; padded ~8% top/bottom). */
  function toPy(v: number): number {
    const [lo, hi] = yExtent;
    const pad = (hi - lo) * 0.08 || 1;
    const t = (v - (lo - pad)) / ((hi + pad) - (lo - pad));
    return TOP + (1 - Math.min(1, Math.max(0, t))) * plotH;
  }

  /** Decimated SVG path for one magnitude line (≤ ~2 samples/px). */
  function pathFor(l: StripLine): string {
    const n = l.x.length;
    if (n === 0 || innerW <= 0) return '';
    const budget = Math.max(64, Math.floor(innerW * 2));
    const step = Math.max(1, Math.floor(n / budget));
    let d = '';
    for (let i = 0; i < n; i += step) {
      if (l.x[i] < domain[0] || l.x[i] > domain[1]) continue;   // scoped strip: don't pile clamped points at the edges
      const X = toPx(l.x[i]), Y = toPy(l.y[i]);
      if (!Number.isFinite(X) || !Number.isFinite(Y)) continue;
      d += (d ? 'L' : 'M') + X.toFixed(1) + ',' + Y.toFixed(1);
    }
    return d;
  }

  // ---- hit zones + cursors ----
  type Zone = 'move' | 'resize-lo' | 'resize-hi' | 'create';

  /**
   * The interaction zone under strip-px `px`, measured against the CURRENT
   * committed band. The edge grip shrinks with the band so a narrow band always
   * keeps a body zone (fix for round-6 item 6a: the two 7-px grips used to
   * swallow the whole band, leaving nothing to grab for a translate).
   */
  function zoneAt(px: number): Zone {
    const lo = toPx(band[0]), hi = toPx(band[1]);
    const bw = hi - lo;
    const edge = Math.min(HANDLE_PX, bw * 0.25);
    if (bw > 6 && Math.abs(px - lo) <= edge) return 'resize-lo';
    if (bw > 6 && Math.abs(px - hi) <= edge) return 'resize-hi';
    if (px >= lo && px <= hi) return 'move';
    return 'create';
  }

  let hoverZone = $state<Zone>('create');
  /** Cursor: the drag zone while dragging, else the hover zone. */
  const activeCursor = $derived.by(() => {
    const z = dragMode ?? hoverZone;
    if (z === 'move') return dragMode ? 'grabbing' : 'grab';
    if (z === 'resize-lo' || z === 'resize-hi') return 'ew-resize';
    return 'crosshair';
  });

  // ---- drag state (local preview; live frames throttled to rAF) ----
  let dragMode = $state<Zone | null>(null);
  let dragPointer = 0;
  let grabOffset = 0;           // for 'move': px between pointer and band lo (at down)
  let createAnchor = 0;        // for 'create': freq where the drag began
  let baseLo = 0, baseHi = 0;  // band captured at pointer-down (drag reference frame)
  let preview = $state<[number, number] | null>(null);

  let rafId = 0;
  let pendingPreview: [number, number] | null = null;

  /** The band the strip currently DISPLAYS: the live preview, or the committed prop. */
  const shownBand = $derived<[number, number]>(preview ?? band);
  const loPx = $derived(toPx(shownBand[0]));
  const hiPx = $derived(toPx(shownBand[1]));

  function localX(e: PointerEvent): number {
    if (!svgEl) return 0;
    const r = svgEl.getBoundingClientRect();
    const sx = r.width ? width / r.width : 1;
    return (e.clientX - r.left) * sx;
  }

  /** Emit `onpreview` at most once per frame with the latest previewed band. */
  function schedulePreview() {
    if (!onpreview || rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      if (pendingPreview && onpreview) onpreview(pendingPreview[0], pendingPreview[1]);
    });
  }
  function cancelRaf() {
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    pendingPreview = null;
  }

  function onDown(e: PointerEvent) {
    if (e.button !== 0) return;
    const px = localX(e);
    baseLo = band[0]; baseHi = band[1];
    const zone = zoneAt(px);
    dragMode = zone;
    if (zone === 'move') { grabOffset = px - toPx(band[0]); preview = [baseLo, baseHi]; }
    else if (zone === 'create') { createAnchor = toF(px); preview = [createAnchor, createAnchor]; }
    else { preview = [baseLo, baseHi]; }   // resize starts at the current band
    dragPointer = e.pointerId;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    onstart?.();                            // parent opens a transient (one-undo) gesture
  }

  /** Pointer move: drag the band (live) when a gesture is active, else track the hover cursor. */
  function onMove(e: PointerEvent) {
    if (dragMode === null) { hoverZone = zoneAt(localX(e)); return; }
    if (e.pointerId !== dragPointer) return;
    const px = localX(e);
    const f = toF(px);
    const [fmin, fmax] = domain;   // the window is dragged within the strip's spanned domain (scope, else full)
    let lo = baseLo, hi = baseHi;
    if (dragMode === 'resize-lo') { lo = Math.min(f, baseHi); hi = baseHi; }
    else if (dragMode === 'resize-hi') { lo = baseLo; hi = Math.max(f, baseLo); }
    else if (dragMode === 'create') { lo = Math.min(createAnchor, f); hi = Math.max(createAnchor, f); }
    else {                                         // move: translate keeping width
      const w = baseHi - baseLo;
      const newLoPx = px - grabOffset;
      lo = toF(newLoPx);
      // Preserve width in DATA units for a linear axis; for log, translate by px
      // then re-derive hi so the visual width stays put.
      const basePxW = toPx(baseHi) - toPx(baseLo);
      hi = log ? toF(newLoPx + basePxW) : lo + w;
      if (hi > fmax) { hi = fmax; lo = log ? toF(toPx(fmax) - basePxW) : fmax - w; }
      if (lo < fmin) { lo = fmin; hi = log ? toF(toPx(fmin) + basePxW) : fmin + w; }
    }
    preview = [Math.max(fmin, lo), Math.min(fmax, hi)];
    // Live re-window (throttled): don't emit on a sub-pixel jitter click.
    if (toPx(preview[1]) - toPx(preview[0]) >= 3) {
      pendingPreview = preview;
      schedulePreview();
    }
  }

  function onUp(e: PointerEvent) {
    if (dragMode === null || e.pointerId !== dragPointer) return;
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch { /* already released */ }
    const p = preview;
    dragMode = null; dragPointer = 0; preview = null;
    cancelRaf();
    if (!p) { oncancel?.(); return; }
    const [lo, hi] = p;
    // Reject a degenerate band (a click / sub-pixel drag) or a no-move gesture —
    // measured against the PRE-DRAG base (the live band has been scrubbing along
    // with the preview, so it can't be the reference). Revert the live preview.
    const degenerate = !(hi > lo) || toPx(hi) - toPx(lo) < 3;
    const unchanged = lo === baseLo && hi === baseHi;
    if (degenerate || unchanged) { oncancel?.(); return; }
    onchange(lo, hi);
  }

  function onCancel(e: PointerEvent) {
    if (e.pointerId !== dragPointer) return;
    dragMode = null; dragPointer = 0; preview = null;
    cancelRaf();
    oncancel?.();
  }

  function onLeave() {
    if (dragMode === null) hoverZone = 'create';
  }

  // ---- numeric min/max fields ----
  /** Compact, editable rendering of a band edge (Hz). */
  function fmtNum(v: number): string {
    if (!Number.isFinite(v)) return '';
    const a = Math.abs(v);
    if (a >= 100) return v.toFixed(0);
    if (a >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }

  /** Clamp + validate a typed [lo, hi] against the strip's domain, then commit once. */
  function commitFields(rawLo: string, rawHi: string) {
    let lo = parseFloat(rawLo), hi = parseFloat(rawHi);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return;   // ignore garbage input
    const [fmin, fmax] = domain;
    lo = Math.min(Math.max(lo, fmin), fmax);
    hi = Math.min(Math.max(hi, fmin), fmax);
    if (!(hi > lo)) return;                                      // reject a degenerate/inverted band
    if (lo === band[0] && hi === band[1]) return;               // no change
    onchange(lo, hi);
  }
  const commitLo = (raw: string) => commitFields(raw, String(band[1]));
  const commitHi = (raw: string) => commitFields(String(band[0]), raw);
  function onFieldKey(e: KeyboardEvent) {
    if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();  // blur → change → commit
  }

  // ── scope ribbon (full-extent miniature; only rendered when scoped) ──
  const RH = 14;                     // ribbon height (px)
  const rLog = $derived(xScale === 'log' && fullExtent[0] > 0 && fullExtent[1] > 0);
  const rlMin = $derived(rLog ? Math.log10(fullExtent[0]) : 0);
  const rlMax = $derived(rLog ? Math.log10(fullExtent[1]) : 1);

  function toPxR(f: number): number {
    const [fmin, fmax] = fullExtent;
    const t = rLog
      ? (Math.log10(Math.max(f, fmin)) - rlMin) / (rlMax - rlMin || 1)
      : (f - fmin) / (fmax - fmin || 1);
    return PAD_L + Math.min(1, Math.max(0, t)) * innerW;
  }
  function toFR(px: number): number {
    const [fmin, fmax] = fullExtent;
    const t = Math.min(1, Math.max(0, (px - PAD_L) / (innerW || 1)));
    const f = rLog ? 10 ** (rlMin + t * (rlMax - rlMin)) : fmin + t * (fmax - fmin);
    return Math.min(fmax, Math.max(fmin, f));
  }

  type RbZone = 'move' | 'resize-lo' | 'resize-hi' | null;
  let rbMode = $state<RbZone>(null);
  let rbPointer = 0;
  let rbGrabOffset = 0;
  let rbBaseLo = 0, rbBaseHi = 0;
  let rbPreview = $state<[number, number] | null>(null);
  let rbHover = $state<RbZone>(null);

  const shownScope = $derived<[number, number]>(rbPreview ?? (scope ?? fullExtent));
  const rLoPx = $derived(toPxR(shownScope[0]));
  const rHiPx = $derived(toPxR(shownScope[1]));

  function rbZoneAt(px: number): RbZone {
    if (!scope) return null;
    const lo = toPxR(scope[0]), hi = toPxR(scope[1]);
    const edge = Math.min(HANDLE_PX, (hi - lo) * 0.25);
    if (hi - lo > 6 && Math.abs(px - lo) <= edge) return 'resize-lo';
    if (hi - lo > 6 && Math.abs(px - hi) <= edge) return 'resize-hi';
    if (px >= lo && px <= hi) return 'move';
    return null;
  }
  const ribbonCursor = $derived.by(() => {
    const z = rbMode ?? rbHover;
    if (z === 'move') return rbMode ? 'grabbing' : 'grab';
    if (z === 'resize-lo' || z === 'resize-hi') return 'ew-resize';
    return 'default';
  });

  function rbLocalX(e: PointerEvent): number {
    const el = e.currentTarget as SVGSVGElement;
    const r = el.getBoundingClientRect();
    const sx = r.width ? width / r.width : 1;
    return (e.clientX - r.left) * sx;
  }
  function rbDown(e: PointerEvent) {
    if (e.button !== 0 || !scope) return;
    const px = rbLocalX(e);
    const z = rbZoneAt(px);
    if (!z) return;
    rbMode = z; rbBaseLo = scope[0]; rbBaseHi = scope[1];
    rbGrabOffset = px - toPxR(scope[0]);
    rbPreview = [rbBaseLo, rbBaseHi];
    rbPointer = e.pointerId;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }
  function rbMove(e: PointerEvent) {
    if (rbMode === null) { rbHover = rbZoneAt(rbLocalX(e)); return; }
    if (e.pointerId !== rbPointer) return;
    const px = rbLocalX(e);
    const f = toFR(px);
    const [fmin, fmax] = fullExtent;
    let lo = rbBaseLo, hi = rbBaseHi;
    if (rbMode === 'resize-lo') lo = Math.min(f, rbBaseHi);
    else if (rbMode === 'resize-hi') hi = Math.max(f, rbBaseLo);
    else {
      const basePxW = toPxR(rbBaseHi) - toPxR(rbBaseLo);
      const newLoPx = px - rbGrabOffset;
      lo = toFR(newLoPx); hi = toFR(newLoPx + basePxW);
      if (hi >= fmax) { hi = fmax; lo = toFR(toPxR(fmax) - basePxW); }
      if (lo <= fmin) { lo = fmin; hi = toFR(toPxR(fmin) + basePxW); }
    }
    rbPreview = [Math.max(fmin, lo), Math.min(fmax, hi)];
  }
  function rbUp(e: PointerEvent) {
    if (rbMode === null || e.pointerId !== rbPointer) return;
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch { /* released */ }
    const p = rbPreview;
    rbMode = null; rbPointer = 0; rbPreview = null;
    if (!p || !(p[1] > p[0])) return;
    if (p[0] === rbBaseLo && p[1] === rbBaseHi) return;   // click / no-move
    onscope(p);
  }
  function rbCancel(e: PointerEvent) {
    if (e.pointerId !== rbPointer) return;
    rbMode = null; rbPointer = 0; rbPreview = null;
  }

  $effect(() => () => cancelRaf());   // drop a pending live frame on unmount
</script>

<div class="brush" data-testid="freq-nav" bind:clientWidth={width}>
  <div class="brush-head">
    <span class="brush-lab">frequency band</span>
    <span class="nav-btns">
      <button
        class="nbtn"
        type="button"
        data-testid="freq-nav-prev"
        title="Previous peak (window keeps its width)"
        disabled={!prevTarget}
        onclick={() => prevTarget && onchange(prevTarget[0], prevTarget[1])}
      >‹</button>
      <button
        class="nbtn"
        type="button"
        data-testid="freq-nav-next"
        title="Next peak (window keeps its width)"
        disabled={!nextTarget}
        onclick={() => nextTarget && onchange(nextTarget[0], nextTarget[1])}
      >›</button>
      <button
        class="nbtn"
        type="button"
        data-testid="freq-nav-scope-btn"
        title="Scope the strip to the current window (double-click the ribbon to clear)"
        onclick={() => onscope([band[0], band[1]])}
      >⤢</button>
    </span>
    <span class="brush-fields">
      <input
        class="fld mono"
        type="number"
        step="any"
        inputmode="decimal"
        data-testid="freq-nav-min"
        aria-label="Frequency band min"
        value={fmtNum(shownBand[0])}
        onchange={(e) => commitLo(e.currentTarget.value)}
        onkeydown={onFieldKey}
      />
      <span class="dash">–</span>
      <input
        class="fld mono"
        type="number"
        step="any"
        inputmode="decimal"
        data-testid="freq-nav-max"
        aria-label="Frequency band max"
        value={fmtNum(shownBand[1])}
        onchange={(e) => commitHi(e.currentTarget.value)}
        onkeydown={onFieldKey}
      />
      <span class="unit">Hz</span>
    </span>
  </div>
  {#if scope && width > 0}
    <!-- Context ribbon: full extent in miniature, the scope highlighted. Body
         drag translates, edge drag resizes, double-click clears the scope.
         Local preview only; onscope fires once on release (scope is not
         undoable, so no transient protocol needed). -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <svg
      class="ribbon"
      viewBox="0 0 {width} {RH}"
      height={RH}
      data-testid="freq-nav-ribbon"
      style="cursor: {ribbonCursor}"
      aria-label="Scope: {shownScope[0].toFixed(1)} to {shownScope[1].toFixed(1)} Hz of {fullExtent[0].toFixed(1)}–{fullExtent[1].toFixed(1)} Hz"
      onpointerdown={rbDown}
      onpointermove={rbMove}
      onpointerup={rbUp}
      onpointercancel={rbCancel}
      onlostpointercapture={rbCancel}
      ondblclick={() => onscope(null)}
    >
      <rect class="strip-bg" x={PAD_L} y={1} width={innerW} height={RH - 2} />
      <rect class="mask" x={PAD_L} y={1} width={Math.max(0, rLoPx - PAD_L)} height={RH - 2} />
      <rect class="mask" x={rHiPx} y={1} width={Math.max(0, PAD_L + innerW - rHiPx)} height={RH - 2} />
      <rect class="rband" data-testid="freq-nav-ribbon-band"
        x={rLoPx} y={1} width={Math.max(1, rHiPx - rLoPx)} height={RH - 2} />
    </svg>
  {/if}
  {#if width > 0}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <svg
      bind:this={svgEl}
      class="brush-svg"
      viewBox="0 0 {width} {H}"
      height={H}
      style="cursor: {activeCursor}"
      aria-label="Frequency band: {shownBand[0].toFixed(1)} to {shownBand[1].toFixed(1)} Hz"
      onpointerdown={onDown}
      onpointermove={onMove}
      onpointerup={onUp}
      onpointercancel={onCancel}
      onpointerleave={onLeave}
      onlostpointercapture={onCancel}
      ondblclick={onhome}
    >
      <rect class="strip-bg" x={PAD_L} y={TOP} width={innerW} height={plotH} />
      {#each lines as l, i (i)}
        {#if pathFor(l)}
          <path class="mag" d={pathFor(l)} stroke={l.color} />
        {/if}
      {/each}
      <!-- Dimmed masks over the unselected regions, so the band reads as the focus. -->
      <rect class="mask" x={PAD_L} y={TOP} width={Math.max(0, loPx - PAD_L)} height={plotH} />
      <rect class="mask" x={hiPx} y={TOP} width={Math.max(0, PAD_L + innerW - hiPx)} height={plotH} />
      <!-- Selected band + edge handles. -->
      <rect class="band" data-testid="freq-nav-band"
        x={loPx} y={TOP} width={Math.max(1, hiPx - loPx)} height={plotH} />
      <!-- Edge grips: a hairline + a rounded knob so the resizable ends read as distinct. -->
      <g class="handle" data-testid="freq-nav-handle-lo">
        <line x1={loPx} y1={TOP} x2={loPx} y2={TOP + plotH} />
        <rect class="knob" x={loPx - 2} y={TOP + plotH / 2 - 7} width="4" height="14" rx="2" />
      </g>
      <g class="handle" data-testid="freq-nav-handle-hi">
        <line x1={hiPx} y1={TOP} x2={hiPx} y2={TOP + plotH} />
        <rect class="knob" x={hiPx - 2} y={TOP + plotH / 2 - 7} width="4" height="14" rx="2" />
      </g>
      <!-- The committed window lies (partly) beyond the scoped strip: point at it. -->
      {#if band[1] < domain[0]}
        <path class="offscope" data-testid="freq-nav-offscope"
          d="M{PAD_L + 12},{TOP + plotH / 2 - 5} l-7,5 l7,5 z" />
      {:else if band[0] > domain[1]}
        <path class="offscope" data-testid="freq-nav-offscope"
          d="M{PAD_L + innerW - 12},{TOP + plotH / 2 - 5} l7,5 l-7,5 z" />
      {/if}
      <!-- End tick labels for orientation. -->
      <text class="edge" x={PAD_L} y={H - 4} text-anchor="start">{fmtTick(domain[0], domain[1] - domain[0])}</text>
      <text class="edge" x={PAD_L + innerW} y={H - 4} text-anchor="end">{fmtTick(domain[1], domain[1] - domain[0])}</text>
      <!-- Fitted-mode markers: one triangle per mode fn inside the domain
           (dimmed when muted) — the strip doubles as a mode map. -->
      {#each modeTicks as t, i (i)}
        {#if t.fn >= domain[0] && t.fn <= domain[1]}
          <path class="mtick" class:muted={t.muted} data-testid="freq-nav-tick"
            d="M{toPx(t.fn)},{TOP + 7} l-4,-7 l8,0 z" />
        {/if}
      {/each}
    </svg>
  {/if}
</div>

<style>
  .brush {
    flex: 0 0 auto;
    background: var(--surface, #fff);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: var(--radius, 10px);
    box-shadow: var(--shadow, 0 1px 3px rgba(16, 24, 40, 0.12));
    padding: 5px 8px 2px;
    margin-bottom: 6px;
  }
  .brush-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 0 2px 3px;
  }
  .brush-lab {
    font: 600 11px var(--font-body, system-ui, sans-serif);
    color: var(--muted, #66708a);
    letter-spacing: 0.02em;
  }
  .brush-fields {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: var(--muted, #66708a);
  }
  .brush-fields .fld {
    width: 62px;
    height: 22px;
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 5px;
    padding: 0 5px;
    background: var(--control-bg, #fff);
    color: var(--text, #1b2437);
    font: 11px var(--font-mono, ui-monospace, Menlo, monospace);
    text-align: right;
  }
  /* Drop the spinner arrows — the value is scrubbed by the band or typed. */
  .brush-fields .fld::-webkit-outer-spin-button,
  .brush-fields .fld::-webkit-inner-spin-button {
    appearance: none;
    margin: 0;
  }
  .brush-fields .fld {
    -moz-appearance: textfield;
    appearance: textfield;
  }
  .brush-fields .fld:focus {
    outline: none;
    border-color: var(--accent-soft-border, #c7d2fe);
  }
  .brush-fields .dash {
    font: 11px var(--font-mono, ui-monospace, Menlo, monospace);
  }
  .brush-fields .unit {
    font: 10px var(--font-mono, ui-monospace, Menlo, monospace);
  }
  .brush-svg {
    display: block;
    width: 100%;
    touch-action: none;
  }
  .strip-bg {
    fill: var(--surface-2);
  }
  .mag {
    fill: none;
    stroke-width: 1;
    opacity: 0.75;
  }
  .mask {
    fill: var(--surface, #fff);
    opacity: 0.62;
    pointer-events: none;
  }
  .band {
    fill: var(--indigo, #4f46e5);
    fill-opacity: 0.1;
    stroke: var(--indigo, #4f46e5);
    stroke-opacity: 0.55;
    stroke-width: 1;
    pointer-events: none;
  }
  .handle line {
    stroke: var(--indigo, #4f46e5);
    stroke-width: 2;
  }
  .handle .knob {
    fill: var(--indigo, #4f46e5);
    stroke: var(--surface, #fff);
    stroke-width: 1;
  }
  .handle {
    pointer-events: none;
  }
  .edge {
    fill: var(--muted, #66708a);
    font: 10px var(--font-mono, ui-monospace, Menlo, monospace);
    pointer-events: none;
  }
  .nav-btns { display: inline-flex; align-items: center; gap: 2px; }
  .nbtn {
    width: 22px; height: 20px;
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 5px;
    background: var(--control-bg, #fff);
    color: var(--muted, #66708a);
    font: 12px/1 var(--font-body, system-ui, sans-serif);
    cursor: pointer;
    padding: 0;
  }
  .nbtn:hover:not(:disabled) { color: var(--text, #1b2437); border-color: var(--accent-soft-border, #c7d2fe); }
  .nbtn:disabled { opacity: 0.35; cursor: default; }
  .ribbon { display: block; width: 100%; touch-action: none; margin-bottom: 2px; }
  .rband {
    fill: var(--indigo, #4f46e5);
    fill-opacity: 0.22;
    stroke: var(--indigo, #4f46e5);
    stroke-opacity: 0.7;
    stroke-width: 1;
  }
  .offscope { fill: var(--indigo, #4f46e5); opacity: 0.8; pointer-events: none; }
  .mtick { fill: var(--indigo, #4f46e5); opacity: 0.85; pointer-events: none; }
  .mtick.muted { opacity: 0.3; }
</style>
