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

  // ---- Resample (round-9) -------------------------------------------------
  // Change the highlighted set's sample rate: pick another set to MATCH
  // (dropdown shows each set's fs) or a custom fs. Down = noise-reducing
  // anti-alias decimation; up = band-limited interpolation (no invented
  // high-frequency content). One-level Undo via the success toast.
  // `workingSets()` is a plain accessor — re-read it when the set list or
  // the busy flag changes so the fs labels track resamples/removals.
  const workingInfo = $derived.by(() => {
    void $setsView; void $busy;
    return actions.workingSets();
  });
  const currentFs = $derived(workingInfo.find((w) => w.setId === targetId)?.fs ?? null);
  const fmtFs = (fs: number): string =>
    fs >= 1000 ? `${(fs / 1000).toFixed(3).replace(/\.?0+$/, '')} kHz` : `${fs.toFixed(6).replace(/\.?0+$/, '')} Hz`;
  // Other time-bearing sets whose fs differs — the "match" choices.
  const matchOptions = $derived(workingInfo
    .filter((w) => w.hasTime && w.setId !== targetId
      && currentFs !== null && Math.abs(w.fs - currentFs) / currentFs > 1e-9)
    .map((w) => ({
      setId: w.setId, fs: w.fs,
      name: $setsView.find((s) => s.id === w.setId)?.name ?? `set ${w.setId}`,
    })));
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
  const canResample = $derived(!$busy && targetId >= 0 && currentFs !== null
    && resampleFs !== null && Math.abs(resampleFs - currentFs) / currentFs > 1e-9);
  function doResample() {
    if (canResample && resampleFs !== null) {
      void actions.resampleTime(targetId, resampleFs, { notify: true });
    }
  }
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
    {#if currentFs !== null}
      <div class="ctx-row">
        <div class="grp">
          <span class="grp-lab">resample — now {fmtFs(currentFs)}</span>
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
              title="Down: noise-reducing anti-alias decimation. Up: band-limited interpolation (no invented high-frequency content). Undo via the toast."
              onclick={doResample}>Resample</button>
          </div>
        </div>
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
