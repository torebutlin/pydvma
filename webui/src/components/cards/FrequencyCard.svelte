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
  import { createLiveCalc } from '../../lib/analysis/liveCalc';
  import { distributeByDf } from '../../lib/analysis/resolutionControl';
  import ResolutionControl from '../ResolutionControl.svelte';

  let {
    actions,
    selection,
    analysisSettings,
  }: { actions: Actions; selection: Selection; analysisSettings: AnalysisSettings } = $props();

  const setsView = $derived(selection.setsView);
  const computeErrors = $derived(actions.computeErrors);
  const busy = $derived(actions.busy);

  const target = $derived(analysisSettings.analysisTarget);
  const settingsMap = $derived(analysisSettings.map);   // subscribe → re-derive on patch

  // Focused freq settings for the current target ('void $settingsMap'
  // forces a re-read after every patch, since settingFor reads a snapshot).
  const freq = $derived((void $settingsMap, analysisSettings.settingFor($target, 'freq')));
  const mixed = (key: 'window' | 'mode' | 'nFrames') =>
    (void $settingsMap, $target === 'all' && analysisSettings.isMixed('freq', key));

  const freqMode = $derived(freq.mode as FreqMode);
  // This card owns the FFT error in FFT mode and the PSD error otherwise
  // (PSD + CSD both compute via calcPsd). Per-kind so a TF/sono failure
  // never shows here (Round-3 item 2).
  const errKind = $derived(freqMode === 'fft' ? 'fft' : 'psd');

  // Coupled resolution seeds off the TARGET set's fs + duration (R1-minor
  // fix): for a specific set target, use THAT set's metadata; for 'all',
  // use the first (representative) set. `fs` only lives on the working
  // sets (not on setsView), so look both up by the resolved setId.
  const repId = $derived($target === 'all' ? $setsView[0]?.id : $target);
  const ws = $derived(actions.workingSets());
  const fs = $derived(ws.find((w) => w.setId === repId)?.fs ?? 1000);
  const durationS = $derived(
    $setsView.find((s) => s.id === repId)?.durationS
      ?? ws.find((w) => w.setId === repId)?.durationS
      ?? 1,
  );

  const MODES: { id: FreqMode; label: string }[] = [
    { id: 'fft', label: 'FFT' },
    { id: 'psd', label: 'PSD' },
    { id: 'csd', label: 'CSD' },
  ];
  const averaged = $derived(freqMode !== 'fft');
  const calcLabel = $derived(freqMode === 'fft' ? 'Calc FFT' : freqMode === 'psd' ? 'Calc PSD' : 'Calc CSD');

  const patch = (partial: Partial<{ window: string; mode: FreqMode; nFrames: number }>) =>
    analysisSettings.patch($target, 'freq', partial);

  function calc() {
    if (freqMode === 'fft') actions.calcFft($target);
    else actions.calcPsd($target);
  }

  // Live recompute (round-2 feedback): once a spectrum has been computed
  // for this target, changing the quantity / window / resolution re-runs
  // it (debounced). Gated on an existing result so a tweak before the
  // first Calc never boots the engine — the Calc button forces that first
  // compute. `patchLive` = patch the setting THEN schedule the recompute.
  const live = createLiveCalc(
    () => actions.hasComputed($target, 'freq') || actions.hasComputed($target, 'psd'),
    calc,
  );
  const patchLive = (partial: Partial<{ window: string; mode: FreqMode; nFrames: number }>) => {
    patch(partial);
    live.schedule();
  };

  /**
   * Apply a resolution edit. A single-set target stores its own nFrames.
   * For 'all', the edit is a Δf INTENT distributed per-set in each set's own
   * fs/duration terms (mixed-fs correctness, Round-3 item 1) — equal-duration
   * sets receive the same nFrames, so this matches the old uniform behaviour
   * there.
   */
  function onResolution(n: number) {
    if ($target !== 'all') { patchLive({ nFrames: n }); return; }
    for (const { setId, nFrames } of distributeByDf(n, durationS, fs, actions.workingSets())) {
      analysisSettings.patch(setId, 'freq', { nFrames });
    }
    live.schedule();
  }
  // Drop a pending live recompute if the card unmounts (stage switch).
  $effect(() => () => live.cancel());

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
                onclick={() => patchLive({ mode: m.id })}>{m.label}</button>
            {/each}
          </span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">window</span>
        <div class="grp-ctl">
          <select value={mixed('window') ? '' : freq.window}
            onchange={(e) => patchLive({ window: e.currentTarget.value })} aria-label="window">
            {#if mixed('window')}<option value="" disabled>–mixed–</option>{/if}
            <option>hann</option><option>hamming</option><option>flattop</option><option>none</option>
          </select>
        </div>
      </div>
    </div>
    {#if averaged}
      <div class="ctx-row">
        <div class="grp">
          <span class="grp-lab">averaging</span>
          <div class="grp-ctl">
            <ResolutionControl {fs} {durationS} nFrames={freq.nFrames}
              mixed={mixed('nFrames')}
              onchange={onResolution} />
          </div>
        </div>
      </div>
    {/if}
    {#if freqMode === 'csd'}
      <span class="note">CSD shows |Cxy| on the diagonal (coherence); cross-power pairs deferred.</span>
    {/if}
    {#if $computeErrors[errKind]}
      <div class="ctx-err" role="alert">{$computeErrors[errKind]}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button class="btn indigo" disabled={$busy || $setsView.length === 0} onclick={calc}>{calcLabel}</button>
  </div>
</section>

<style>
  .seg.mixed button.active { background: none; color: inherit; }
</style>
