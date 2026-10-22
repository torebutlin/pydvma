<script lang="ts">
  /**
   * Time-stage context card (design spec §3; visuals ported from the
   * `data-card="time"` block of dev/mockups/round2-bench.html). A
   * "dataset" choice, quick x-range chips, an input-channel select for
   * Clean Impulse, and the Resample tool.
   *
   * Wiring: the dataset dropdown is the shared `analysisTarget` (All sets +
   * one entry per set, following the tray like every analysis card);
   * Clean Impulse and Resample act on the chosen set, or on every
   * time-bearing set for 'All sets'. `[Full]` / `[First 0.2 s]` drive
   * `viewState` range on the time view. The channel select spans the
   * widest targeted set.
   */
  import type { ViewState } from '../../lib/stores/viewstate';
  import type { Selection } from '../../lib/stores/selection';
  import type { Actions } from '../../lib/analysis/actions';
  import type { AnalysisSettings } from '../../lib/stores/analysisSettings';
  import { IMPULSE_TAIL_MAX, looksLikeImpulse } from '../../lib/analysis/impulse';

  let {
    viewState,
    selection,
    actions,
    analysisSettings,
  }: {
    viewState: ViewState; selection: Selection; actions: Actions; analysisSettings: AnalysisSettings;
  } = $props();

  // DATA sets only: a modal-fit pseudo-set has no time data to clean.
  const setsView = $derived(selection.dataSetsView);
  const target = $derived(analysisSettings.analysisTarget);
  const computeErrors = $derived(actions.computeErrors);
  const busy = $derived(actions.busy);
  // Clean Impulse is a TOGGLE (round-7b): on = the cleaned arrays are
  // applied (raw stashed), off = raw restored. Cleaning never re-runs on
  // its own output; the flag tracks the APPLIED state per set.
  const cleanedSets = $derived(actions.cleanedSets);

  // `workingSets()` is a plain accessor — re-read it when the set list or
  // the busy flag changes so the fs labels track resamples/removals.
  const workingInfo = $derived.by(() => {
    void $setsView; void $busy;
    return actions.workingSets();
  });
  const nameOf = (id: number): string => $setsView.find((s) => s.id === id)?.name ?? `set ${id}`;

  /** The sets Clean Impulse and Resample act on: every time-bearing set for
   *  'All sets', else the chosen one (none when it has no time data). */
  const targetIds = $derived.by(() => {
    const timed = workingInfo.filter((w) => w.hasTime).map((w) => w.setId);
    if ($target === 'all') return timed;
    return timed.includes($target) ? [$target] : [];
  });

  // The widest targeted set drives the impulse-channel options.
  const maxChannels = $derived($setsView
    .filter((s) => targetIds.includes(s.id))
    .reduce((m, s) => Math.max(m, s.nChannels), 0));
  let impulseCh = $state(0);
  // A narrower target than before (e.g. one 1-channel set picked after All
  // sets) would leave the select on a channel it no longer lists.
  $effect(() => {
    if (maxChannels > 0 && impulseCh >= maxChannels) impulseCh = 0;
  });

  function onTarget(v: string) {
    analysisSettings.setTarget(v === 'all' ? 'all' : Number(v));
  }

  // Round-15 item 4: offer Clean Impulse only where the chosen input
  // channel actually looks like an impulse — at most IMPULSE_TAIL_MAX of
  // its energy in the second half of the record (see lib/analysis/
  // impulse.ts). A set that is already cleaned stays eligible so the
  // toggle can be turned off again. Re-read when the set list, the busy
  // flag (a resample / clean changes the arrays) or the channel changes.
  const impulse = $derived.by(() => {
    void $busy;
    return targetIds.map((id) => ({
      id,
      cleaned: !!$cleanedSets[id],
      tail: actions.impulseEnergyTail(id, impulseCh),
    }));
  });
  const eligible = $derived(impulse.filter((i) => i.cleaned || looksLikeImpulse(i.tail)));
  const leftOut = $derived(impulse.filter((i) => !(i.cleaned || looksLikeImpulse(i.tail))));
  const nOn = $derived(eligible.filter((i) => i.cleaned).length);
  /** Every eligible set is cleaned: the button reads "on" and turns them off. */
  const allOn = $derived(eligible.length > 0 && nOn === eligible.length);

  function clean() {
    void actions.setImpulseClean(eligible.map((i) => i.id), impulseCh, !allOn);
  }
  const tailNote = (tail: number | null): string => tail === null
    ? `ch_${impulseCh} has no signal to clean`
    : `not an impulse on ch_${impulseCh} (${Math.round(tail * 100)}% of its energy is in the second half)`;

  // ---- Resample (round-9) -------------------------------------------------
  // Change the targeted sets' sample rate: pick a set to MATCH (dropdown
  // shows each set's fs) or a custom fs. Down = noise-reducing anti-alias
  // decimation; up = band-limited interpolation (no invented high-frequency
  // content). One-level Undo via the success toast.
  const fmtFs = (fs: number): string =>
    fs >= 1000 ? `${(fs / 1000).toFixed(3).replace(/\.?0+$/, '')} kHz` : `${fs.toFixed(6).replace(/\.?0+$/, '')} Hz`;
  const sameFs = (a: number, b: number) => Math.abs(a - b) / b <= 1e-9;
  const targetFs = $derived(workingInfo.filter((w) => targetIds.includes(w.setId)).map((w) => w.fs));
  /** The targeted sets' common rate, or null when they differ (or there are none). */
  const currentFs = $derived(targetFs.length && targetFs.every((f) => sameFs(f, targetFs[0]))
    ? targetFs[0] : null);
  // The "match" choices: time-bearing sets whose rate differs from at least
  // one targeted set (one entry per distinct rate).
  const matchOptions = $derived.by(() => {
    const out: { setId: number; fs: number; name: string }[] = [];
    for (const w of workingInfo) {
      if (!w.hasTime || !targetFs.some((f) => !sameFs(w.fs, f))) continue;
      if (out.some((o) => sameFs(o.fs, w.fs))) continue;
      out.push({ setId: w.setId, fs: w.fs, name: nameOf(w.setId) });
    }
    return out;
  });
  let resampleChoice = $state<string>('custom');
  let customFs = $state<number | null>(null);
  // A stale match selection (set removed / fs now equal) falls back to custom.
  $effect(() => {
    if (resampleChoice !== 'custom'
        && !matchOptions.some((o) => String(o.setId) === resampleChoice)) {
      resampleChoice = 'custom';
    }
  });
  const resampleFs = $derived(resampleChoice === 'custom'
    ? (customFs && customFs > 0 ? customFs : null)
    : matchOptions.find((o) => String(o.setId) === resampleChoice)?.fs ?? null);
  const canResample = $derived(!$busy && resampleFs !== null
    && targetFs.some((f) => !sameFs(resampleFs, f)));
  function doResample() {
    if (canResample && resampleFs !== null) {
      void actions.resampleSets(targetIds, resampleFs, { notify: true });
    }
  }
