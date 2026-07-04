<script lang="ts">
  /**
   * TF-stage context card (design spec §3; visuals ported from the
   * `data-card="tf"` block of round2-bench.html).
   *
   * Controls: window + averaging (none / within each set / across
   * sets), an N-frames slider (1–30) with a live frame-length readout,
   * a coherence toggle, and the plot-type select (Mag dB / Phase / Bode
   * / Real / Imag / Nyquist). Plot type drives the plot MODEL through
   * `viewState.setPlotType`; coherence through `viewState.setCoherence`.
   * Nyquist reveals fmin/fmax fields bound to the shared freq range.
   *
   * Calc TF runs `actions.calcTf(chIn, window, averaging, nFrames)`.
   * The N-frames slider re-issues live but is DEBOUNCED (150 ms) and
   * the action carries its own stale-guard, so dragging never floods
   * the worker or lets an old response clobber a newer one.
   */
  import type { ViewState, TfPlotType } from '../../lib/stores/viewstate';
  import type { Selection } from '../../lib/stores/selection';
  import type { Actions } from '../../lib/analysis/actions';
  import { fromNFrames } from '../../lib/analysis/resolution';

  let {
    viewState,
    selection,
    actions,
  }: { viewState: ViewState; selection: Selection; actions: Actions } = $props();

  const setsView = $derived(selection.setsView);
  const current = $derived(viewState.current);
  const sharedFreq = $derived(viewState.sharedFreqRange);
  const computeError = $derived(actions.computeError);
  const busy = $derived(actions.busy);

  let window = $state('hann');
  let averaging = $state<'none' | 'within' | 'across'>('within');
  let chIn = $state(0);
  let nFrames = $state(10);

  const maxChannels = $derived($setsView.reduce((m, s) => Math.max(m, s.nChannels), 0));
  const fs = $derived(actions.workingSets()[0]?.fs ?? 1000);
  const durationS = $derived($setsView[0]?.durationS ?? 1);
  const frameLengthS = $derived(fromNFrames(nFrames, durationS, fs).frameLengthS);

  const plotType = $derived($current.plotType);
  const coherence = $derived($current.coherence);

  const PLOT_TYPES: { id: TfPlotType; label: string }[] = [
    { id: 'mag', label: 'Mag (dB)' }, { id: 'phase', label: 'Phase' },
    { id: 'bode', label: 'Bode' }, { id: 'real', label: 'Real' },
    { id: 'imag', label: 'Imag' }, { id: 'nyquist', label: 'Nyquist' },
  ];

  function setPlotType(t: TfPlotType) { viewState.setPlotType(t); }

  function calc() {
    actions.calcTf(chIn, window === 'none' ? null : window, averaging, nFrames);
  }

  // Live N-frames: debounce the worker re-issue while dragging the slider.
  let debounceId: ReturnType<typeof setTimeout> | undefined;
  function onFrames(n: number) {
    nFrames = n;
    clearTimeout(debounceId);
    debounceId = setTimeout(calc, 150);
  }

  // Nyquist fmin/fmax are bound to the shared freq range (tf view range).
  const nyqMin = $derived($sharedFreq?.[0] ?? 0);
  const nyqMax = $derived($sharedFreq?.[1] ?? 0);
  function setNyqRange(lo: number, hi: number) {
    if (Number.isFinite(lo) && Number.isFinite(hi) && hi > lo) {
      viewState.setRange('tf', { x: [lo, hi], y: $current.range.y });
    }
  }
</script>

<section class="ctx-card card-controls" aria-label="TF stage controls">
  <div class="ctx-name"><span class="cn-t">TF</span><span class="cn-s">estimate</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">estimator</span>
        <div class="grp-ctl">
          <span class="ml">in</span>
          <select bind:value={chIn} style="width:64px" aria-label="input channel">
            {#each Array.from({ length: Math.max(1, maxChannels) }, (_, c) => c) as c (c)}
              <option value={c}>ch_{c}</option>
            {/each}
          </select>
          <span class="ml">window</span>
          <select bind:value={window} aria-label="window">
            <option>hann</option><option>hamming</option><option>none</option>
          </select>
          <span class="ml">avg</span>
          <select bind:value={averaging} aria-label="averaging">
            <option value="none">none</option>
            <option value="within">within set</option>
            <option value="across">across sets</option>
          </select>
        </div>
      </div>
      <div class="grp" class:dim={averaging === 'none' || averaging === 'across'}>
        <span class="grp-lab">frames — live</span>
        <div class="grp-ctl">
          <input type="range" min="1" max="30" value={nFrames}
            disabled={averaging !== 'within'}
            oninput={(e) => onFrames(+e.currentTarget.value)} style="width:104px" aria-label="N frames" />
          <span class="mono" style="font-size:11.5px">N = {nFrames} · Frame length = {frameLengthS.toFixed(2)} s</span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">coherence</span>
        <div class="grp-ctl">
          <label class="switch"><input type="checkbox" checked={coherence}
            onchange={(e) => viewState.setCoherence(e.currentTarget.checked)} aria-label="coherence overlay" /></label>
        </div>
      </div>
    </div>
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">plot type</span>
        <div class="grp-ctl">
          <select value={plotType} onchange={(e) => setPlotType(e.currentTarget.value as TfPlotType)}
            aria-label="plot type">
            {#each PLOT_TYPES as p (p.id)}
              <option value={p.id}>{p.label}</option>
            {/each}
          </select>
          {#if plotType === 'nyquist'}
            <span class="ml">fmin</span>
            <input type="number" value={nyqMin} style="width:56px" aria-label="fmin"
              onchange={(e) => setNyqRange(+e.currentTarget.value, nyqMax)} />
            <span class="ml">fmax</span>
            <input type="number" value={nyqMax} style="width:56px" aria-label="fmax"
              onchange={(e) => setNyqRange(nyqMin, +e.currentTarget.value)} />
            <span class="note">range linked to TF zoom</span>
          {/if}
        </div>
      </div>
    </div>
    {#if $computeError}
      <div class="ctx-err" role="alert">{$computeError}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button class="btn indigo" disabled={$busy || $setsView.length === 0} onclick={calc}>Calc TF</button>
  </div>
</section>

<style>
  .grp.dim .grp-ctl > *:not(.switch) {
    opacity: 0.55;
  }
</style>
