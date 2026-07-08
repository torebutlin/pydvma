<script lang="ts">
  /**
   * Frequency-band brush for the Nyquist view (round-5 item 4, Tore's design).
   *
   * A narrow magnitude-|H|(f) strip rendered ABOVE the Nyquist plot, spanning
   * the FULL committed frequency extent, with a highlighted draggable band that
   * is the CURRENT shared/committed frequency range — the SAME `tf.range.x`
   * that Calc, Fit and the windowed Nyquist locus all read. Interacting with
   * the band scrubs that range, so the Nyquist locus (and the fit window) can
   * be steered directly from here:
   *   - drag the band body → TRANSLATE the range;
   *   - drag either edge handle → RESIZE that end;
   *   - drag on empty strip → CREATE a fresh band;
   *   - double-click the strip → reset to the FULL range.
   *
   * Like the plot's pan gesture, a drag previews LOCALLY and commits EXACTLY
   * ONE `onchange` on release (the parent routes it through `viewState.setRange`
   * so the toolbar's curl undo/redo captures each brush edit as one step).
   *
   * The strip is intentionally minimal + fast: the magnitude curves are
   * decimated to ~2 samples per pixel before the path is built.
   */
  import { fmtTick } from '../lib/plot/scales';

  interface StripLine { x: ArrayLike<number>; y: ArrayLike<number>; color: string; }

  let {
    lines,
    fullExtent,
    band,
    xScale = 'lin',
    onchange,
    onfull,
  }: {
    /** |H|(f) magnitude lines (y already in the plot's dB/linear units) over the full extent. */
    lines: StripLine[];
    /** Full frequency extent [fmin, fmax] the strip spans. */
    fullExtent: [number, number];
    /** Current committed frequency band [lo, hi] (the highlighted selection). */
    band: [number, number];
    /** Frequency axis scale, matched to the TF plot's x scale. */
    xScale?: 'lin' | 'log';
    /** Fired once on release with the new committed band. */
    onchange: (lo: number, hi: number) => void;
    /** Fired on double-click: reset to the full extent. */
    onfull: () => void;
  } = $props();

  const H = 58;                 // strip height (px)
  const PAD_L = 8, PAD_R = 8;   // horizontal insets so edge handles never clip
  const TOP = 4, BOT = 16;      // vertical insets (BOT leaves room for tick labels)
  const HANDLE_PX = 7;          // edge-grab tolerance

  let width = $state(0);
  let svgEl: SVGSVGElement | undefined = $state();

  const innerW = $derived(Math.max(1, width - PAD_L - PAD_R));
  const plotH = $derived(H - TOP - BOT);

  // Log-x mapping (matches the plot) when requested and the extent is positive.
  const log = $derived(xScale === 'log' && fullExtent[0] > 0 && fullExtent[1] > 0);
  const lfmin = $derived(log ? Math.log10(fullExtent[0]) : 0);
  const lfmax = $derived(log ? Math.log10(fullExtent[1]) : 1);

  /** Frequency → strip px (clamped to the plot area). */
  function toPx(f: number): number {
    const [fmin, fmax] = fullExtent;
    let t: number;
    if (log) {
      const lf = Math.log10(Math.max(f, fullExtent[0]));
      t = (lf - lfmin) / (lfmax - lfmin || 1);
    } else {
      t = (f - fmin) / (fmax - fmin || 1);
    }
    return PAD_L + Math.min(1, Math.max(0, t)) * innerW;
  }

  /** Strip px → frequency (clamped to the full extent). */
  function toF(px: number): number {
    const [fmin, fmax] = fullExtent;
    const t = Math.min(1, Math.max(0, (px - PAD_L) / (innerW || 1)));
    const f = log ? 10 ** (lfmin + t * (lfmax - lfmin)) : fmin + t * (fmax - fmin);
    return Math.min(fmax, Math.max(fmin, f));
  }

  // ---- magnitude curves (auto-scaled to their dB/linear extent) ----
  const yExtent = $derived.by<[number, number]>(() => {
    let lo = Infinity, hi = -Infinity;
    for (const l of lines) {
      for (let i = 0; i < l.y.length; i++) {
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
      const X = toPx(l.x[i]), Y = toPy(l.y[i]);
      if (!Number.isFinite(X) || !Number.isFinite(Y)) continue;
      d += (d ? 'L' : 'M') + X.toFixed(1) + ',' + Y.toFixed(1);
    }
    return d;
  }

  // ---- drag state (local preview; commits once on release) ----
  type DragMode = 'move' | 'resize-lo' | 'resize-hi' | 'create';
  let dragMode: DragMode | null = null;
  let dragPointer = 0;
  let grabOffset = 0;           // for 'move': px between pointer and band lo
  let createAnchor = 0;        // for 'create': freq where the drag began
  let preview = $state<[number, number] | null>(null);

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

  function onDown(e: PointerEvent) {
    if (e.button !== 0) return;
    const px = localX(e);
    const lo = toPx(band[0]), hi = toPx(band[1]);
    if (Math.abs(px - lo) <= HANDLE_PX) dragMode = 'resize-lo';
    else if (Math.abs(px - hi) <= HANDLE_PX) dragMode = 'resize-hi';
    else if (px > lo && px < hi) { dragMode = 'move'; grabOffset = px - lo; }
    else { dragMode = 'create'; createAnchor = toF(px); }
    dragPointer = e.pointerId;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    onMove(e);   // seed the preview immediately
  }

  function onMove(e: PointerEvent) {
    if (dragMode === null || e.pointerId !== dragPointer) return;
    const px = localX(e);
    const f = toF(px);
    const [fmin, fmax] = fullExtent;
    let lo = band[0], hi = band[1];
    if (dragMode === 'resize-lo') { lo = Math.min(f, band[1]); hi = band[1]; }
    else if (dragMode === 'resize-hi') { lo = band[0]; hi = Math.max(f, band[0]); }
    else if (dragMode === 'create') { lo = Math.min(createAnchor, f); hi = Math.max(createAnchor, f); }
    else {                                         // move: translate keeping width
      const width = band[1] - band[0];
      const newLoPx = px - grabOffset;
      lo = toF(newLoPx);
      // Preserve width in DATA units for a linear axis; for log, translate by px
      // then re-derive hi so the visual width stays put.
      hi = log ? toF(newLoPx + (hiPx - loPx)) : lo + width;
      if (hi > fmax) { hi = fmax; lo = log ? toF(toPx(fmax) - (hiPx - loPx)) : fmax - width; }
      if (lo < fmin) { lo = fmin; hi = log ? toF(toPx(fmin) + (hiPx - loPx)) : fmin + width; }
    }
    preview = [Math.max(fmin, lo), Math.min(fmax, hi)];
  }

  function onUp(e: PointerEvent) {
    if (dragMode === null || e.pointerId !== dragPointer) return;
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch { /* already released */ }
    const p = preview;
    dragMode = null; dragPointer = 0; preview = null;
    if (!p) return;
    const [lo, hi] = p;
    // Reject a degenerate band (a click or a sub-pixel drag) — keep the committed one.
    if (!(hi > lo) || toPx(hi) - toPx(lo) < 3) return;
    if (lo !== band[0] || hi !== band[1]) onchange(lo, hi);
  }

  function onCancel(e: PointerEvent) {
    if (e.pointerId !== dragPointer) return;
    dragMode = null; dragPointer = 0; preview = null;
  }
</script>

<div class="brush" data-testid="nyquist-brush" bind:clientWidth={width}>
  <div class="brush-head">
    <span class="brush-lab">frequency band</span>
    <span class="brush-val" data-testid="nyquist-brush-readout"
      >{fmtTick(shownBand[0], shownBand[1] - shownBand[0])} – {fmtTick(shownBand[1], shownBand[1] - shownBand[0])} Hz</span>
  </div>
  {#if width > 0}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <svg
      bind:this={svgEl}
      class="brush-svg"
      viewBox="0 0 {width} {H}"
      height={H}
      aria-label="Frequency band: {shownBand[0].toFixed(1)} to {shownBand[1].toFixed(1)} Hz"
      onpointerdown={onDown}
      onpointermove={onMove}
      onpointerup={onUp}
      onpointercancel={onCancel}
      onlostpointercapture={onCancel}
      ondblclick={onfull}
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
      <rect class="band" data-testid="nyquist-brush-band"
        x={loPx} y={TOP} width={Math.max(1, hiPx - loPx)} height={plotH} />
      <line class="handle" data-testid="nyquist-brush-handle-lo" x1={loPx} y1={TOP} x2={loPx} y2={TOP + plotH} />
      <line class="handle" data-testid="nyquist-brush-handle-hi" x1={hiPx} y1={TOP} x2={hiPx} y2={TOP + plotH} />
      <!-- End tick labels for orientation. -->
      <text class="edge" x={PAD_L} y={H - 4} text-anchor="start">{fmtTick(fullExtent[0], fullExtent[1] - fullExtent[0])}</text>
      <text class="edge" x={PAD_L + innerW} y={H - 4} text-anchor="end">{fmtTick(fullExtent[1], fullExtent[1] - fullExtent[0])}</text>
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
    align-items: baseline;
    justify-content: space-between;
    padding: 0 2px 2px;
  }
  .brush-lab {
    font: 600 11px var(--font-body, system-ui, sans-serif);
    color: var(--muted, #66708a);
    letter-spacing: 0.02em;
  }
  .brush-val {
    font: 11px var(--font-mono, ui-monospace, Menlo, monospace);
    color: var(--text, #1b2437);
  }
  .brush-svg {
    display: block;
    width: 100%;
    touch-action: none;
    cursor: ew-resize;
  }
  .strip-bg {
    fill: #f6f7fa;
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
  .handle {
    stroke: var(--indigo, #4f46e5);
    stroke-width: 2;
    pointer-events: none;
  }
  .edge {
    fill: var(--muted, #66708a);
    font: 10px var(--font-mono, ui-monospace, Menlo, monospace);
    pointer-events: none;
  }
</style>