</script>

<section class="ctx-card card-controls" aria-label="Time stage controls">
  <div class="ctx-name"><span class="cn-t">Time</span><span class="cn-s">inspect</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">dataset</span>
        <div class="grp-ctl">
          <select value={$target === 'all' ? 'all' : String($target)}
            onchange={(e) => onTarget(e.currentTarget.value)}
            style="width:120px" aria-label="dataset" data-testid="time-dataset">
            <option value="all">All sets</option>
            {#each $setsView as s (s.id)}
              <option value={String(s.id)}>{s.name}</option>
            {/each}
          </select>
        </div>
      </div>
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
    {#if targetIds.length}
      <div class="ctx-row">
        <div class="grp">
          <span class="grp-lab">resample — now {currentFs !== null ? fmtFs(currentFs) : 'mixed rates'}</span>
          <div class="grp-ctl">
            <select bind:value={resampleChoice} aria-label="resample target"
              title="Pick a set to match its sample rate, or choose a custom rate">
              {#each matchOptions as o (o.setId)}
                <option value={String(o.setId)}>match {o.name} ({fmtFs(o.fs)})</option>
              {/each}
              <option value="custom">custom…</option>
            </select>
            {#if resampleChoice === 'custom'}
              <input type="number" min="1" step="1" bind:value={customFs}
                placeholder="new fs" style="width:76px" aria-label="new sample rate Hz" />
              <span class="ml">Hz</span>
            {/if}
            <button class="btn sm" disabled={!canResample}
              data-testid="resample-apply"
              title={`${targetIds.length > 1 ? 'Resamples every set in the dataset choice. ' : ''}Down: noise-reducing anti-alias decimation. Up: band-limited interpolation (no invented high-frequency content). Undo via the toast.`}
              onclick={doResample}>Resample</button>
          </div>
        </div>
      </div>
    {/if}
    {#if eligible.length && leftOut.length}
      <div class="ctx-row">
        <span class="note" data-testid="clean-impulse-left-out"
          title={`Clean Impulse is offered when at most ${Math.round(IMPULSE_TAIL_MAX * 100)}% of the input channel's energy is in the second half of the record`}>
          Clean Impulse leaves out {leftOut.map((i) => nameOf(i.id)).join(', ')}
          (not an impulse on ch_{impulseCh})
        </span>
      </div>
    {/if}
    {#if $computeErrors.clean}
      <div class="ctx-err" role="alert">{$computeErrors.clean}</div>
    {/if}
    {#if $computeErrors.resample}
      <div class="ctx-err" role="alert">{$computeErrors.resample}</div>
    {/if}
  </div>
  <div class="ctx-primary">
    {#if eligible.length}
      <button
        class="btn indigo"
        class:on={allOn}
        aria-pressed={allOn}
        data-testid="clean-impulse-toggle"
        disabled={$busy}
        title={allOn
          ? 'Cleaned data applied — click to restore the raw recording (the clean stays cached)'
          : 'Zero the pre-impulse noise and window the tail (toggles — the raw data is kept)'}
        onclick={clean}>{allOn
          ? 'Clean Impulse: on'
          : nOn > 0 ? `Clean Impulse: ${nOn} of ${eligible.length} on` : 'Clean Impulse'}</button
      >
    {:else if impulse.length}
      <span class="note" data-testid="clean-impulse-hidden"
        title={`Clean Impulse is offered when at most ${Math.round(IMPULSE_TAIL_MAX * 100)}% of the input channel's energy is in the second half of the record`}>
        {impulse.length === 1 ? tailNote(impulse[0].tail) : `no set looks like an impulse on ch_${impulseCh}`}
      </span>
    {/if}
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
