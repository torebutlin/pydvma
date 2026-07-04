<script lang="ts">
  /**
   * Frequency-stage context card (design spec §3; visuals ported from
   * the `data-card="frequency"` block of round2-bench.html).
   *
   * `[FFT | PSD | CSD]` sub-toggle drives `freqMode` (bound up to the
   * app so the plot model transforms accordingly). Window select feeds
   * the worker. The coupled-resolution control (three linked inputs +
   * slider via `fromNFrames`/`fromFrameLength`/`fromNFft`) is shown only
   * for PSD/CSD — FFT has no averaging. Calc runs `actions.calcFft`
   * (FFT) or `actions.calcPsd` (PSD/CSD, one op fills both psd + Cxy).
   *
   * CSD note: only the coherence matrix `Cxy` is available from the
   * worker, so CSD displays |Cxy[ch,ch]| and is labelled "CSD
   * (coherence)"; the off-diagonal cross-power pairs are deferred.
   */
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';
  import type { FreqMode } from '../../lib/plot/model';
  import { fromNFrames, fromNFft, fromFrameLength, type Resolution } from '../../lib/analysis/resolution';

  let {
    actions,
    selection,
    freqMode = $bindable('fft'),
  }: { actions: Actions; selection: Selection; freqMode?: FreqMode } = $props();

  const setsView = $derived(selection.setsView);
  const computeError = $derived(actions.computeError);
  const busy = $derived(actions.busy);

  let window = $state('hann');

  // Coupled resolution: seed from the first loaded set's duration + fs.
  const first = $derived($setsView[0]);
  const fs = $derived(actions.workingSets()[0]?.fs ?? 1000);
  const durationS = $derived(first?.durationS ?? 1);
  // nFrames is the source of truth; `res` derives from it + duration/fs, so
  // it self-recomputes when the source set changes (no read/write effect loop).
  let nFrames = $state(10);
  const res = $derived<Resolution>(fromNFrames(nFrames, durationS, fs));

  const MODES: { id: FreqMode; label: string }[] = [
    { id: 'fft', label: 'FFT' },
    { id: 'psd', label: 'PSD' },
    { id: 'csd', label: 'CSD' },
  ];
  const averaged = $derived(freqMode !== 'fft');
  const calcLabel = $derived(freqMode === 'fft' ? 'Calc FFT' : freqMode === 'psd' ? 'Calc PSD' : 'Calc CSD');

  function setFrames(n: number) { nFrames = fromNFrames(n, durationS, fs).nFrames; }
  function setFrameLen(s: number) { nFrames = fromFrameLength(s, durationS, fs).nFrames; }
  function setNFft(n: number) { nFrames = fromNFft(n, durationS, fs).nFrames; }

  function calc() {
    const win = window === 'none' ? null : window;
    if (freqMode === 'fft') actions.calcFft(win);
    else actions.calcPsd(win, res.nFrames);
  }
</script>

<section class="ctx-card card-controls" aria-label="Frequency stage controls">
  <div class="ctx-name"><span class="cn-t">Frequency</span><span class="cn-s">spectra</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">quantity</span>
        <div class="grp-ctl">
          <span class="seg" role="group" aria-label="spectral quantity">
            {#each MODES as m (m.id)}
              <button class:active={freqMode === m.id} data-spec={m.id}
                onclick={() => (freqMode = m.id)}>{m.label}</button>
            {/each}
          </span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">window</span>
        <div class="grp-ctl">
          <select bind:value={window} aria-label="window">
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
            <input type="number" min="1" max="60" value={res.nFrames}
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
