<script lang="ts">
  /**
   * TF-stage context card (design spec §3; Task R1 per-set redesign).
   *
   * FIRST control is the "Dataset ▾" dropdown bound to the shared
   * `analysisTarget` (follows the tray). The estimator controls (input
   * channel, window, averaging mode, N-frames) two-way bind to the
   * FOCUSED set's TF settings via the `analysisSettings` store; a
   * "–mixed–" placeholder shows when the target is `'all'` and sets
   * disagree, and the first edit applies to every set.
   *
   * Plot type (Mag dB / Phase / Bode / Real / Imag / Nyquist) and the
   * coherence toggle are per-VIEW, not per-set — they stay on
   * `viewState`. Nyquist reveals fmin/fmax fields bound to the shared
   * freq range.
   *
   * Calc TF runs `actions.calcTf(target)`. The N-frames slider re-issues
   * live but is DEBOUNCED (150 ms) and the action carries a per-kind
   * stale seq (key 'tf'), so dragging never floods the worker or lets an
   * old TF response clobber a newer one.
   */
  import type { ViewState, TfPlotType } from '../../lib/stores/viewstate';
  import type { Selection } from '../../lib/stores/selection';
  import type { Actions } from '../../lib/analysis/actions';
  import type { AnalysisSettings } from '../../lib/stores/analysisSettings';
  import { fromNFrames } from '../../lib/analysis/resolution';

  let {
    viewState,
    selection,
    actions,
    analysisSettings,
  }: { viewState: ViewState; selection: Selection; actions: Actions; analysisSettings: AnalysisSettings } = $props();

  const setsView = $derived(selection.setsView);
  const current = $derived(viewState.current);
  const sharedFreq = $derived(viewState.sharedFreqRange);
  const computeError = $derived(actions.computeError);
  const busy = $derived(actions.busy);

  const target = $derived(analysisSettings.analysisTarget);
  const settingsMap = $derived(analysisSettings.map);
  const tf = $derived((void $settingsMap, analysisSettings.settingFor($target, 'tf')));
  const mixed = (key: 'chIn' | 'window' | 'averaging' | 'nFrames') =>
    (void $settingsMap, $target === 'all' && analysisSettings.isMixed('tf', key));

  const maxChannels = $derived($setsView.reduce((m, s) => Math.max(m, s.nChannels), 0));
  const fs = $derived(actions.workingSets()[0]?.fs ?? 1000);
  const durationS = $derived($setsView[0]?.durationS ?? 1);
  const frameLengthS = $derived(fromNFrames(tf.nFrames, durationS, fs).frameLengthS);

  const plotType = $derived($current.plotType);
  const coherence = $derived($current.coherence);

  const PLOT_TYPES: { id: TfPlotType; label: string }[] = [
    { id: 'mag', label: 'Mag (dB)' }, { id: 'phase', label: 'Phase' },
    { id: 'bode', label: 'Bode' }, { id: 'real', label: 'Real' },
    { id: 'imag', label: 'Imag' }, { id: 'nyquist', label: 'Nyquist' },
  ];

  const patch = (partial: Partial<{ chIn: number; window: string; averaging: 'none' | 'within' | 'across'; nFrames: number }>) =>
    analysisSettings.patch($target, 'tf', partial);

  function setPlotType(t: TfPlotType) { viewState.setPlotType(t); }

  function calc() { actions.calcTf($target); }

  function onTarget(v: string) {
    analysisSettings.setTarget(v === 'all' ? 'all' : Number(v));
  }

  // Live N-frames: write to the store, then debounce the worker re-issue.
  let debounceId: ReturnType<typeof setTimeout> | undefined;
  function onFrames(n: number) {
    patch({ nFrames: n });
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
        <span class="grp-lab">dataset</span>
        <div class="grp-ctl">
          <select value={$target === 'all' ? 'all' : String($target)}
            onchange={(e) => onTarget(e.currentTarget.value)}
            style="width:120px" aria-label="dataset">
            <option value="all">All sets</option>
            {#each $setsView as s (s.id)}
              <option value={String(s.id)}>{s.name}</option>
            {/each}
          </select>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">estimator</span>
        <div class="grp-ctl">
          <span class="ml">in</span>
          <select value={mixed('chIn') ? '' : String(tf.chIn)}
            onchange={(e) => patch({ chIn: Number(e.currentTarget.value) })}
            style="width:64px" aria-label="input channel">
            {#if mixed('chIn')}<option value="" disabled>–mixed–</option>{/if}
            {#each Array.from({ length: Math.max(1, maxChannels) }, (_, c) => c) as c (c)}
              <option value={String(c)}>ch_{c}</option>
            {/each}
          </select>
          <span class="ml">window</span>
          <select value={mixed('window') ? '' : tf.window}
            onchange={(e) => patch({ window: e.currentTarget.value })} aria-label="window">
            {#if mixed('window')}<option value="" disabled>–mixed–</option>{/if}
            <option>hann</option><option>hamming</option><option>none</option>
          </select>
          <span class="ml">avg</span>
          <select value={mixed('averaging') ? '' : tf.averaging}
            onchange={(e) => patch({ averaging: e.currentTarget.value as 'none' | 'within' | 'across' })}
            aria-label="averaging">
            {#if mixed('averaging')}<option value="" disabled>–mixed–</option>{/if}
            <option value="none">none</option>
            <option value="within">within set</option>
            <option value="across">across sets</option>
          </select>
        </div>
      </div>
      <div class="grp" class:dim={tf.averaging === 'none' || tf.averaging === 'across'}>
        <span class="grp-lab">frames — live</span>
        <div class="grp-ctl">
          <input type="range" min="1" max="30" value={tf.nFrames}
            disabled={tf.averaging !== 'within'}
            oninput={(e) => onFrames(+e.currentTarget.value)} style="width:104px" aria-label="N frames" />
          <span class="mono" style="font-size:11.5px">N = {mixed('nFrames') ? '–mixed–' : tf.nFrames} · Frame length = {frameLengthS.toFixed(2)} s</span>
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
