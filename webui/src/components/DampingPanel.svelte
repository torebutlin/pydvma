<script lang="ts">
  /**
   * Interactive damping-fit panel (round-7 items 3+4) — the web rebuild of
   * the Qt `DampingFitWindow`, plus the new interactive controls Tore asked
   * for. Docked BELOW the sonogram plot area while open (App mounts it in
   * the sono host), so the sonogram itself stays visible with the draggable
   * start-time line overlaid.
   *
   * Two modes (Segmented toggle):
   * - `peaks` — the sonogram/CWT per-mode decay fits. Left chart: the
   *   start-slice magnitude spectrum (normalised min→max, the exact scale
   *   `peakutils.indexes` thresholds on) with the DRAGGABLE threshold line
   *   and the candidate peaks. Right chart: Re log(S) decay per fitted mode
   *   — sparse × data markers + the fitted line, palette-coloured, with a
   *   `f Hz, Qn=…` legend (the Untitled-23 screenshot's plot).
   * - `bands` — Schroeder band decays: EDC per band + dashed T60 fit lines,
   *   and the metrics table (EDT / T20 / T30 / T60 / Qn; NaN renders as an
   *   em-dash — insufficient decay range, not an error).
   *
   * The panel never talks to the engine: control commits update the damping
   * store then call `onrefit`, and the actions layer pushes decoded results
   * back into the store. Start time and threshold accept BLANK = auto (the
   * engine infers / uses its automatic choice, then echoes the resolved
   * value back into the field).
   */
  import type { DampingStore, DampingMode, BandLadder } from '../lib/stores/damping';
  import { LINE_PALETTE } from '../lib/stores/selection';
  import { niceTicks, fmtTick } from '../lib/plot/scales';
  import {
    seriesExtent, padDomain, polylinePoints, pxX, pxY, markerIndices,
    type MiniDomain,
  } from '../lib/plot/miniplot';
  import Segmented from './Segmented.svelte';

  let {
    damping,
    onrefit,
    onclose,
  }: {
    damping: DampingStore;
    /** Re-run the fit with the store's current knobs (debounced upstream). */
    onrefit: () => void;
    onclose: () => void;
  } = $props();

  const state = $derived($damping);

  // ---- mini-plot geometry (shared) ----
  const H = 170;
  const ML = 46, MR = 10, MT = 8, MB = 26;
  let specW = $state(360);   // bound to each chart host's clientWidth
  let decayW = $state(360);
  const iw = (w: number) => Math.max(40, w - ML - MR);
  const ih = H - MT - MB;

  // ---- peaks mode: spectrum (normalised) + threshold ----
  /** Slice magnitude normalised min→max — the scale the threshold lives on. */
  const specNorm = $derived.by(() => {
    const p = state.peaks;
    if (!p || p.sliceMag.length === 0) return null;
    const [lo, hi] = seriesExtent([p.sliceMag]);
    const span = hi - lo || 1;
    const norm = new Float64Array(p.sliceMag.length);
    for (let i = 0; i < norm.length; i++) norm[i] = (p.sliceMag[i] - lo) / span;
    return { freq: p.sliceFreq, norm, lo, span };
  });
  const specDom = $derived<MiniDomain | null>(specNorm && {
    x: padDomain(seriesExtent([specNorm.freq]), 0.02),
    y: [0, 1.06],
  });

  // Threshold drag: live-preview the line locally; commit (store + refit) on
  // release. The hit target is a fat invisible band around the 1px line.
  let dragThr = $state<number | null>(null);
  const shownThr = $derived(dragThr ?? state.threshold);
  let specSvg: SVGSVGElement | undefined = $state();
  function thrFromEvent(e: PointerEvent): number {
    const r = specSvg!.getBoundingClientRect();
    const frac = 1 - ((e.clientY - r.top) / r.height) * (H / ih) + MT / ih;
    return Math.min(1, Math.max(0, frac * 1.06));
  }
  function onThrDown(e: PointerEvent) {
    if (state.busy || !specDom) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragThr = thrFromEvent(e);
  }
  function onThrMove(e: PointerEvent) {
    if (dragThr === null) return;
    dragThr = thrFromEvent(e);
  }
  function onThrUp() {
    if (dragThr === null) return;
    damping.setThreshold(Number(dragThr.toPrecision(3)));
    dragThr = null;
    onrefit();
  }

  /**
   * Threshold display: 3 SIGNIFICANT figures, not fixed decimals — the
   * automatic choice can be tiny (e.g. 4e-4 on a peaky spectrum) and a
   * 3-decimal rounding would show it as a misleading "0".
   */
  const fmtThr = (v: number) => String(Number(v.toPrecision(3)));

  // ---- peaks mode: decay-fit chart ----
  const decayDom = $derived<MiniDomain | null>(state.peaks && state.peaks.fits.length > 0
    ? {
        x: padDomain(seriesExtent(state.peaks.fits.map((f) => f.tFit)), 0.03),
        y: padDomain(seriesExtent(state.peaks.fits.flatMap((f) => [f.realData, f.realFit])), 0.08),
      }
    : null);

  // ---- bands mode: EDC chart ----
  const edcDom = $derived<MiniDomain | null>(state.bands && state.bands.bandData.length > 0
    ? {
        x: padDomain(seriesExtent(state.bands.bandData.map((b) => b.edcT)), 0.02),
        // Show the useful top of the decay; the Schroeder tail dives to the
        // -300 dB floor, which would crush every fit window into the frame top.
        y: [-70, 3],
      }
    : null);

  const colour = (i: number) => LINE_PALETTE[i % LINE_PALETTE.length];
  const fmt1 = (v: number) => (Number.isFinite(v) ? v.toFixed(1) : '—');
  const fmt2 = (v: number) => (Number.isFinite(v) ? v.toFixed(2) : '—');

  // ---- numeric fields: blank = auto (null) ----
  function commitStart(e: Event) {
    const raw = (e.currentTarget as HTMLInputElement).value.trim();
    const v = raw === '' ? null : parseFloat(raw);
    if (v !== null && !Number.isFinite(v)) return;
    damping.setStartTime(v);
    onrefit();
  }
  function commitThreshold(e: Event) {
    const raw = (e.currentTarget as HTMLInputElement).value.trim();
    const v = raw === '' ? null : parseFloat(raw);
    if (v !== null && (!Number.isFinite(v) || v < 0 || v > 1)) return;
    damping.setThreshold(v);
    onrefit();
  }
