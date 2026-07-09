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
   *   - fit lines (local | global) — round-7 item 6, replacing the old
   *     Local/Global visibility button pair: an either/or Segmented choice of
   *     WHICH reconstruction the modal-fit pseudo-sets draw (the tray cards
   *     whose dashed lines flow through the normal visible pipeline, one per
   *     spanned set, all channels — round-5 item 13). 'global' (default) is
   *     the whole model on each set's measured axis; 'local' is the
   *     just-fitted modes dense over the fit window (empty again after any
   *     non-fit recompute, so local lines are the transient just-fitted
   *     feedback — now for ALL sets/channels, not the old primary-set-only
   *     pink overlay). Show/hide is the legend / tray tri-state, and the
   *     legend names carry the mode ("Modal fit local (set)").
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
  import type { Selection } from '../../lib/stores/selection';
  import type { ViewState, TfPlotType } from '../../lib/stores/viewstate';
  import type { ModalStore, ReconMode } from '../../lib/stores/modal';
  import Segmented from '../Segmented.svelte';

  let {
    actions,
    analysisSettings,
    selection,
    viewState,
    modal,
  }: {
    actions: Actions;
    analysisSettings: AnalysisSettings;
    selection: Selection;
    viewState: ViewState;
    modal: ModalStore;
  } = $props();

  const busy = $derived(actions.busy);
  const computeErrors = $derived(actions.computeErrors);
  const sharedFreq = $derived(viewState.sharedFreqRange);
  const modalState = $derived(modal);

  // View-type chips (round-5 item 9): the Fit stage reuses the 'tf' view, so
  // the same projection options as the TF card must be reachable while fitting
  // — you fit against whatever projection reads best (Nyquist circles, Bode,
  // real/imag). Drives the ACTIVE ('tf') view's plotType, so the plot and the
  // TF card's selector stay in lock-step.
  const current = $derived(viewState.current);
  const plotType = $derived($current.plotType);
  const PLOT_TYPES: { id: TfPlotType; label: string }[] = [
    { id: 'mag', label: 'Mag (dB)' }, { id: 'phase', label: 'Phase' },
    { id: 'bode', label: 'Bode' }, { id: 'real', label: 'Real' },
    { id: 'imag', label: 'Imag' }, { id: 'nyquist', label: 'Nyquist' },
  ];
  // Gate: fitting needs a computed TF. Mirrors the ribbon's `fitEngine`
  // capability (which flips on the first TF); until then the fit buttons
  // are disabled and the card explains what to do — the stage stays
  // navigable per the gated-stage design, but can't issue a doomed fit.
  const derivedMap = $derived(actions.derived);
  const setsView = $derived(selection.dataSetsView);
  // TF-bearing DATA sets (excludes the fit pseudo-set, which dataSetsView drops)
  // — the pool the fit-target dropdown offers and the `hasTf` gate reads.
  const tfSets = $derived(
    $setsView.filter((s) => {
      const d = $derivedMap[s.id];
      return d?.tf && ((d.tf.data.shape[1] ?? 0) > 0);
    }),
  );
  const hasTf = $derived(tfSets.length > 0);

  // Fit target (round-6 item 7): 'shared' = a JOINT shared-pole fit over EVERY
  // TF-bearing set (one fn/zn per mode, per-set amplitudes — Qt's hammer-test
  // workflow); a setId = fit that ONE set. Defaults to 'shared' when more than
  // one set has a TF, else the single set. Kept LOCAL to the card (not
  // analysisSettings.analysisTarget), because 'all' there means "each set
  // independently" — a different semantic from "all sets jointly".
  let fitTarget = $state<'shared' | number>('shared');
  // Reconcile the selection with the live TF-set pool: one set ⇒ that set;
  // several ⇒ default 'shared'; drop a stale numeric target that lost its TF.
  $effect(() => {
    const ids = tfSets.map((s) => s.id);
    if (ids.length === 1) {
      if (fitTarget !== ids[0]) fitTarget = ids[0];
    } else if (ids.length > 1) {
      if (fitTarget !== 'shared' && !ids.includes(fitTarget as number)) fitTarget = 'shared';
    }
  });

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

  const nModes = $derived($modalState.modes.length);

  // What a Fit would use RIGHT NOW (round-7h): the fit takes the LINES LEFT
  // VISIBLE in the legend/tray — hide or solo lines there to choose exactly
  // which line(s) are fitted. Re-derived on tri-state changes via the
  // legendEntries subscription (the summary itself is a pure actions read).
  const legendEntriesStore = $derived(selection.legendEntries);
  const fitLines = $derived.by(() => {
    void $legendEntriesStore;
    return actions.fitLineSummary(fitTarget);
  });

  // 'fit' honours the chosen target; reject / refine operate on the EXISTING
  // model, which calcFit resolves from the stored spanned-set composition (the
  // target passed is only used when no model exists yet).
  function fit(n: number) { actions.calcFit(fitTarget, range, mt, 'fit', n); }
  function reject() { actions.calcFit(fitTarget, range, mt, 'reject'); }
  function refine() { actions.calcFit(fitTarget, null, mt, 'refine'); }
  function undo() { modal.undo(); }

  // Fit-lines toggle (round-7 item 6): an either/or choice of WHICH recon the
  // fit pseudo-sets draw. The store update triggers the actions layer's
  // syncModal, which refeeds every pseudo-set's slice + renames its legend row.
  const RECON_MODES: { value: ReconMode; label: string; title: string; testid: string }[] = [
    { value: 'local', label: 'local', testid: 'fit-lines-local',
      title: 'Draw the just-fitted modes over the fit window (all sets/channels); cleared by any non-fit recompute' },
    { value: 'global', label: 'global', testid: 'fit-lines-global',
      title: 'Draw the whole model over each set’s measured frequency axis (all sets/channels)' },
  ];
