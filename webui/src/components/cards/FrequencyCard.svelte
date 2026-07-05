<script lang="ts">
  /**
   * Frequency-stage context card (design spec §3; Task R1 per-set
   * redesign).
   *
   * FIRST control is the "Dataset ▾" dropdown (All sets + one entry per
   * set) bound to the shared `analysisTarget` — it follows the tray and
   * drives which set(s) the card configures + Calc runs. The rest of the
   * controls two-way bind to the FOCUSED set's freq settings via the
   * `analysisSettings` store (window, mode, nFrames); when the target is
   * `'all'` and the sets disagree on a key, the control shows a "–mixed–"
   * placeholder and the first edit applies to every set.
   *
   * `[FFT | PSD | CSD]` sub-toggle drives the set's `mode`. The
   * coupled-resolution control (frames + slider via `fromNFrames`) is
   * shown only for PSD/CSD — FFT has no averaging. Calc runs
   * `actions.calcFft(target)` (FFT) or `actions.calcPsd(target)`
   * (PSD/CSD, one op fills both psd + Cxy).
   *
   * CSD note: only the coherence matrix `Cxy` is available from the
   * worker, so CSD displays |Cxy[ch,ch]| and is labelled "CSD
   * (coherence)"; the off-diagonal cross-power pairs are deferred.
   */
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';
  import type { AnalysisSettings } from '../../lib/stores/analysisSettings';
  import type { FreqMode } from '../../lib/plot/model';
  import { fromNFrames, fromNFft, fromFrameLength, type Resolution } from '../../lib/analysis/resolution';

  let {
    actions,
    selection,
    analysisSettings,
  }: { actions: Actions; selection: Selection; analysisSettings: AnalysisSettings } = $props();

  const setsView = $derived(selection.setsView);
  const computeError = $derived(actions.computeError);
  const busy = $derived(actions.busy);

  const target = $derived(analysisSettings.analysisTarget);
  const settingsMap = $derived(analysisSettings.map);   // subscribe → re-derive on patch

  // Focused freq settings for the current target ('void $settingsMap'
  // forces a re-read after every patch, since settingFor reads a snapshot).
  const freq = $derived((void $settingsMap, analysisSettings.settingFor($target, 'freq')));
  const mixed = (key: 'window' | 'mode' | 'nFrames') =>
    (void $settingsMap, $target === 'all' && analysisSettings.isMixed('freq', key));

  const freqMode = $derived(freq.mode as FreqMode);

  // Coupled resolution: seed the frame-length/Δf readout from the target
  // set's duration + fs (first set for 'all').
  const first = $derived($setsView[0]);
  const fs = $derived(actions.workingSets()[0]?.fs ?? 1000);
  const durationS = $derived(first?.durationS ?? 1);
  const res = $derived<Resolution>(fromNFrames(freq.nFrames, durationS, fs));

  const MODES: { id: FreqMode; label: string }[] = [
    { id: 'fft', label: 'FFT' },
    { id: 'psd', label: 'PSD' },
    { id: 'csd', label: 'CSD' },
  ];
  const averaged = $derived(freqMode !== 'fft');
  const calcLabel = $derived(freqMode === 'fft' ? 'Calc FFT' : freqMode === 'psd' ? 'Calc PSD' : 'Calc CSD');

  const patch = (partial: Partial<{ window: string; mode: FreqMode; nFrames: number }>) =>
    analysisSettings.patch($target, 'freq', partial);
  function setFrames(n: number) { patch({ nFrames: fromNFrames(n, durationS, fs).nFrames }); }
  function setFrameLen(s: number) { patch({ nFrames: fromFrameLength(s, durationS, fs).nFrames }); }
  function setNFft(n: number) { patch({ nFrames: fromNFft(n, durationS, fs).nFrames }); }

  function calc() {
    if (freqMode === 'fft') actions.calcFft($target);
    else actions.calcPsd($target);
  }

  function onTarget(v: string) {
    analysisSettings.setTarget(v === 'all' ? 'all' : Number(v));
  }
</script>

<section class="ctx-card card-controls" aria-label="Frequency stage controls">
  <div class="ctx-name"><span class="cn-t">Frequency</span><span class="cn-s">spectra</span></div>
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
        <span class="grp-lab">quantity</span>
        <div class="grp-ctl">
          <span class="seg" role="group" aria-label="spectral quantity" class:mixed={mixed('mode')}>
            {#each MODES as m (m.id)}
              <button class:active={!mixed('mode') && freqMode === m.id} data-spec={m.id}
                onclick={() => patch({ mode: m.id })}>{m.label}</button>
            {/each}
          </span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">window</span>
        <div class="grp-ctl">
          <select value={mixed('window') ? '' : freq.window}
            onchange={(e) => patch({ window: e.currentTarget.value })} aria-label="window">
            {#if mixed('window')}<option value="" disabled>–mixed–</option>{/if}
            <option>hann</option><option>hamming</option><option>flattop</option><option>none</option>
          </select>
        </div>
      </div>
    </div>
    {#if averaged}
      <div class="ctx-row">
        <div class="grp">
          <span class="grp-lab">resolution — {res.nFrames} frames</span>
          <div class="grp-ctl">
            <input type="range" min="1" max="30" value={res.nFrames}
              oninput={(e) => setFrames(+e.currentTarget.value)}
              style="width:104px" aria-label="number of frames" />
            <span class="ml">N</span>
            <input type="number" min="1" max="60" value={mixed('nFrames') ? '' : res.nFrames}
              placeholder={mixed('nFrames') ? '–mixed–' : ''}
              onchange={(e) => setFrames(+e.currentTarget.value)} style="width:52px" aria-label="N frames" />
            <span class="ml">frame&nbsp;s</span>
            <input type="number" step="0.01" value={res.frameLengthS.toFixed(2)}
              onchange={(e) => setFrameLen(+e.currentTarget.value)} style="width:64px" aria-label="frame length seconds" />
            <span class="ml">nFFT</span>
            <input type="number" value={res.nFft}
              onchange={(e) => setNFft(+e.currentTarget.value)} style="width:64px" aria-label="nFFT" />
            <span class="note mono">Δf = {res.dF.toFixed(2)} Hz</span>
          </div>
        </div>
      </div>
    {/if}
    {#if freqMode === 'csd'}
      <span class="note">CSD shows |Cxy| on the diagonal (coherence); cross-power pairs deferred.</span>
    {/if}
    {#if $computeError}
      <div class="ctx-err" role="alert">{$computeError}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button class="btn indigo" disabled={$busy || $setsView.length === 0} onclick={calc}>{calcLabel}</button>
  </div>
</section>

<style>
  .seg.mixed button.active { background: none; color: inherit; }
</style>