</script>

{#snippet frame(w: number, dom: MiniDomain, xlab: string, ylab: string)}
  <!-- axes frame + ticks for one mini chart -->
  <rect x={ML} y={MT} width={iw(w)} height={ih} class="mini-frame" />
  {#each niceTicks(dom.x[0], dom.x[1], 5) as tv (tv)}
    {#if tv >= dom.x[0] && tv <= dom.x[1]}
      <text x={ML + pxX(tv, dom, iw(w))} y={H - 10} class="mini-tick" text-anchor="middle"
        >{fmtTick(tv, dom.x[1] - dom.x[0])}</text>
    {/if}
  {/each}
  {#each niceTicks(dom.y[0], dom.y[1], 4) as tv (tv)}
    {#if tv >= dom.y[0] && tv <= dom.y[1]}
      <text x={ML - 5} y={MT + pxY(tv, dom, ih) + 3} class="mini-tick" text-anchor="end"
        >{fmtTick(tv, dom.y[1] - dom.y[0])}</text>
    {/if}
  {/each}
  <text x={ML + iw(w) / 2} y={H - 0.5} class="mini-lab" text-anchor="middle">{xlab}</text>
  <text x={11} y={MT + ih / 2} class="mini-lab" text-anchor="middle"
    transform="rotate(-90 11 {MT + ih / 2})">{ylab}</text>
{/snippet}

<div class="damp-panel" data-testid="damping-panel">
  <div class="dp-bar">
    <Segmented
      testid="damping-mode-toggle"
      ariaLabel="Damping method"
      label="method"
      value={state.mode}
      onchange={(m: DampingMode) => { damping.setMode(m); onrefit(); }}
      options={[
        { value: 'peaks' as const, label: 'peaks', title: 'Find spectral peaks at the start time, fit each band’s decay (freq from phase)' },
        { value: 'bands' as const, label: 'bands', title: 'Band-pass filter bank + Schroeder decay integral (EDT / T20 / T30 / RT60 / Q)' },
      ]}
    />
    <label class="dp-field">
      <span>start (s)</span>
      <input data-testid="damping-start-input" inputmode="decimal" placeholder="auto"
        value={state.startTime === null ? '' : String(state.startTime)}
        onchange={commitStart} disabled={state.busy} />
    </label>
    {#if state.mode === 'peaks'}
      <label class="dp-field">
        <span>threshold</span>
        <input data-testid="damping-threshold-input" inputmode="decimal" placeholder="auto"
          value={shownThr === null ? '' : fmtThr(shownThr)}
          onchange={commitThreshold} disabled={state.busy} />
      </label>
    {:else}
      <label class="dp-field">
        <span>bands</span>
        <select data-testid="damping-ladder-select" value={state.ladder} disabled={state.busy}
          onchange={(e) => { damping.setLadder(e.currentTarget.value as BandLadder); onrefit(); }}>
          <option value="all">all (broadband)</option>
          <option value="octave">octave</option>
          <option value="third-octave">1/3 octave</option>
          <option value="tenth-decade">1/10 decade</option>
        </select>
      </label>
    {/if}
    <!-- Controls refit live; the explicit button covers changes made OUTSIDE
         the panel (e.g. the Sono card's STFT|CWT method switch, which the
         peaks fit follows). -->
    <button class="dp-refit" data-testid="damping-refit" onclick={onrefit}
      disabled={state.busy} title="Re-run the fit (picks up the card's STFT|CWT method)">Refit</button>
    {#if state.busy}<span class="dp-busy" role="status">fitting…</span>{/if}
    {#if state.error}<span class="dp-err" role="alert">{state.error}</span>{/if}
    <button class="dp-close" data-testid="damping-close" title="Close damping panel"
      aria-label="Close damping panel" onclick={onclose}>×</button>
  </div>

  {#if state.mode === 'peaks'}
    <div class="dp-charts">
      <div class="dp-chart" bind:clientWidth={specW}>
        {#if specNorm && specDom}
          <svg bind:this={specSvg} data-testid="damping-spectrum" viewBox="0 0 {specW} {H}"
            role="img" aria-label="Start-slice spectrum with peak threshold">
            {@render frame(specW, specDom, 'Frequency (Hz)', 'norm |S|')}
            <g clip-path="inset(0)">
              <polyline class="dp-spec-line"
                points={polylinePoints(specNorm.freq, specNorm.norm, specDom, iw(specW), ih)}
                transform="translate({ML},{MT})" />
              {#each Array.from(state.peaks!.peaksFreq) as pf, i (i)}
                <circle
                  cx={ML + pxX(pf, specDom, iw(specW))}
                  cy={MT + pxY((state.peaks!.peaksMag[i] - specNorm.lo) / specNorm.span, specDom, ih)}
                  r="3.4" class="dp-peak" />
              {/each}
              {#if shownThr !== null}
                <!-- the draggable threshold line: fat invisible hit band -->
                <line x1={ML} x2={ML + iw(specW)}
                  y1={MT + pxY(shownThr, specDom, ih)} y2={MT + pxY(shownThr, specDom, ih)}
                  class="dp-thr" data-testid="damping-threshold-line" />
                <rect x={ML} width={iw(specW)}
                  y={MT + pxY(shownThr, specDom, ih) - 7} height="14"
                  class="dp-thr-hit" style="cursor: ns-resize"
                  onpointerdown={onThrDown} onpointermove={onThrMove}
                  onpointerup={onThrUp} onpointercancel={() => (dragThr = null)} />
              {/if}
            </g>
          </svg>
        {:else}
          <p class="dp-note">No spectrum context — run Fit damping (a stale engine build hides the picker; reload if this persists).</p>
        {/if}
      </div>
      <div class="dp-chart" bind:clientWidth={decayW}>
        {#if state.peaks && decayDom}
          <svg data-testid="damping-decay" viewBox="0 0 {decayW} {H}" role="img"
            aria-label="Per-mode decay fits">
            {@render frame(decayW, decayDom, 'Time (s)', 'Re log(S)')}
            {#each state.peaks.fits as f, i (i)}
              <g transform="translate({ML},{MT})">
                {#each markerIndices(f.tFit.length) as k (k)}
                  <path class="dp-x" stroke={colour(i)}
                    d="M-2.6,-2.6 L2.6,2.6 M-2.6,2.6 L2.6,-2.6"
                    transform="translate({pxX(f.tFit[k], decayDom, iw(decayW))},{pxY(f.realData[k], decayDom, ih)})" />
                {/each}
                <polyline class="dp-fit" stroke={colour(i)}
                  points={polylinePoints(f.tFit, f.realFit, decayDom, iw(decayW), ih)} />
              </g>
            {/each}
          </svg>
          <div class="dp-legend" data-testid="damping-fit-legend">
            {#each state.peaks.fits as f, i (i)}
              <span class="dp-chip"><i style="background:{colour(i)}"></i>{fmt1(f.fPeak)} Hz, Qn={f.Qn.toFixed(0)}</span>
            {/each}
          </div>
        {:else if state.peaks}
          <!-- A completed fit with ZERO modes is a normal outcome (threshold
               too high / start line past the decay), not an error state. -->
          <div class="dp-legend" data-testid="damping-fit-legend">
            <span class="dp-note">No modes fitted — lower the threshold or move the start line.</span>
          </div>
        {:else}
          <p class="dp-note">No fits yet.</p>
        {/if}
      </div>
    </div>
  {:else}
    <div class="dp-charts">
      <div class="dp-chart" bind:clientWidth={specW}>
        {#if state.bands && edcDom}
          <svg data-testid="damping-edc" viewBox="0 0 {specW} {H}" role="img"
            aria-label="Band energy-decay curves">
            {@render frame(specW, edcDom, 'Time (s)', 'EDC (dB)')}
            {#each state.bands.bandData as b, i (i)}
              <g transform="translate({ML},{MT})">
                <polyline class="dp-edc" stroke={colour(i)}
                  points={polylinePoints(b.edcT, b.edcDb, edcDom, iw(specW), ih)} />
                {#if b.fitT && b.fitDb}
                  <polyline class="dp-edc-fit" stroke={colour(i)}
                    points={polylinePoints(b.fitT, b.fitDb, edcDom, iw(specW), ih)} />
                {/if}
              </g>
            {/each}
          </svg>
        {:else}
          <p class="dp-note">No band decays yet.</p>
        {/if}
      </div>
      <div class="dp-chart dp-table-host">
        {#if state.bands}
          <table class="dp-table" data-testid="damping-band-table">
            <thead>
              <tr><th>fc (Hz)</th><th>EDT (s)</th><th>T20 (s)</th><th>T30 (s)</th><th>T60 (s)</th><th>Qn</th></tr>
            </thead>
            <tbody>
              {#each Array.from(state.bands.fc) as fc, i (i)}
                <tr>
                  <td><i class="dp-dot" style="background:{colour(i)}"></i>{fmt1(fc)}</td>
                  <td>{fmt2(state.bands.EDT[i])}</td>
                  <td>{fmt2(state.bands.T20[i])}</td>
                  <td>{fmt2(state.bands.T30[i])}</td>
                  <td>{fmt2(state.bands.T60[i])}</td>
                  <td>{fmt1(state.bands.Qn[i])}</td>
                </tr>
              {/each}
            </tbody>
          </table>
          <p class="dp-note">— means that band's decay range was too small to fit (not an error). T60 prefers the T30 window, falling back to T20.</p>
        {:else}
          <p class="dp-note">No band metrics yet.</p>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .damp-panel {
    flex: none;
    border-top: 1px solid var(--border);
    background: var(--surface);
    padding: 6px 8px 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 46%;
    overflow: auto;
  }
  .dp-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .dp-field {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font: 11px var(--font-body, system-ui, sans-serif);
    color: var(--muted);
  }
  .dp-field input, .dp-field select {
    width: 74px;
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 11.5px;
    padding: 2px 5px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--control-bg);
    color: var(--text);
  }
  .dp-field select { width: auto; }
  .dp-refit {
    border: 1px solid var(--border);
    background: var(--control-bg);
    color: var(--text);
    font: 600 11px var(--font-body, system-ui, sans-serif);
    border-radius: 5px;
    height: 22px;
    padding: 0 8px;
    cursor: pointer;
  }
  .dp-refit:hover:not(:disabled) { background: var(--hover-bg); }
  .dp-refit:disabled { opacity: 0.5; cursor: default; }
  .dp-busy { font: italic 11px var(--font-body); color: var(--muted); }
  .dp-err { font: 11px var(--font-body); color: var(--danger); }
  .dp-close {
    margin-left: auto;
    border: none;
    background: transparent;
    color: var(--muted);
    font-size: 16px;
    line-height: 1;
    cursor: pointer;
    padding: 2px 6px;
    border-radius: 5px;
  }
  .dp-close:hover { background: var(--hover-bg); color: var(--text); }
  .dp-charts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    min-height: 0;
  }
  .dp-chart { min-width: 0; position: relative; }
  .dp-chart svg { display: block; width: 100%; height: auto; }
  .mini-frame { fill: none; stroke: var(--border); }
  .mini-tick {
    font: 9.5px var(--font-mono, ui-monospace, monospace);
    fill: var(--muted);
  }
  .mini-lab {
    font: 10px var(--font-body, system-ui, sans-serif);
    fill: var(--muted);
  }
  .dp-spec-line { fill: none; stroke: var(--indigo, #4f46e5); stroke-width: 1.3; }
  .dp-peak { fill: none; stroke: var(--danger, #dc2626); stroke-width: 1.4; }
  .dp-thr { stroke: var(--danger, #dc2626); stroke-width: 1.2; stroke-dasharray: 5 3; }
  .dp-thr-hit { fill: transparent; }
  .dp-x { stroke-width: 1.1; opacity: 0.75; }
  .dp-fit { fill: none; stroke-width: 2.4; }
  .dp-edc { fill: none; stroke-width: 1.4; opacity: 0.9; }
  .dp-edc-fit { fill: none; stroke-width: 2; stroke-dasharray: 6 3; }
  .dp-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; padding: 2px 4px; }
  .dp-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font: 10.5px var(--font-mono, ui-monospace, monospace);
    color: var(--text);
  }
  .dp-chip i { width: 14px; height: 3px; border-radius: 2px; display: inline-block; }
  .dp-dot {
    width: 8px; height: 8px; border-radius: 50%;
    display: inline-block; margin-right: 5px; vertical-align: baseline;
  }
  .dp-table-host { overflow: auto; }
  .dp-table {
    border-collapse: collapse;
    font: 11px var(--font-mono, ui-monospace, monospace);
    color: var(--text);
    width: 100%;
  }
  .dp-table th, .dp-table td {
    text-align: right;
    padding: 2px 8px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  .dp-table th:first-child, .dp-table td:first-child { text-align: left; }
  .dp-table th {
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    font-size: 9.5px;
    letter-spacing: 0.05em;
  }
  .dp-note { font: 11px var(--font-body); color: var(--muted); margin: 4px; }
</style>
