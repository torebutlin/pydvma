<script lang="ts">
  /**
   * Sonogram-stage context card (design spec §3; visuals ported from
   * the `data-card="sonogram"` block of round2-bench.html).
   *
   * Set/channel selects choose the source; a live resolution slider
   * maps to the STFT window size `nFft = 2^slider` (nperseg=nFft,
   * noverlap=nFft/2 in the worker); a dynamic-range dB input clamps the
   * heat-map floor (consumed by the App's canvas heat layer via
   * `dynRangeDb`). Calc Sonogram runs `actions.calcSono`. The slider
   * re-issues live but DEBOUNCED (150 ms); the action carries a per-kind
   * stale seq (key 'sono') so an old sonogram response never clobbers a
   * newer one, and — being per-kind — never cross-drops an in-flight
   * result of another kind (e.g. a running TF batch).
   */
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';

  let {
    actions,
    selection,
    dynRangeDb = $bindable(60),
    sonoSetIdx = $bindable(0),
  }: {
    actions: Actions;
    selection: Selection;
    dynRangeDb?: number;
    /** Selected source-set index; bound up so App renders THIS set's sono. */
    sonoSetIdx?: number;
  } = $props();

  const setsView = $derived(selection.setsView);
  const computeError = $derived(actions.computeError);
  const busy = $derived(actions.busy);

  let ch = $state(0);
  let resExp = $state(9); // slider position → nFft = 2^resExp (default 512)

  const nFft = $derived(1 << resExp);
  const chOptions = $derived($setsView[sonoSetIdx]?.nChannels ?? 1);

  function calc() {
    if ($setsView.length) actions.calcSono(sonoSetIdx, ch, nFft);
  }

  let debounceId: ReturnType<typeof setTimeout> | undefined;
  function onRes(v: number) {
    resExp = v;
    clearTimeout(debounceId);
    debounceId = setTimeout(calc, 150);
  }
</script>

<section class="ctx-card card-controls" aria-label="Sonogram stage controls">
  <div class="ctx-name"><span class="cn-t">Sonogram</span><span class="cn-s">time–freq</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">source</span>
        <div class="grp-ctl">
          <select bind:value={sonoSetIdx} style="width:96px" aria-label="set">
            {#each $setsView as s, i (s.id)}
              <option value={i}>{s.name}</option>
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
        <span class="grp-lab">resolution — {nFft} pt</span>
        <div class="grp-ctl">
          <input type="range" min="6" max="12" value={resExp}
            oninput={(e) => onRes(+e.currentTarget.value)} style="width:96px" aria-label="resolution" />
          <span class="mono" style="font-size:11.5px">nFFT = {nFft}</span>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">dynamic range</span>
        <div class="grp-ctl">
          <input type="number" bind:value={dynRangeDb} step="10" min="30" max="120"
            style="width:56px" aria-label="dynamic range dB" /><span class="ml">dB</span>
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
