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
   *   - Reconstruction — toggle the global (grey dashed) reconstruction overlay.
   *
   * The mockup's "Summary" is realised as the ALWAYS-ON floating mode chip
   * (`FitChip`, mounted over the plot by App), so no separate button is needed;
   * this card's primary slot shows a running "N mode(s) fitted" count.
   * "Global optimise" from the mockup is OMITTED — pydvma has no simultaneous
   * multi-mode entry point (deferred; flagged to Tore), and a dead disabled
   * button is worse than none.
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

  function fit(nModes: number) { actions.calcFit($target, range, mt, 'fit', nModes); }
  function reject() { actions.calcFit($target, range, mt, 'reject'); }
  function toggleRecon() { modal.toggleGlobal(); }
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
        <span class="grp-lab">inspect</span>
        <div class="grp-ctl">
          <button class="btn" disabled={$busy} onclick={reject}
            title="Delete mode fits whose frequency lies in the visible window">Reject</button>
          <button class="btn" class:on={$modalState.showGlobal}
            disabled={$modalState.setId === null} onclick={toggleRecon}
            title="Toggle the global modal reconstruction overlay">Reconstruction</button>
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