</script>

<section class="ctx-card card-controls" aria-label="Fit stage controls">
  <div class="ctx-name"><span class="cn-t">Fit</span><span class="cn-s">modal</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      {#if tfSets.length > 1}
        <div class="grp">
          <span class="grp-lab">sets</span>
          <div class="grp-ctl">
            <select bind:value={fitTarget} disabled={$busy}
              aria-label="Fit target"
              title="Fit all sets jointly with shared poles (one fn/ζ per mode), or one set alone">
              <option value="shared">All sets (shared poles)</option>
              {#each tfSets as s (s.id)}<option value={s.id}>{s.name}</option>{/each}
            </select>
          </div>
        </div>
      {/if}
      <div class="grp">
        <span class="grp-lab">peak fits</span>
        <div class="grp-ctl">
          <button class="btn indigo-t" disabled={$busy || !hasTf} onclick={() => fit(1)}
            title="Fit one mode in the visible frequency window">Fit 1</button>
          <button class="btn indigo-t" disabled={$busy || !hasTf} onclick={() => fit(2)}
            title="Fit two modes in the visible window (split at detected peaks)">Fit 2</button>
          <button class="btn indigo-t" disabled={$busy || !hasTf} onclick={() => fit(3)}
            title="Fit three modes in the visible window (split at detected peaks)">Fit 3</button>
          {#if fitLines.total > 0}
            <span class="note" data-testid="fit-lines-note"
              title="A Fit uses the lines left visible — hide or solo lines in the legend/tray to choose exactly which line(s) are fitted">
              {fitLines.fitted === fitLines.total
                ? `all ${fitLines.total} line${fitLines.total === 1 ? '' : 's'}`
                : `${fitLines.fitted} of ${fitLines.total} lines (visible only)`}
            </span>
          {/if}
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
        <span class="grp-lab">fit lines</span>
        <div class="grp-ctl">
          <Segmented testid="fit-lines-toggle" ariaLabel="Fit lines reconstruction"
            options={RECON_MODES} value={$modalState.reconMode}
            onchange={(v) => modal.setReconMode(v)} />
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
      <div class="grp">
        <span class="grp-lab">view</span>
        <div class="grp-ctl">
          <select value={plotType} aria-label="TF plot type"
            onchange={(e) => viewState.setPlotType(e.currentTarget.value as TfPlotType)}>
            {#each PLOT_TYPES as p (p.id)}<option value={p.id}>{p.label}</option>{/each}
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
