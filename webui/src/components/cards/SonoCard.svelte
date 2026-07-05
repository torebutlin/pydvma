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
   * Calc Sonogram runs `actions.calcSono(target, ch)`. The slider
   * re-issues live but DEBOUNCED (150 ms); the action carries a per-kind
   * stale seq (key 'sono').
   */
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';
  import type { AnalysisSettings } from '../../lib/stores/analysisSettings';

  let {
    actions,
    selection,
    analysisSettings,
  }: { actions: Actions; selection: Selection; analysisSettings: AnalysisSettings } = $props();

  const setsView = $derived(selection.setsView);
  const computeError = $derived(actions.computeError);
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

  let debounceId: ReturnType<typeof setTimeout> | undefined;
  function onRes(v: number) {
    patch({ nFft: 1 << v });
    clearTimeout(debounceId);
    debounceId = setTimeout(calc, 150);
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
          <select bind:value={ch} style="width:66px" aria-label="channel">
            {#each Array.from({ length: Math.max(1, chOptions) }, (_, c) => c) as c (c)}
              <option value={c}>ch_{c}</option>
            {/each}
          </select>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">resolution — {mixed('nFft') ? '–mixed–' : `${nFft} pt`}</span>
        <div class="grp-ctl">
          <input type="range" min="6" max="12" value={resExp}
            oninput={(e) => onRes(+e.currentTarget.value)} style="width:96px" aria-label="resolution" />
          <span class="mono" style="font-size:11.5px">nFFT = {mixed('nFft') ? '–mixed–' : nFft}</span>
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
    {#if $computeError}
      <div class="ctx-err" role="alert">{$computeError}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button class="btn indigo" disabled={$busy || $setsView.length === 0} onclick={calc}>Calc Sonogram</button>
  </div>
</section>
