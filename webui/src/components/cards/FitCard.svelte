<script lang="ts">
  /**
   * Fit-stage context card (design spec §3; visuals ported from
   * dev/mockups/round2-bench.html `.ctx-card[data-card=fit]`, lines 556-575).
   *
   * Modal curve-fitting over the CURRENT visible TF window
   * (`viewState.sharedFreqRange`), scoped to the analysis TARGET set's TF
   * (the Fit stage reuses the 'tf' view). Buttons mirror the Qt driver:
   *
   *   - Fit 1 / Fit 2 / Fit 3 — fit that many modes in the visible window and
   *     accumulate them into the dataset's modal model (`calc_fit` action
   *     'fit'; Fit 2/3 split the window at detected peaks — best-effort);
   *   - Reject — delete modes whose fn lies in the visible window;
   *   - Refine — simultaneously refine ALL fitted modes (round-4 item 10;
   *     `calc_fit` action 'refine'), auto-reverting if it does not improve;
   *   - Local / Global — independent visibility toggles for the pink local
   *     (just-fitted) and grey-dashed global (whole-model) recon overlays
   *     (round-4 item 9 — the dashed global read as too subtle on its own).
   *   - Undo — appears after a destructive/refine action; one level.
   *
   * The mockup's "Summary" is realised as the ALWAYS-ON floating mode chip
   * (`FitChip`, mounted over the plot by App), which also carries the per-mode
   * mute / delete controls; this card's primary slot shows a running "N
   * mode(s) fitted" count. "Global optimise" from the mockup is realised as
   * Refine (a refine-from-current, not a from-scratch global fit).
   *
   * TF measurement type ('acc'|'vel'|'dsp') is a Fit-card control here (Qt
   * keeps it on the TF card's "TF type" combo); it drives the `(iω)^p` power
   * in the modal transfer-function model.
   */
  import type { Actions, MeasurementType } from '../../lib/analysis/actions';
  import type { AnalysisSettings } from '../../lib/stores/analysisSettings';
  import type { ViewState } from '../../lib/stores/viewstate';
  import type { ModalStore } from '../../lib/stores/modal';

  let {
    actions,
    analysisSettings,
    viewState,
    modal,
  }: {
    actions: Actions;
    analysisSettings: AnalysisSettings;
    viewState: ViewState;
    modal: ModalStore;
  } = $props();

  const busy = $derived(actions.busy);
  const computeErrors = $derived(actions.computeErrors);
  const target = $derived(analysisSettings.analysisTarget);
  const sharedFreq = $derived(viewState.sharedFreqRange);
  const modalState = $derived(modal);
  // Gate: fitting needs a computed TF. Mirrors the ribbon's `fitEngine`
  // capability (which flips on the first TF); until then the fit buttons
  // are disabled and the card explains what to do — the stage stays
  // navigable per the gated-stage design, but can't issue a doomed fit.
  const derivedMap = $derived(actions.derived);
  const hasTf = $derived(Object.values($derivedMap).some((s) => s?.tf !== undefined));

  // Measurement type drives the modal TF model's (iω)^p power (acc→2, vel→1,
  // dsp→0). Local to the card — a per-view fit control, not a per-set setting.
  let mt = $state<MeasurementType>('acc');

  const MT: { id: MeasurementType; label: string }[] = [
    { id: 'acc', label: 'Acceleration' },
    { id: 'vel', label: 'Velocity' },
    { id: 'dsp', label: 'Displacement' },
  ];

  const range = $derived<[number, number] | null>($sharedFreq ?? null);

  // Mirror the measurement type into the modal store so the chip's per-mode
  // delete / mute recompute the overlays with the same (iω)^p power.
  $effect(() => { modal.setMt(mt); });

  // Refine / undo operate on the SAME set the model targets.
  const modelTarget = $derived($modalState.setId ?? $target);
  const nModes = $derived($modalState.modes.length);

  function fit(n: number) { actions.calcFit($target, range, mt, 'fit', n); }
  function reject() { actions.calcFit($target, range, mt, 'reject'); }
  function refine() { actions.calcFit(modelTarget, null, mt, 'refine'); }
  function undo() { modal.undo(); }
  function toggleLocal() { modal.toggleLocal(); }
  function toggleGlobal() { modal.toggleGlobal(); }
</script>

<section class="ctx-card card-controls" aria-label="Fit stage controls">
  <div class="ctx-name"><span class="cn-t">Fit</span><span class="cn-s">modal</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">peak fits</span>
        <div class="grp-ctl">
          <button class="btn indigo-t" disabled={$busy || !hasTf} onclick={() => fit(1)}
            title="Fit one mode in the visible frequency window">Fit 1</button>
          <button class="btn indigo-t" disabled={$busy || !hasTf} onclick={() => fit(2)}
            title="Fit two modes in the visible window (split at detected peaks)">Fit 2</button>
          <button class="btn indigo-t" disabled={$busy || !hasTf} onclick={() => fit(3)}
            title="Fit three modes in the visible window (split at detected peaks)">Fit 3</button>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">modes</span>
        <div class="grp-ctl">
          <button class="btn" disabled={$busy} onclick={reject}
            title="Delete mode fits whose frequency lies in the visible window">Reject</button>
          <button class="btn indigo-t" disabled={$busy || nModes < 2} onclick={refine}
            title="Refine all fitted modes simultaneously (neighbouring modes interact); auto-reverts if it does not improve">Refine</button>
          {#if $modalState.undo}
            <button class="btn" disabled={$busy} onclick={undo}
              title="Undo the last modal change">↶ Undo</button>
          {/if}
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">overlays</span>
        <div class="grp-ctl">
          <button class="btn" class:on={$modalState.showLocal}
            disabled={$modalState.setId === null} onclick={toggleLocal}
            title="Toggle the local (just-fitted) reconstruction overlay">Local</button>
          <button class="btn" class:on={$modalState.showGlobal}
            disabled={$modalState.setId === null} onclick={toggleGlobal}
            title="Toggle the global (whole-model) reconstruction overlay">Global</button>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">TF type</span>
        <div class="grp-ctl">
          <select bind:value={mt} aria-label="TF measurement type">
            {#each MT as m (m.id)}<option value={m.id}>{m.label}</option>{/each}
          </select>
        </div>
      </div>
    </div>
    {#if !hasTf}
      <div class="ctx-note">Fit needs a computed transfer function — run Calc TF on the TF stage first.</div>
    {:else if $computeErrors.fit}
      <div class="ctx-err" role="alert">{$computeErrors.fit}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    <div class="fit-count">
      {#if $modalState.modes.length}
        {$modalState.modes.length} mode{$modalState.modes.length === 1 ? '' : 's'} fitted
      {:else}
        no modes yet
      {/if}
    </div>
  </div>
</section>

<style>
  .fit-count {
    font-size: 12px;
    color: var(--muted);
    white-space: nowrap;
  }
  /* Mirrors ContextCard's .ctx-note (Svelte styles are component-scoped). */
  .ctx-note {
    font-size: 12px;
    color: var(--muted);
    font-style: italic;
  }
</style>
