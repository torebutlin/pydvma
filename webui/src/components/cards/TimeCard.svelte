<script lang="ts">
  /**
   * Time-stage context card (design spec §3; visuals ported from the
   * `data-card="time"` block of dev/mockups/round2-bench.html). Quick
   * x-range chips, an input-channel select for Clean Impulse, and a
   * (Task 14) Save Figure placeholder.
   *
   * Wiring: `[Full]` / `[First 0.2 s]` drive `viewState` range on the
   * time view; Clean Impulse calls `actions.cleanImpulse` for the
   * highlighted set's chosen channel; the channel select spans the
   * widest loaded set. Save Figure jumps to the Export stage (Task 14),
   * whose ExportCard hosts the PNG/PDF figure dialog — one export flow,
   * reachable from the labsheet's Time card as a shortcut.
   */
  import type { ViewState } from '../../lib/stores/viewstate';
  import type { Selection } from '../../lib/stores/selection';
  import type { Actions } from '../../lib/analysis/actions';

  let {
    viewState,
    selection,
    actions,
  }: { viewState: ViewState; selection: Selection; actions: Actions } = $props();

  const setsView = $derived(selection.setsView);
  const highlight = $derived(selection.highlight);
  const computeErrors = $derived(actions.computeErrors);
  const busy = $derived(actions.busy);
  // Clean Impulse is a TOGGLE (round-7b): on = the cleaned arrays are
  // applied (raw stashed), off = raw restored. Cleaning never re-runs on
  // its own output; the flag tracks the APPLIED state per set.
  const cleanedSets = $derived(actions.cleanedSets);

  // Widest set drives the impulse-channel options.
  const maxChannels = $derived($setsView.reduce((m, s) => Math.max(m, s.nChannels), 0));
  let impulseCh = $state(0);

  /** The highlighted set's id (Clean Impulse target), or the first set. */
  const targetId = $derived.by(() => {
    const list = $setsView;
    if (list.some((s) => s.id === $highlight)) return $highlight;
    return list.length ? list[0].id : -1;
  });

  function clean() {
    if (targetId >= 0) actions.cleanImpulse(targetId, impulseCh);
  }
  const isCleaned = $derived(targetId >= 0 && !!$cleanedSets[targetId]);
</script>

<section class="ctx-card card-controls" aria-label="Time stage controls">
  <div class="ctx-name"><span class="cn-t">Time</span><span class="cn-s">inspect</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">input channel</span>
        <div class="grp-ctl">
          <select bind:value={impulseCh} style="width:84px" aria-label="input channel">
            {#each Array.from({ length: Math.max(1, maxChannels) }, (_, c) => c) as c (c)}
              <option value={c}>ch_{c}</option>
            {/each}
          </select>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">x-range</span>
        <div class="grp-ctl">
          <button class="btn sm" onclick={() => viewState.autoFit('time')}>Full</button>
          <button class="btn sm" onclick={() => viewState.setRange('time', { x: [0, 0.2], y: null })}
            >First 0.2 s</button
          >
        </div>
      </div>
    </div>
    {#if $computeErrors.clean}
      <div class="ctx-err" role="alert">{$computeErrors.clean}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <button
      class="btn indigo"
      class:on={isCleaned}
      aria-pressed={isCleaned}
      data-testid="clean-impulse-toggle"
      disabled={$busy || targetId < 0}
      title={isCleaned
        ? 'Cleaned data applied — click to restore the raw recording (the clean stays cached)'
        : 'Zero the pre-impulse noise and window the tail (toggles — the raw data is kept)'}
      onclick={clean}>{isCleaned ? 'Clean Impulse: on' : 'Clean Impulse'}</button
    >
  </div>
</section>

<style>
  /* Toggle-on state: the indigo button flips to its soft/active look so the
     applied clean reads at a glance (mirrors the toolbar's .active idiom). */
  .btn.indigo.on {
    background: var(--accent-soft);
    border-color: var(--accent-soft-border);
    color: var(--indigo, #4f46e5);
  }
</style>
