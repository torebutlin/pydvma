<script lang="ts">
  /**
   * Sonogram-stage context card (design spec §3; Task R1 per-set
   * redesign).
   *
   * FIRST control is the "Dataset ▾" dropdown bound to the shared
   * `analysisTarget` (follows the tray). It replaces the old free-standing
   * "source set" select — the sonogram now runs the TARGET set. A channel
   * select chooses which channel of that set to transform (the channel is
   * a transient card control, not a per-set stored setting). The STFT
   * window size (`nFft = 2^slider`) and heat-map dynamic range two-way
   * bind to the FOCUSED set's sono settings via the `analysisSettings`
   * store, with "–mixed–" shown when the target is `'all'` and sets
   * disagree.
   *
   * Calc Sonogram runs `actions.calcSono(target, ch)`. Once a sonogram
   * exists, the STFT-window slider / nFFT box and the channel select
   * re-issue live but DEBOUNCED (150 ms) and gated on an existing result
   * (`createLiveCalc`), so a tweak before the first Calc never boots the
   * engine; the action carries a per-kind stale seq (key 'sono').
   */
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';
  import type { AnalysisSettings } from '../../lib/stores/analysisSettings';
  import { createLiveCalc } from '../../lib/analysis/liveCalc';

  let {
    actions,
    selection,
    analysisSettings,
  }: { actions: Actions; selection: Selection; analysisSettings: AnalysisSettings } = $props();

  const setsView = $derived(selection.setsView);
  const computeErrors = $derived(actions.computeErrors);
  const busy = $derived(actions.busy);

  const target = $derived(analysisSettings.analysisTarget);
  const settingsMap = $derived(analysisSettings.map);
  const sono = $derived((void $settingsMap, analysisSettings.settingFor($target, 'sono')));
  const mixed = (key: 'nFft' | 'dynRangeDb') =>
    (void $settingsMap, $target === 'all' && analysisSettings.isMixed('sono', key));

  let ch = $state(0);

  // nFft ↔ slider exponent (nFft = 2^resExp). Mixed → the readout shows –mixed–.
  const nFft = $derived(sono.nFft);
  const resExp = $derived(Math.round(Math.log2(nFft)));

  // Channel options come from the target set (first set for 'all').
  const targetView = $derived(
    $target === 'all' ? $setsView[0] : $setsView.find((s) => s.id === $target),
  );
  const chOptions = $derived(targetView?.nChannels ?? 1);

  const patch = (partial: Partial<{ nFft: number; dynRangeDb: number }>) =>
    analysisSettings.patch($target, 'sono', partial);

  function calc() {
    if ($setsView.length) actions.calcSono($target, ch);
  }

  // Slider exponent range (2^6 = 64 .. 2^12 = 4096 pt STFT windows).
  const RES_MIN_EXP = 6;
  const RES_MAX_EXP = 12;

  // Live recompute (round-2 feedback), gated on an existing sonogram so a
  // slider/channel tweak before the first Calc never boots the engine.
  const live = createLiveCalc(() => actions.hasComputed($target, 'sono'), calc);
  function onRes(v: number) {
    patch({ nFft: 1 << v });
    live.schedule();
  }
  // Drop a pending live recompute if the card unmounts (stage switch).
  $effect(() => () => live.cancel());

  /**
   * Text-box entry for nFFT: snap an arbitrary point count to the nearest
   * power of two (the STFT window must be 2^k), then reuse `onRes`. The
   * TEXT BOX accepts values OUTSIDE the slider's exponent range; the
   * SLIDER clamps to its end-stops (R2 point 3), mirroring
   * `ResolutionControl` for the frame-count family. Non-positive / NaN
   * entries are ignored.
   */
  function onNFftText(v: number) {
    if (!Number.isFinite(v) || v < 1) return;
    const exp = Math.round(Math.log2(v));   // nearest power of two
    onRes(exp);                             // patch stores 1<<exp; slider clamps
  }

  function onTarget(v: string) {
    analysisSettings.setTarget(v === 'all' ? 'all' : Number(v));
  }
</script>

<section class="ctx-card card-controls" aria-label="Sonogram stage controls">
  <div class="ctx-name"><span class="cn-t">Sonogram</span><span class="cn-s">time–freq</span></div>
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
          <select bind:value={ch} onchange={() => live.schedule()} style="width:66px" aria-label="channel">
            {#each Array.from({ length: Math.max(1, chOptions) }, (_, c) => c) as c (c)}
              <option value={c}>ch_{c}</option>
            {/each}
          </select>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">resolution — {mixed('nFft') ? '–mixed–' : `${nFft} pt`}</span>
        <div class="grp-ctl">
          <input type="range" min={RES_MIN_EXP} max={RES_MAX_EXP}
            value={Math.min(RES_MAX_EXP, Math.max(RES_MIN_EXP, resExp))}
            oninput={(e) => onRes(+e.currentTarget.value)} style="width:96px" aria-label="resolution" />
          <span class="ml">nFFT</span>
          <input type="number" step="1" min="1"
            value={mixed('nFft') ? '' : nFft}
            placeholder={mixed('nFft') ? '–mixed–' : ''}
            onchange={(e) => onNFftText(+e.currentTarget.value)}
            style="width:64px" aria-label="nFFT" />
          <span class="note">pt</span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">dynamic range</span>
        <div class="grp-ctl">
          <input type="number" value={mixed('dynRangeDb') ? '' : sono.dynRangeDb}
            placeholder={mixed('dynRangeDb') ? '–mixed–' : ''}
            onchange={(e) => patch({ dynRangeDb: +e.currentTarget.value })}
            step="10" min="30" max="120" style="width:56px" aria-label="dynamic range dB" /><span class="ml">dB</span>
        </div>
      </div>
    </div>
    {#if $computeErrors.sono}
      <div class="ctx-err" role="alert">{$computeErrors.sono}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button class="btn indigo" disabled={$busy || $setsView.length === 0} onclick={calc}>Calc Sonogram</button>
  </div>
</section>
