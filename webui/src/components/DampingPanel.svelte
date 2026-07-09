<script lang="ts">
  /**
   * Interactive damping-fit panel (round-7 items 3+4; round-7c layout) — the
   * web rebuild of the Qt `DampingFitWindow`, plus the interactive controls
   * Tore asked for.
   *
   * Two layouts (the `side` prop, chosen by App):
   * - `side` (wide screens): a column DOCKED TO THE RIGHT of the sonogram,
   *   controls on top, the two charts stacked below. Each chart can EXPAND to
   *   fill the whole plot region (click the chart or its ⤢ button — App hides
   *   the sonogram while `damping.expanded` is set) and pop back in.
   * - dock (narrow): the round-7 layout — full-width below the sonogram,
   *   charts side by side. No expansion (the charts already span the width).
   *
   * Two modes (Segmented toggle):
   * - `peaks` — the sonogram/CWT per-mode decay fits. Spectrum chart: the
   *   start-slice magnitude (normalised min→max, the exact scale
   *   `peakutils.indexes` thresholds on) with the DRAGGABLE threshold line
   *   and candidate peaks. Decay chart: Re log(S) per fitted mode — sparse ×
   *   data markers + the fitted line, palette-coloured, with an `f Hz, Qn=…`
   *   legend (the Untitled-23 screenshot's plot).
   * - `bands` — Schroeder band decays: EDC per band + dashed T60 fit lines,
   *   and the metrics table (EDT / T20 / T30 / T60 / Qn; NaN renders as an
   *   em-dash — insufficient decay range, not an error).
   *
   * Every chart is SAVEABLE as its own figure (round-7c): the SVGs follow
   * PlotSurface's self-contained-SVG contract (decision A) — a
   * `data-role="plot-bg"` rect and `data-role="axis"` chrome with inline
   * CHROME hexes (scoped CSS still wins on screen), `tick`-classed tick
   * text — so `figure.ts`'s exportPng restyles them exactly like the main
   * plot. The band table saves as CSV. Delivery goes through the same
   * workdir-or-download path as Save Figure (the `onsavefile` prop).
   *
   * The panel never talks to the engine: control commits update the damping
   * store then call `onrefit`, and the actions layer pushes decoded results
   * back into the store. Start time and threshold accept BLANK = auto (the
   * engine infers / uses its automatic choice, then echoes the resolved
   * value back into the field).
   */
  import type { DampingStore, DampingMode, DampingChart, BandLadder, DampingBandsResult } from '../lib/stores/damping';
  import { LINE_PALETTE } from '../lib/stores/selection';
  import { niceTicks, fmtTick } from '../lib/plot/scales';
  import { CHROME } from '../lib/plot/chrome';
  import { exportPng } from '../lib/export/figure';
  import {
    seriesExtent, padDomain, polylinePoints, pxX, pxY, markerIndices,
    type MiniDomain,
  } from '../lib/plot/miniplot';
  import Segmented from './Segmented.svelte';

  let {
    damping,
    onrefit,
    onclose,
    side = false,
    onsavefile,
    notify,
  }: {
    damping: DampingStore;
    /** Re-run the fit with the store's current knobs (debounced upstream). */
    onrefit: () => void;
    onclose: () => void;
    /** Wide-screen layout: right-hand column with stacked, expandable charts. */
    side?: boolean;
    /** Deliver a saved file (workdir or download — App wires the same path Save Figure uses). */
    onsavefile: (name: string, bytes: Uint8Array) => Promise<void>;
    /** Toast feedback for saves. */
    notify: (message: string, level: 'success' | 'error') => void;
  } = $props();

  // NB not named `state`: a local called `state` shadows the rune name, so
  // svelte-check (via the app tsconfig, as CI runs it) then reads every
  // `$state(...)` in the file as a store subscription of this variable.
  const dmp = $derived($damping);

  // ---- mini-plot geometry ----
  // Margins follow PlotSurface's proportions scaled down; per-chart width AND
  // height are measured from the host (round-7c: heights vary — 170px docked,
  // taller in the side column, full region when expanded).
  const ML = 46, MR = 10, MT = 8, MB = 26;
  let specW = $state(360), specH = $state(170);
  let decayW = $state(360), decayH = $state(170);
  let edcW = $state(360), edcH = $state(170);
  const iw = (w: number) => Math.max(40, w - ML - MR);
  const ih = (h: number) => Math.max(40, h - MT - MB);

  // ---- expand/collapse (side layout only) ----
  const expanded = $derived(side ? dmp.expanded : null);
  function toggleExpand(chart: DampingChart) {
    if (!side) return;
    damping.setExpanded(dmp.expanded === chart ? null : chart);
  }

  // ---- peaks mode: spectrum (normalised) + threshold ----
  /** Slice magnitude normalised min→max — the scale the threshold lives on. */
  const specNorm = $derived.by(() => {
    const p = dmp.peaks;
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
  const shownThr = $derived(dragThr ?? dmp.threshold);
  let specSvg: SVGSVGElement | undefined = $state();
  let decaySvg: SVGSVGElement | undefined = $state();
  let edcSvg: SVGSVGElement | undefined = $state();
  function thrFromEvent(e: PointerEvent): number {
    const r = specSvg!.getBoundingClientRect();
    const frac = 1 - ((e.clientY - r.top) / r.height) * (specH / ih(specH)) + MT / ih(specH);
    return Math.min(1, Math.max(0, frac * 1.06));
  }
  function onThrDown(e: PointerEvent) {
    if (dmp.busy || !specDom) return;
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
  const decayDom = $derived<MiniDomain | null>(dmp.peaks && dmp.peaks.fits.length > 0
    ? {
        x: padDomain(seriesExtent(dmp.peaks.fits.map((f) => f.tFit)), 0.03),
        y: padDomain(seriesExtent(dmp.peaks.fits.flatMap((f) => [f.realData, f.realFit])), 0.08),
      }
    : null);

  // ---- bands mode: EDC chart ----
  const edcDom = $derived<MiniDomain | null>(dmp.bands && dmp.bands.bandData.length > 0
    ? {
        x: padDomain(seriesExtent(dmp.bands.bandData.map((b) => b.edcT)), 0.02),
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

  // ---- per-chart save (round-7c) ----
  const stamp = () => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
  };
  let saving = $state(false);
  async function saveChart(id: DampingChart, svg: SVGSVGElement | undefined) {
    if (!svg || saving) return;
    saving = true;
    try {
      // 'white' background — the same theme-invariant default the main Save
      // Figure opens with; the charts' CHROME-hex chrome restyles identically.
      const blob = await exportPng(svg.outerHTML, 'white');
      const name = `damping-${id}_${stamp()}.png`;
      await onsavefile(name, new Uint8Array(await blob.arrayBuffer()));
      notify(`Saved ${name}`, 'success');
    } catch (e) {
      notify(`Chart save failed: ${e instanceof Error ? e.message : e}`, 'error');
    } finally {
      saving = false;
    }
  }

  /** Band metrics as CSV (NaN → empty cell, matching the table's em-dash). */
  function bandsCsv(b: DampingBandsResult): string {
    const cell = (v: number) => (Number.isFinite(v) ? String(v) : '');
    const rows = ['fc_Hz,f_lo_Hz,f_hi_Hz,EDT_s,T20_s,T30_s,T60_s,Qn'];
    for (let i = 0; i < b.fc.length; i++) {
      rows.push([b.fc[i], b.fLo[i], b.fHi[i], b.EDT[i], b.T20[i], b.T30[i], b.T60[i], b.Qn[i]]
        .map(cell).join(','));
    }
    return rows.join('\n') + '\n';
  }
  async function saveBandsCsv() {
    if (!dmp.bands || saving) return;
    saving = true;
    try {
      const name = `damping-bands_${stamp()}.csv`;
      await onsavefile(name, new TextEncoder().encode(bandsCsv(dmp.bands)));
      notify(`Saved ${name}`, 'success');
    } catch (e) {
      notify(`CSV save failed: ${e instanceof Error ? e.message : e}`, 'error');
    } finally {
      saving = false;
    }
  }
</script>

{#snippet frame(w: number, h: number, dom: MiniDomain, xlab: string, ylab: string)}
  <!-- Chart chrome per the self-contained-SVG contract: plot-bg rect + axis
       elements with inline CHROME hexes (scoped CSS wins on screen; the
       inline values make a serialised save restyle like the main figure). -->
  <rect data-role="plot-bg" class="mini-bg" x="0" y="0" width={w} height={h} fill={CHROME.bg} />
  <rect data-role="axis" x={ML} y={MT} width={iw(w)} height={ih(h)} class="mini-frame"
    fill="none" stroke={CHROME.frame} />
  {#each niceTicks(dom.x[0], dom.x[1], 5) as tv (tv)}
    {#if tv >= dom.x[0] && tv <= dom.x[1]}
      <text data-role="axis" x={ML + pxX(tv, dom, iw(w))} y={h - 10} class="tick mini-tick"
        text-anchor="middle" fill={CHROME.axis}>{fmtTick(tv, dom.x[1] - dom.x[0])}</text>
    {/if}
  {/each}
  {#each niceTicks(dom.y[0], dom.y[1], 4) as tv (tv)}
    {#if tv >= dom.y[0] && tv <= dom.y[1]}
      <text data-role="axis" x={ML - 5} y={MT + pxY(tv, dom, ih(h)) + 3} class="tick mini-tick"
        text-anchor="end" fill={CHROME.axis}>{fmtTick(tv, dom.y[1] - dom.y[0])}</text>
    {/if}
  {/each}
  <text data-role="axis" x={ML + iw(w) / 2} y={h - 0.5} class="mini-lab" text-anchor="middle"
    fill={CHROME.axis}>{xlab}</text>
  <text data-role="axis" x={11} y={MT + ih(h) / 2} class="mini-lab" text-anchor="middle"
    fill={CHROME.axis} transform="rotate(-90 11 {MT + ih(h) / 2})">{ylab}</text>
{/snippet}

{#snippet cardHead(title: string, chart: DampingChart, svg: SVGSVGElement | undefined)}
  <div class="dpc-head">
    <span class="dpc-title">{title}</span>
    <button class="dpc-btn" data-testid="damping-save-{chart}" title="Save this chart as PNG"
      aria-label="Save {title} as PNG" disabled={saving}
      onclick={() => saveChart(chart, svg)}>
      <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M8 2v8M4.8 7l3.2 3.2L11.2 7M2.8 13h10.4" />
      </svg>
    </button>
    {#if side}
      <button class="dpc-btn" data-testid="damping-expand-{chart}"
        title={expanded === chart ? 'Restore layout' : 'Expand to fill the plot area'}
        aria-label={expanded === chart ? 'Restore layout' : 'Expand chart'}
        aria-pressed={expanded === chart}
        onclick={() => toggleExpand(chart)}>
        <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor"
          stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          {#if expanded === chart}
            <path d="M6.5 2v4.5H2M9.5 14V9.5H14M9.5 2v4.5H14M6.5 14V9.5H2" />
          {:else}
            <path d="M9.5 2H14v4.5M6.5 14H2V9.5M14 2 9.6 6.4M2 14l4.4-4.4" />
          {/if}
        </svg>
      </button>
    {/if}
  </div>
{/snippet}

<div class="damp-panel" class:side data-testid="damping-panel">
  <div class="dp-bar">
    <Segmented
      testid="damping-mode-toggle"
      ariaLabel="Damping method"
      label="method"
      value={dmp.mode}
      onchange={(m: DampingMode) => { damping.setMode(m); onrefit(); }}
      options={[
        { value: 'peaks' as const, label: 'peaks', title: 'Find spectral peaks at the start time, fit each band’s decay (freq from phase)' },
        { value: 'bands' as const, label: 'bands', title: 'Band-pass filter bank + Schroeder decay integral (EDT / T20 / T30 / RT60 / Q)' },
      ]}
    />
    <label class="dp-field">
      <span>start (s)</span>
      <input data-testid="damping-start-input" inputmode="decimal" placeholder="auto"
        value={dmp.startTime === null ? '' : String(dmp.startTime)}
        onchange={commitStart} disabled={dmp.busy} />
    </label>
    {#if dmp.mode === 'peaks'}
      <label class="dp-field">
        <span>threshold</span>
        <input data-testid="damping-threshold-input" inputmode="decimal" placeholder="auto"
          value={shownThr === null ? '' : fmtThr(shownThr)}
          onchange={commitThreshold} disabled={dmp.busy} />
      </label>
    {:else}
      <label class="dp-field">
        <span>bands</span>
        <select data-testid="damping-ladder-select" value={dmp.ladder} disabled={dmp.busy}
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
      disabled={dmp.busy} title="Re-run the fit (picks up the card's STFT|CWT method)">Refit</button>
    {#if dmp.busy}<span class="dp-busy" role="status">fitting…</span>{/if}
    {#if dmp.error}<span class="dp-err" role="alert">{dmp.error}</span>{/if}
    <button class="dp-close" data-testid="damping-close" title="Close damping panel"
      aria-label="Close damping panel" onclick={onclose}>×</button>
  </div>

  {#if dmp.mode === 'peaks'}
    <div class="dp-charts">
      <div class="dp-card" class:expanded={expanded === 'spectrum'}
        class:tucked={expanded !== null && expanded !== 'spectrum'}>
        {@render cardHead('Start-slice spectrum', 'spectrum', specSvg)}
        <div class="dp-chart" bind:clientWidth={specW} bind:clientHeight={specH}>
          {#if specNorm && specDom}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <svg xmlns="http://www.w3.org/2000/svg" bind:this={specSvg} data-testid="damping-spectrum" viewBox="0 0 {specW} {specH}"
              role="img" aria-label="Start-slice spectrum with peak threshold"
              onclick={() => toggleExpand('spectrum')}>
              {@render frame(specW, specH, specDom, 'Frequency (Hz)', 'norm |S|')}
              <g>
                <polyline class="dp-spec-line" fill="none" stroke="#4f46e5" stroke-width="1.3"
                  points={polylinePoints(specNorm.freq, specNorm.norm, specDom, iw(specW), ih(specH))}
                  transform="translate({ML},{MT})" />
                {#each Array.from(dmp.peaks!.peaksFreq) as pf, i (i)}
                  <circle
                    cx={ML + pxX(pf, specDom, iw(specW))}
                    cy={MT + pxY((dmp.peaks!.peaksMag[i] - specNorm.lo) / specNorm.span, specDom, ih(specH))}
                    r="3.4" class="dp-peak" fill="none" stroke="#dc2626" stroke-width="1.4" />
                {/each}
                {#if shownThr !== null}
                  <!-- the draggable threshold line: fat invisible hit band -->
                  <line x1={ML} x2={ML + iw(specW)}
                    y1={MT + pxY(shownThr, specDom, ih(specH))} y2={MT + pxY(shownThr, specDom, ih(specH))}
                    class="dp-thr" stroke="#dc2626" stroke-width="1.2" stroke-dasharray="5 3"
                    data-testid="damping-threshold-line" />
                  <rect x={ML} width={iw(specW)}
                    y={MT + pxY(shownThr, specDom, ih(specH)) - 7} height="14"
                    class="dp-thr-hit" fill="transparent" style="cursor: ns-resize"
                    role="slider" aria-label="Peak threshold" aria-orientation="vertical"
                    aria-valuemin="0" aria-valuemax="1" aria-valuenow={shownThr} tabindex="0"
                    onclick={(e) => e.stopPropagation()}
                    onpointerdown={onThrDown} onpointermove={onThrMove}
                    onpointerup={onThrUp} onpointercancel={() => (dragThr = null)} />
                {/if}
              </g>
            </svg>
          {:else}
            <p class="dp-note">No spectrum context — run Fit damping (a stale engine build hides the picker; reload if this persists).</p>
          {/if}
        </div>
      </div>
      <div class="dp-card" class:expanded={expanded === 'decay'}
        class:tucked={expanded !== null && expanded !== 'decay'}>
        {@render cardHead('Decay fits — Re log(S)', 'decay', decaySvg)}
        <div class="dp-chart" bind:clientWidth={decayW} bind:clientHeight={decayH}>
          {#if dmp.peaks && decayDom}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <svg xmlns="http://www.w3.org/2000/svg" bind:this={decaySvg} data-testid="damping-decay" viewBox="0 0 {decayW} {decayH}"
              role="img" aria-label="Per-mode decay fits"
              onclick={() => toggleExpand('decay')}>
              {@render frame(decayW, decayH, decayDom, 'Time (s)', 'Re log(S)')}
              {#each dmp.peaks.fits as f, i (i)}
                <g transform="translate({ML},{MT})">
                  {#each markerIndices(f.tFit.length) as k (k)}
                    <path class="dp-x" fill="none" stroke={colour(i)} stroke-width="1.1" opacity="0.75"
                      d="M-2.6,-2.6 L2.6,2.6 M-2.6,2.6 L2.6,-2.6"
                      transform="translate({pxX(f.tFit[k], decayDom, iw(decayW))},{pxY(f.realData[k], decayDom, ih(decayH))})" />
                  {/each}
                  <polyline class="dp-fit" fill="none" stroke={colour(i)} stroke-width="2.4"
                    points={polylinePoints(f.tFit, f.realFit, decayDom, iw(decayW), ih(decayH))} />
                </g>
              {/each}
            </svg>
          {:else if dmp.peaks}
            <!-- A completed fit with ZERO modes is a normal outcome (threshold
                 too high / start line past the decay), not an error state. -->
            <div class="dp-legend" data-testid="damping-fit-legend">
              <span class="dp-note">No modes fitted — lower the threshold or move the start line.</span>
            </div>
          {:else}
            <p class="dp-note">No fits yet.</p>
          {/if}
        </div>
        {#if dmp.peaks && decayDom}
          <div class="dp-legend" data-testid="damping-fit-legend">
            {#each dmp.peaks.fits as f, i (i)}
              <span class="dp-chip"><i style="background:{colour(i)}"></i>{fmt1(f.fPeak)} Hz, Qn={f.Qn.toFixed(0)}</span>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  {:else}
    <div class="dp-charts">
      <div class="dp-card" class:expanded={expanded === 'edc'}
        class:tucked={expanded !== null && expanded !== 'edc'}>
        {@render cardHead('Schroeder decay — EDC', 'edc', edcSvg)}
        <div class="dp-chart" bind:clientWidth={edcW} bind:clientHeight={edcH}>
          {#if dmp.bands && edcDom}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
            <svg xmlns="http://www.w3.org/2000/svg" bind:this={edcSvg} data-testid="damping-edc" viewBox="0 0 {edcW} {edcH}" role="img"
              aria-label="Band energy-decay curves"
              onclick={() => toggleExpand('edc')}>
              {@render frame(edcW, edcH, edcDom, 'Time (s)', 'EDC (dB)')}
              {#each dmp.bands.bandData as b, i (i)}
                <g transform="translate({ML},{MT})">
                  <polyline class="dp-edc" fill="none" stroke={colour(i)} stroke-width="1.4" opacity="0.9"
                    points={polylinePoints(b.edcT, b.edcDb, edcDom, iw(edcW), ih(edcH))} />
                  {#if b.fitT && b.fitDb}
                    <polyline class="dp-edc-fit" fill="none" stroke={colour(i)} stroke-width="2" stroke-dasharray="6 3"
                      points={polylinePoints(b.fitT, b.fitDb, edcDom, iw(edcW), ih(edcH))} />
                  {/if}
                </g>
              {/each}
            </svg>
          {:else}
            <p class="dp-note">No band decays yet.</p>
          {/if}
        </div>
      </div>
      <div class="dp-card dp-table-card" class:tucked={expanded !== null}>
        <div class="dpc-head">
          <span class="dpc-title">Band metrics</span>
          <button class="dpc-btn" data-testid="damping-save-bands-csv" title="Save the band metrics as CSV"
            aria-label="Save band metrics as CSV" disabled={saving || !dmp.bands}
            onclick={saveBandsCsv}>
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor"
              stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M8 2v8M4.8 7l3.2 3.2L11.2 7M2.8 13h10.4" />
            </svg>
          </button>
        </div>
        <div class="dp-table-host">
          {#if dmp.bands}
            <table class="dp-table" data-testid="damping-band-table">
              <thead>
                <tr><th>fc (Hz)</th><th>EDT (s)</th><th>T20 (s)</th><th>T30 (s)</th><th>T60 (s)</th><th>Qn</th></tr>
              </thead>
              <tbody>
                {#each Array.from(dmp.bands.fc) as fc, i (i)}
                  <tr>
                    <td><i class="dp-dot" style="background:{colour(i)}"></i>{fmt1(fc)}</td>
                    <td>{fmt2(dmp.bands.EDT[i])}</td>
                    <td>{fmt2(dmp.bands.T20[i])}</td>
                    <td>{fmt2(dmp.bands.T30[i])}</td>
                    <td>{fmt2(dmp.bands.T60[i])}</td>
                    <td>{fmt1(dmp.bands.Qn[i])}</td>
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
    </div>
  {/if}
</div>

<style>
  /* ---- dock layout (narrow; the round-7 original): full-width strip below
     the sonogram, charts side by side ---- */
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
  .dp-charts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    min-height: 0;
  }
  /* ---- side layout (wide; round-7c): right-hand column beside the
     sonogram, controls on top, charts STACKED. An expanded card fills the
     whole region (App hides the sonogram and lets this column flex out). ---- */
  .damp-panel.side {
    border-top: none;
    border-left: 1px solid var(--border);
    max-height: none;
    height: 100%;
    overflow: hidden;
  }
  .damp-panel.side .dp-charts {
    grid-template-columns: 1fr;
    grid-auto-rows: minmax(0, 1fr);
    flex: 1;
    min-height: 0;
  }
  .dp-card {
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }
  .dp-card.tucked { display: none; }
  .dpc-head {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .dpc-title {
    font: 600 10.5px var(--font-body, system-ui, sans-serif);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-right: auto;
  }
  .dpc-btn {
    border: 1px solid transparent;
    background: transparent;
    color: var(--muted);
    border-radius: 4px;
    width: 20px;
    height: 20px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }
  .dpc-btn:hover:not(:disabled) { background: var(--hover-bg); color: var(--text); }
  .dpc-btn:disabled { opacity: 0.4; cursor: default; }
  .dp-chart {
    position: relative;
    min-width: 0;
    height: 170px;
  }
  .damp-panel.side .dp-chart { height: auto; flex: 1; min-height: 120px; }
  .dp-chart svg { display: block; width: 100%; height: 100%; }
  .damp-panel.side .dp-card .dp-chart svg { cursor: zoom-in; }
  .damp-panel.side .dp-card.expanded .dp-chart svg { cursor: zoom-out; }

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

  /* Chart chrome: scoped CSS beats the inline export hexes on screen, so the
     charts stay theme-aware while a serialised save is self-contained. */
  .mini-bg { fill: var(--surface); }
  .mini-frame { stroke: var(--border); }
  .mini-tick {
    /* PlotSurface's tick metrics (round-7c consistency): mono 10.5px. */
    font: 10.5px var(--font-mono, ui-monospace, monospace);
    fill: var(--muted);
  }
  .mini-lab {
    font: 11.5px var(--font-body, system-ui, sans-serif);
    fill: var(--muted);
  }
  .dp-spec-line { stroke: var(--indigo, #4f46e5); }
  .dp-peak { stroke: var(--danger, #dc2626); }
  .dp-thr { stroke: var(--danger, #dc2626); }

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
  .dp-table-host { overflow: auto; min-height: 0; }
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
