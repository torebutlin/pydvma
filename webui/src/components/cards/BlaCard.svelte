<script lang="ts">
  /**
   * Nonlin-stage context card — the user-facing surface of the Schoukens BLA
   * workflow (design: `dev/plans/2026-08-10-schoukens-bla-design.md`, "UX — a
   * new Nonlin stage").
   *
   * Three groups, top to bottom:
   *
   *  - **design** (`bla-design`) — band f1–f2, frequency resolution Δf with the
   *    period shown in BOTH samples and seconds (N is the primitive: the
   *    excitation is defined in samples so periodicity survives clock
   *    coercion, but seconds is what the user feels), excitation level, the
   *    M / P / transient counts, the per-AO-channel excitation table with its
   *    x-source choice, the response-channel readout and the total run time.
   *  - **run** (`bla-run`) — Start (disabled, with the reason, whenever
   *    preflight refuses), live `realisation m/M · experiment e/n` progress,
   *    Cancel, and the advisory notes the run acted on (e.g. the pretrigger
   *    auto-disarm).
   *  - **results** (`bla-results`) — one plain-English verdict line per
   *    excitation (see `lib/analysis/blaVerdict.ts`), a "show raw captures"
   *    toggle (the M×n raw sets land hidden) and "new run".
   *
   * The card OWNS no run state: everything reactive comes from the BLA store
   * (`design`, `values`, `checks`, `state`), which in turn reads the live
   * acquisition settings. Every failing check is rendered next to the control
   * its `code` points at rather than in one lump, so a refusal is legible
   * where the fix is.
   */
  import type { BlaStore, BlaOutputRow, XMode } from '../../lib/stores/bla';
  import {
    commandedXSupported, firstBlaError, outputRailFor, BLA_COMMANDED_X_REASON,
  } from '../../lib/stores/bla';
  import type { AcquireStore } from '../../lib/stores/acquire';
  import type { Actions } from '../../lib/analysis/actions';
  import { outputDevices } from '../../lib/audio/provider';
  import { blaVerdicts, summariseBlaVerdicts, worstBlaChannel } from '../../lib/analysis/blaVerdict';

  let {
    bla,
    acquire,
    actions,
  }: {
    bla: BlaStore;
    acquire: AcquireStore;
    actions: Actions;
  } = $props();

  const design = $derived(bla.design);
  const values = $derived(bla.values);
  const checks = $derived(bla.checks);
  const runState = $derived(bla.state);

  const settings = $derived(acquire.settings);
  const bridgeCaps = $derived(acquire.bridgeCaps);
  const bridgeConfig = $derived(acquire.bridgeConfig);
  const kind = $derived(acquire.kind);
  const webOutputDevices = $derived(acquire.webOutputDevices);
  const derivedMap = $derived(actions.derived);

  /**
   * Hard ceiling on excitation-table rows. A soundcard can advertise dozens of
   * output channels; a BLA run drives one multisine per row and the table
   * lives in a context card, so beyond a handful the table stops being usable
   * long before the method does. Raising this is a UI decision, not a method
   * limit (`n_exc` itself is unbounded).
   */
  const MAX_OUTPUT_ROWS = 8;

  // ---- device-derived facts ----

  /** The AO device the run will drive (unset output ⇒ the input device). */
  const outDeviceId = $derived($bridgeConfig.outputDeviceId || $settings.deviceId);
  /** Driver token of that device id (`nidaq:0` → `nidaq`). */
  const outDriver = $derived.by(() => {
    const sep = outDeviceId.indexOf(':');
    return sep >= 0 ? outDeviceId.slice(0, sep) : outDeviceId;
  });
  /**
   * Level unit: the NI path drives a calibrated DAC in VOLTS; the browser and
   * soundcard paths have no calibrated rail, so the level is a fraction of
   * full scale (the ±1 buffer rail) — the same split `outputRailFor` makes.
   */
  const volts = $derived($kind === 'bridge' && outDriver === 'nidaq');
  const ampUnit = $derived(volts ? 'V rms' : '×FS rms');
  const rail = $derived(outputRailFor($kind, $bridgeCaps, $bridgeConfig, $settings.deviceId));

  /** AO channels the effective output device exposes (clamped, ≥ 1). */
  const aoChannels = $derived.by(() => {
    const devs = $kind === 'bridge' ? outputDevices($bridgeCaps) : $webOutputDevices;
    const dev = devs.find((d) => d.deviceId === outDeviceId)
      ?? devs.find((d) => d.deviceId === $settings.deviceId);
    // Unknown output width: the browser path is stereo by convention, and a
    // bridge that advertised no count gets one row (the run itself checks the
    // real AO channel count in preflight).
    const fallback = $kind === 'bridge' ? 1 : 2;
    return Math.max(1, Math.min(MAX_OUTPUT_ROWS, dev?.maxChannels ?? fallback));
  });

  /** Whether the "commanded drive" x-source is admissible on this path. */
  const commandedOk = $derived(commandedXSupported({
    providerKind: $kind,
    caps: $bridgeCaps,
    inputDeviceId: $settings.deviceId,
    outputDeviceId: $bridgeConfig.outputDeviceId,
    stagedOutputFs: $bridgeConfig.outputFs,
    requestedFs: $settings.sampleRate,
    lpfOn: $settings.lpfOn,
  }));

  // Keep the excitation table in step with the device: a new device with more
  // (or fewer) AO channels re-shapes the rows, preserving whatever the user
  // already chose for the rows that survive. New rows arrive DISABLED — a
  // device change must never silently widen a run to more excitations.
  $effect(() => {
    const n = aoChannels;
    const rows = $design.outputs;
    if (rows.length === n) return;
    const nCh = Math.max(0, Math.trunc($settings.channelCount));
    bla.setOutputs(Array.from({ length: n }, (_, i) => rows[i] ?? {
      aoChannel: i,
      enabled: false,
      xMode: 'measured' as XMode,
      // Guess the straight wiring (ao0 → ch0, ao1 → ch1) the loopback
      // convention implies; the row is disabled, so it is only a starting
      // point, and preflight rejects a duplicate assignment if it is wrong.
      xChannel: i < nCh ? i : 0,
    }));
  });

  // ---- run state ----

  const phase = $derived($runState.phase);
  const running = $derived(phase === 'running');
  const analysing = $derived(phase === 'analysing');
  const busy = $derived(running || analysing);
  /** Why Start is refused right now (`''` ⇒ the run may start). */
  const blockReason = $derived(firstBlaError($checks));

  /** Preflight findings whose `code` belongs beside a given control. */
  const CODE_PLACEMENT: Record<string, string[]> = {
    band: ['fs', 'band'],
    design: ['design'],
    level: ['peak'],
    outputs: ['n-exc', 'x-mode', 'commanded-sync', 'ao-channels', 'x-channels'],
    responses: ['resp-channels'],
    path: ['lpf', 'output-fs', 'pretrigger'],
  };
  const msgsFor = (group: string) =>
    $checks.filter((c) => CODE_PLACEMENT[group].includes(c.code));

  // ---- formatting ----

  /** Period seconds: enough decimals to distinguish neighbouring Δf choices. */
  function fmtPeriod(s: number): string {
    if (!(s > 0)) return '—';
    return s >= 10 ? s.toFixed(2) : s.toFixed(3);
  }
  /** Wall-clock estimate: seconds under a minute, else `m min s s`. */
  function fmtDuration(s: number): string {
    if (!(s > 0)) return '—';
    if (s < 60) return `${s.toFixed(1)} s`;
    const m = Math.floor(s / 60);
    return `${m} min ${Math.round(s - 60 * m)} s`;
  }

  /**
   * The period readout, always in BOTH units plus the excited-line count —
   * "period: N = 4096 samples = 0.500 s · 993 lines". The sample count is the
   * quantity the excitation is actually defined in; the seconds are what the
   * run costs.
   */
  const periodText = $derived(
    $values.periodSamples > 0
      ? `period: N = ${$values.periodSamples} samples = ${fmtPeriod($values.periodS)} s`
        + ` · ${$values.linesCount} line${$values.linesCount === 1 ? '' : 's'}`
      : 'period: —',
  );

  /** "total: 6 × 2 × 6 periods ≈ 12.4 s" — the run's whole wall-clock cost. */
  const totalText = $derived(
    `total: ${Math.trunc($design.M)} × ${$values.nExc} × `
    + `${Math.trunc($design.tPeriods) + Math.trunc($design.P)} periods ≈ ${fmtDuration($values.totalRunS)}`,
  );

  const responsesText = $derived(
    $values.respChannels.length
      ? `responses: ${$values.respChannels.map((c) => `ch ${c}`).join(', ')}`
      : 'responses: none',
  );

  const progressText = $derived(
    `realisation ${$runState.m + 1}/${Math.trunc($design.M)} · `
    + `experiment ${$runState.e + 1}/${Math.max(1, $values.nExc)}`,
  );

  // ---- results ----

  /**
   * One verdict line per landed BLA set: the excitation's name (its x source
   * comes from the run spec, which is the geometry the RESULTS were computed
   * with — not the design's current, possibly edited, table) plus the banded
   * σ_NL vs σ_n reading of the worst response channel.
   */
  const verdicts = $derived.by(() => {
    const ids = $runState.resultSetIds;
    const spec = $runState.runSpec;
    return ids.map((setId, q) => {
      const tf = $derivedMap[setId]?.tf;
      const via = spec?.x_mode === 'commanded'
        ? 'commanded'
        : `via ch${spec?.x_channels?.[q] ?? '?'}`;
      const label = `q${q + 1} (${via})`;
      if (!tf?.sigmaNl || !tf?.sigmaN) return { setId, label, text: 'no σ data' };
      const nCols = tf.sigmaNl.shape[1] ?? 1;
      const pair = worstBlaChannel(tf.sigmaNl.re, tf.sigmaN.re, nCols);
      return { setId, label, text: summariseBlaVerdicts(blaVerdicts(tf.axis, pair.sigmaNl, pair.sigmaN)) };
    });
  });
  const showResults = $derived(phase === 'done' || $runState.resultSetIds.length > 0);

  /** Whether the last run's raw captures are currently unhidden. */
  let rawVisible = $state(false);
  // A new run lands a fresh (hidden) batch of raw sets, so the toggle goes
  // back to its "hidden" reading rather than lying about the new captures.
  $effect(() => {
    if ($runState.phase === 'running') rawVisible = false;
  });

  // ---- handlers ----

  /** Read a number input, ignoring blanks/garbage (the field keeps its value). */
  function num(e: Event): number | null {
    const v = Number((e.target as HTMLInputElement).value);
    return Number.isFinite(v) ? v : null;
  }
  const onF1 = (e: Event) => { const v = num(e); if (v != null) bla.patch({ f1Hz: v }); };
  const onF2 = (e: Event) => { const v = num(e); if (v != null) bla.patch({ f2Hz: v }); };
  const onDf = (e: Event) => { const v = num(e); if (v != null) bla.patch({ dfHz: v }); };
  const onAmp = (e: Event) => { const v = num(e); if (v != null) bla.patch({ ampRms: v }); };
  const onM = (e: Event) => { const v = num(e); if (v != null) bla.patch({ M: Math.max(2, Math.round(v)) }); };
  const onP = (e: Event) => { const v = num(e); if (v != null) bla.patch({ P: Math.max(2, Math.round(v)) }); };
  const onTrans = (e: Event) => {
    const v = num(e);
    if (v != null) bla.patch({ tPeriods: Math.max(0, Math.round(v)) });
  };

  /** Replace one excitation row (enable flag or x-source). */
  function patchRow(i: number, patch: Partial<BlaOutputRow>): void {
    bla.setOutputs($design.outputs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }
  function onRowEnable(i: number, e: Event) {
    patchRow(i, { enabled: (e.target as HTMLInputElement).checked });
  }
  /** x-source select: `commanded`, or `m<ch>` for a measured input channel. */
  function onRowSource(i: number, e: Event) {
    const v = (e.target as HTMLSelectElement).value;
    if (v === 'commanded') patchRow(i, { xMode: 'commanded', xChannel: null });
    else patchRow(i, { xMode: 'measured', xChannel: Number(v.slice(1)) });
  }
  const rowValue = (r: BlaOutputRow) =>
    (r.xMode === 'commanded' ? 'commanded' : `m${r.xChannel ?? 0}`);
  /**
   * Measured-x channels the select offers for a row: every CAPTURED input
   * channel, plus the row's own channel when it sits outside that range (a
   * design carried over from a wider capture) — otherwise the select would
   * render blank while the stored value quietly stayed out of range.
   */
  function sourceChannels(r: BlaOutputRow): number[] {
    const chs = Array.from({ length: Math.max(0, Math.trunc($settings.channelCount)) }, (_, c) => c);
    if (r.xMode === 'measured' && r.xChannel != null && !chs.includes(r.xChannel)) chs.push(r.xChannel);
    return chs;
  }

  function toggleRaw() {
    rawVisible = !rawVisible;
    bla.setRawVisible(rawVisible);
  }
</script>

<section class="ctx-card card-controls" aria-label="Nonlin stage controls">
  <div class="ctx-name">
    <span class="cn-t">Nonlin</span>
    <span class="cn-s">BLA</span>
  </div>
  <div class="ctx-body">
    <!-- ---------------- design ---------------- -->
    <div class="ctx-row" data-testid="bla-design">
      <div class="grp">
        <span class="grp-lab">test</span>
        <div class="grp-ctl">
          <input
            type="text" style="width:90px"
            title="Base name for this run's raw captures and BLA sets — level sweeps are separate runs, so name them apart"
            aria-label="test name" data-testid="bla-name"
            value={$design.testName} disabled={busy}
            onchange={(e) => bla.patch({ testName: (e.currentTarget as HTMLInputElement).value.trim() || 'bla' })}
          />
        </div>
      </div>

      <div class="grp">
        <span class="grp-lab">band (Hz)</span>
        <div class="grp-ctl">
          <input
            type="number" step="1" min="0" style="width:64px"
            aria-label="band start" data-testid="bla-f1"
            value={$design.f1Hz} onchange={onF1} disabled={busy}
          />
          <span class="ml">to</span>
          <input
            type="number" step="1" min="0" style="width:70px"
            aria-label="band end" data-testid="bla-f2"
            value={$design.f2Hz} onchange={onF2} disabled={busy}
          />
        </div>
        {#each msgsFor('band') as c (c.code + c.reason)}
          <span class="msg-err" data-testid="bla-msg">{c.reason}</span>
        {/each}
      </div>

      <div class="grp">
        <span class="grp-lab">resolution</span>
        <div class="grp-ctl">
          <span class="ml">Δf</span>
          <input
            type="number" step="any" min="0" style="width:64px"
            title="Frequency resolution; fixes the period length N = round(fs/Δf)"
            aria-label="frequency resolution" data-testid="bla-df"
            value={$design.dfHz} onchange={onDf} disabled={busy}
          />
          <span class="ml mono" data-testid="bla-period">{periodText}</span>
        </div>
        {#each msgsFor('design') as c (c.code + c.reason)}
          <span class="msg-err" data-testid="bla-msg">{c.reason}</span>
        {/each}
      </div>

      <div class="grp">
        <span class="grp-lab">level</span>
        <div class="grp-ctl">
          <input
            type="number" step="any" min="0" max={rail} style="width:64px"
            title={volts
              ? `Per-excitation RMS level in volts (device rail ±${rail.toFixed(2)} V peak)`
              : 'Per-excitation RMS level as a fraction of full scale (peak rail ±1)'}
            aria-label="excitation level" data-testid="bla-amp"
            value={$design.ampRms} onchange={onAmp} disabled={busy}
          />
          <span class="ml">{ampUnit}</span>
        </div>
        {#each msgsFor('level') as c (c.code + c.reason)}
          <span class="msg-err" data-testid="bla-msg">{c.reason}</span>
        {/each}
      </div>

      <div class="grp">
        <span class="grp-lab">averaging</span>
        <div class="grp-ctl">
          <span class="ml">M</span>
          <input
            type="number" step="1" min="2" style="width:52px"
            title="Realisations — fresh random phases each; the realisation scatter is σ_tot"
            aria-label="realisations" data-testid="bla-m"
            value={$design.M} onchange={onM} disabled={busy}
          />
          <span class="ml">P</span>
          <input
            type="number" step="1" min="2" style="width:52px"
            title="Steady-state periods per experiment; the period scatter is σ_n"
            aria-label="periods" data-testid="bla-p"
            value={$design.P} onchange={onP} disabled={busy}
          />
          <span class="ml">transient</span>
          <input
            type="number" step="1" min="0" style="width:52px"
            title="Periods played and discarded before the steady-state window"
            aria-label="transient periods" data-testid="bla-transient"
            value={$design.tPeriods} onchange={onTrans} disabled={busy}
          />
        </div>
      </div>

      <div class="grp">
        <span class="grp-lab">excitations</span>
        <div class="out-rows" data-testid="bla-outputs">
          {#each $design.outputs as row, i (row.aoChannel)}
            <div class="out-row">
              <label class="switch" title="Drive this analog output during the run">
                <input
                  type="checkbox" checked={row.enabled} disabled={busy}
                  aria-label={`drive ao${row.aoChannel}`}
                  data-testid={`bla-out-enable-${row.aoChannel}`}
                  onchange={(e) => onRowEnable(i, e)}
                />
                ao{row.aoChannel}
              </label>
              <select
                aria-label={`x source for ao${row.aoChannel}`}
                data-testid={`bla-out-source-${row.aoChannel}`}
                value={rowValue(row)} disabled={busy || !row.enabled}
                onchange={(e) => onRowSource(i, e)}
                title="Where the analysis reads this excitation from"
              >
                {#each sourceChannels(row) as c (c)}
                  <option value={`m${c}`}>
                    measure on ch {c}{c >= $settings.channelCount ? ' (not captured)' : ''}
                  </option>
                {/each}
                <option
                  value="commanded"
                  disabled={!commandedOk}
                  title={commandedOk ? 'Regenerate the drive from the seed (hardware-synced NI only)' : BLA_COMMANDED_X_REASON}
                >commanded drive</option>
              </select>
            </div>
          {/each}
        </div>
        {#if !commandedOk}
          <span class="msg-note" data-testid="bla-commanded-note" title={BLA_COMMANDED_X_REASON}>
            commanded drive needs a hardware-synced NI output
          </span>
        {/if}
        {#each msgsFor('outputs') as c (c.code + c.reason)}
          <span class="msg-err" data-testid="bla-msg">{c.reason}</span>
        {/each}
      </div>

      <div class="grp">
        <span class="grp-lab">responses · run time</span>
        <div class="col">
          <span class="ml mono" data-testid="bla-responses">{responsesText}</span>
          <span class="ml mono" data-testid="bla-total">{totalText}</span>
          {#each msgsFor('responses') as c (c.code + c.reason)}
            <span class="msg-err" data-testid="bla-msg">{c.reason}</span>
          {/each}
        </div>
      </div>
    </div>

    <!-- ---------------- run ---------------- -->
    <div class="ctx-row" data-testid="bla-run">
      <div class="grp">
        <span class="grp-lab">run</span>
        <div class="grp-ctl">
          <button
            class="btn start-btn" data-testid="bla-start"
            disabled={busy || !!blockReason}
            title={blockReason || 'Run the BLA measurement (M × n_exc captures)'}
            onclick={() => void bla.start()}
          >Start</button>
          {#if busy}
            <button class="btn cancel-btn" data-testid="bla-cancel" onclick={() => bla.cancel()}
              title="Stop after the capture in flight completes">Cancel</button>
          {/if}
          {#if running}
            <span class="ml mono" data-testid="bla-progress">{progressText}</span>
          {:else if analysing}
            <span class="ml mono" data-testid="bla-analysing">computing BLA…</span>
          {/if}
        </div>
        {#if blockReason && !busy}
          <span class="msg-err" data-testid="bla-blocked">{blockReason}</span>
        {/if}
      </div>

      {#if msgsFor('path').length}
        <div class="grp">
          <span class="grp-lab">capture path</span>
          <div class="col">
            {#each msgsFor('path') as c (c.code + c.reason)}
              <span class={c.ok ? 'msg-note' : 'msg-err'} data-testid="bla-msg">{c.reason}</span>
            {/each}
          </div>
        </div>
      {/if}

      {#if $runState.notes.length || phase === 'cancelled' || $runState.error}
        <div class="grp">
          <!-- One group carries both the advisories the run acted on and a
               failure, so it names whichever is the more serious. -->
          <span class="grp-lab">{$runState.error ? 'run failed' : 'notes'}</span>
          <div class="col">
            {#each $runState.notes as note (note)}
              <span class="msg-note" data-testid="bla-note">{note}</span>
            {/each}
            {#if phase === 'cancelled'}
              <span class="msg-note" data-testid="bla-cancelled">
                Run cancelled — the captures already taken are kept.
              </span>
            {/if}
            {#if $runState.error}
              <span class="msg-err" role="alert" data-testid="bla-error">{$runState.error}</span>
            {/if}
          </div>
        </div>
      {/if}
    </div>

    <!-- ---------------- results ---------------- -->
    {#if showResults}
      <div class="ctx-row" data-testid="bla-results">
        <div class="grp">
          <span class="grp-lab">verdict</span>
          <div class="col">
            {#each verdicts as v (v.setId)}
              <span class="verdict" data-testid="bla-verdict">
                <strong>{v.label}:</strong> {v.text}
              </span>
            {/each}
          </div>
        </div>
        <div class="grp">
          <span class="grp-lab">captures</span>
          <div class="grp-ctl">
            <button class="btn" data-testid="bla-show-raw" onclick={toggleRaw}
              title="Show or hide this run's raw time captures in the tray and legend"
            >{rawVisible ? 'hide raw captures' : 'show raw captures'}</button>
            <button class="btn" data-testid="bla-new-run" onclick={() => bla.reset()}
              title="Clear the run state and keep the design for another run">new run</button>
          </div>
        </div>
      </div>
    {/if}
  </div>
  <div class="ctx-primary">
    <div class="run-count" data-testid="bla-status">
      {#if running}
        {$runState.rawSetIds.length}/{Math.trunc($design.M) * Math.max(1, $values.nExc)} captures
      {:else if analysing}
        analysing…
      {:else if phase === 'done'}
        {$runState.resultSetIds.length} BLA set{$runState.resultSetIds.length === 1 ? '' : 's'}
      {:else}
        {Math.trunc($design.M) * Math.max(1, $values.nExc)} captures planned
      {/if}
    </div>
  </div>
</section>

<style>
  /* Vertical stack inside a group (message lists, verdict lines) — the shared
     .grp-ctl is a fixed-height horizontal strip, which these outgrow. */
  .col {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .out-rows {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .out-row {
    display: flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
  }
  .out-row :global(select) {
    max-width: 150px;
  }
  /* Preflight messages: the app's error/muted colours, but WRAPPING — a
     refusal has to be readable, and .ctx-err truncates to one line. */
  .msg-err,
  .msg-note,
  .verdict {
    font-size: 10.5px;
    line-height: 1.35;
    max-width: 360px;
    white-space: normal;
  }
  .msg-err {
    color: var(--danger);
  }
  .msg-note {
    color: var(--muted);
    font-style: italic;
  }
  .verdict {
    color: var(--text);
    font-size: 11px;
    max-width: 520px;
  }
  .start-btn {
    background: var(--green) !important;
    border-color: var(--green) !important;
    color: #fff !important;
    font-weight: 600 !important;
  }
  .start-btn:hover:not(:disabled) {
    background: var(--green-hover) !important;
  }
  .start-btn:disabled {
    opacity: 0.55;
  }
  .cancel-btn {
    background: var(--control-bg) !important;
    border-color: var(--danger-strong) !important;
    color: var(--danger-strong) !important;
    font-weight: 600 !important;
  }
  .cancel-btn:hover {
    background: var(--danger-soft) !important;
  }
  .run-count {
    font-size: 12px;
    color: var(--muted);
    white-space: nowrap;
  }
</style>
