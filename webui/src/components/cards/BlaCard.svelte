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
   *    excitation (see `lib/analysis/blaVerdict.ts`), a self-gated "σ lines"
   *    toggle (review item 5 — the TF card's own toggle is unreachable from
   *    here, since the results render over the tf VIEW while the active
   *    STAGE stays 'bla'; this drives the identical `viewState.setBlaSigma`),
   *    a "show raw captures" toggle (the M×n raw sets land hidden) and
   *    "new run".
   *
   * The card OWNS no run state: everything reactive comes from the BLA store
   * (`design`, `values`, `checks`, `state`), which in turn reads the live
   * acquisition settings. Every failing check is rendered next to the control
   * its `code` points at rather than in one lump, so a refusal is legible
   * where the fix is.
   */
  import type { BlaStore, BlaOutputRow, BlaCheckCode, XMode } from '../../lib/stores/bla';
  import {
    commandedXSupported, excitationLabel, firstBlaError, outputRailFor, BLA_COMMANDED_X_REASON,
  } from '../../lib/stores/bla';
  import type { AcquireStore } from '../../lib/stores/acquire';
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';
  import type { ViewState } from '../../lib/stores/viewstate';
  import { outputDevices } from '../../lib/audio/provider';
  import { blaVerdicts, summariseBlaVerdicts, worstBlaChannel } from '../../lib/analysis/blaVerdict';

  let {
    bla,
    acquire,
    actions,
    selection,
    viewState,
  }: {
    bla: BlaStore;
    acquire: AcquireStore;
    actions: Actions;
    /** Read-only here: the raw-capture toggle reads its state from the tray. */
    selection: Selection;
    /**
     * σ_NL/σ_n overlay toggle (review item 5): the TF card's "σ lines"
     * switch is unreachable from here — the Nonlin stage shows results over
     * the SAME tf view, but the active STAGE stays 'bla', so a user reading
     * the verdict has no path to the toggle without first switching stages.
     * This card offers the same switch, driving the identical
     * `viewState.setBlaSigma` store write.
     */
    viewState: ViewState;
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
  const setsView = $derived(selection.setsView);

  // ---- σ overlay toggle (review item 5, mirrors TFCard's control) ----
  const current = $derived(viewState.current);
  const blaSigma = $derived($current.blaSigma);
  /** Self-gated exactly like the TF card's toggle: noise without σ data. */
  const anySigma = $derived(
    $setsView.some((s) => !s.allOff
      && (($derivedMap[s.id]?.tf?.sigmaNl) || ($derivedMap[s.id]?.tf?.sigmaN))),
  );

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
  const rail = $derived(outputRailFor($kind, $bridgeConfig, $settings.deviceId));

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

  /**
   * Which control each preflight `code` reports next to. `as const` keeps the
   * literal members visible to the type system so {@link _EVERY_CODE_PLACED}
   * below can assert — at COMPILE time — that every member of the closed
   * {@link BlaCheckCode} union has a home here. Adding a code to the preflight
   * without listing it therefore fails `npm run check`; {@link unplacedMsgs} is
   * the belt-and-braces runtime net for anything that still slips through.
   */
  const CODE_PLACEMENT = {
    band: ['fs', 'band'],
    design: ['design'],
    level: ['peak'],
    outputs: ['n-exc', 'x-mode', 'commanded-sync', 'ao-channels', 'ao-prefix', 'x-channels'],
    responses: ['resp-channels'],
    path: ['lpf', 'output-fs', 'pretrigger'],
  } as const satisfies Record<string, readonly BlaCheckCode[]>;
  type PlacementGroup = keyof typeof CODE_PLACEMENT;
  /** Every code listed above, as a union of literals. */
  type PlacedCode = (typeof CODE_PLACEMENT)[PlacementGroup][number];
  /**
   * Compile-time exhaustiveness: resolves to `true` only while no
   * {@link BlaCheckCode} is missing from {@link CODE_PLACEMENT}; an unplaced
   * code makes the type `false` and the initialiser stops type-checking, naming
   * the offending code in the error.
   */
  const _EVERY_CODE_PLACED: [Exclude<BlaCheckCode, PlacedCode>] extends [never] ? true : false = true;
  void _EVERY_CODE_PLACED;
  const PLACED_CODES = new Set<string>(Object.values(CODE_PLACEMENT).flat());
  const msgsFor = (group: PlacementGroup) =>
    $checks.filter((c) => (CODE_PLACEMENT[group] as readonly BlaCheckCode[]).includes(c.code));
  /** Findings with no home in {@link CODE_PLACEMENT} — shown in the run group. */
  const unplacedMsgs = $derived($checks.filter((c) => !PLACED_CODES.has(c.code)));

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
      // The geometry comes from the RUN SPEC (what the results were computed
      // with), never from the design's current — possibly edited — table.
      const label = excitationLabel(q, spec?.x_mode ?? 'measured', spec?.x_channels);
      if (!tf?.sigmaNl || !tf?.sigmaN) return { setId, label, text: 'no σ data' };
      const nCols = tf.sigmaNl.shape[1] ?? 1;
      const pair = worstBlaChannel(tf.sigmaNl.re, tf.sigmaN.re, nCols);
      return { setId, label, text: summariseBlaVerdicts(blaVerdicts(tf.axis, pair.sigmaNl, pair.sigmaN)) };
    });
  });

  /**
   * Whether the last run's raw captures are showing, read from the TRAY rather
   * than remembered locally — the user can hide or show those sets from the
   * legend/tray at any time, and a toggle that tracked its own last click
   * would then offer to "show" what is already on screen.
   */
  const rawVisible = $derived.by(() => {
    const ids = new Set($runState.rawSetIds);
    if (!ids.size) return false;
    return $setsView.some((s) => ids.has(s.id) && !s.allOff);
  });

  // ---- handlers ----

  /**
   * Read a number input. A BLANK or unparseable field returns `null` and the
   * design keeps its current value — `Number('')` is `0`, so reading the raw
   * value would silently rewrite f1 (or Δf, or the level) to zero the moment a
   * field is cleared for retyping. Mirrors AcquireCard's trim-then-parse.
   */
  function readNum(e: Event): number | null {
    const raw = (e.target as HTMLInputElement).value.trim();
    if (raw === '') return null;
    const v = Number(raw);
    return Number.isFinite(v) ? v : null;
  }
  const onF1 = (e: Event) => { const v = readNum(e); if (v != null) bla.patch({ f1Hz: v }); };
  const onF2 = (e: Event) => { const v = readNum(e); if (v != null) bla.patch({ f2Hz: v }); };
  const onDf = (e: Event) => { const v = readNum(e); if (v != null) bla.patch({ dfHz: v }); };
  const onAmp = (e: Event) => { const v = readNum(e); if (v != null) bla.patch({ ampRms: v }); };
  const onM = (e: Event) => { const v = readNum(e); if (v != null) bla.patch({ M: Math.max(2, Math.round(v)) }); };
  const onP = (e: Event) => { const v = readNum(e); if (v != null) bla.patch({ P: Math.max(2, Math.round(v)) }); };
  const onTrans = (e: Event) => {
    const v = readNum(e);
    if (v != null) bla.patch({ tPeriods: Math.max(0, Math.round(v)) });
  };
  /** Test name; a blank field keeps the previous name rather than inventing one. */
  const onTestName = (e: Event) => {
    const raw = (e.target as HTMLInputElement).value.trim();
    if (raw !== '') bla.patch({ testName: raw });
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

  const toggleRaw = () => bla.setRawVisible(!rawVisible);
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
            value={$design.testName} onchange={onTestName} disabled={busy}
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
          <span class="msg-err" role="alert" data-testid="bla-msg">{c.reason}</span>
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
          <span class="msg-err" role="alert" data-testid="bla-msg">{c.reason}</span>
        {/each}
      </div>

      <div class="grp">
        <span class="grp-lab">level</span>
        <div class="grp-ctl">
          <!--
            No `max` here: the rail is a PEAK and this field is an RMS level,
            so the legal maximum depends on the realisation's crest factor
            (≥ √2, and higher for a random-phase multisine). Preflight's peak
            guard generates every (m, e) waveform and owns that judgement; a
            max attribute could only be wrong in one direction or the other.
          -->
          <input
            type="number" step="any" min="0" style="width:64px"
            title={volts
              ? `Per-excitation RMS level in volts (output rail ±${rail.toFixed(2)} V peak)`
              : 'Per-excitation RMS level as a fraction of full scale (peak rail ±1)'}
            aria-label="excitation level" data-testid="bla-amp"
            value={$design.ampRms} onchange={onAmp} disabled={busy}
          />
          <span class="ml">{ampUnit}</span>
        </div>
        {#each msgsFor('level') as c (c.code + c.reason)}
          <span class="msg-err" role="alert" data-testid="bla-msg">{c.reason}</span>
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
        <!-- Only worth saying on the bridge, where an NI output is reachable
             at all; a browser user cannot act on it, so it would be permanent
             noise. The disabled option still carries the full reason. -->
        {#if !commandedOk && $kind === 'bridge'}
          <span class="msg-note" data-testid="bla-commanded-note" title={BLA_COMMANDED_X_REASON}>
            commanded drive needs a hardware-synced NI output
          </span>
        {/if}
        {#each msgsFor('outputs') as c (c.code + c.reason)}
          <span class="msg-err" role="alert" data-testid="bla-msg">{c.reason}</span>
        {/each}
      </div>

      <div class="grp">
        <span class="grp-lab">responses · run time</span>
        <div class="col">
          <span class="ml mono" data-testid="bla-responses">{responsesText}</span>
          <span class="ml mono" data-testid="bla-total">{totalText}</span>
          {#each msgsFor('responses') as c (c.code + c.reason)}
            <span class="msg-err" role="alert" data-testid="bla-msg">{c.reason}</span>
          {/each}
        </div>
      </div>
    </div>

    <!-- ---------------- run ---------------- -->
    <div class="ctx-row" data-testid="bla-run">
      <div class="grp">
        <span class="grp-lab">run</span>
        <div class="grp-ctl">
          <!-- A disabled .btn has pointer-events: none, so a title on it would
               never be seen; the refusal reads as visible text below instead. -->
          <button
            class="btn green" data-testid="bla-start"
            disabled={busy || !!blockReason}
            title={busy || blockReason ? undefined : 'Run the BLA measurement (M × n_exc captures)'}
            onclick={() => void bla.start()}
          >Start</button>
          <!-- Only while CAPTURING: `cancel()` is a flag the capture loop
               reads, so during 'analysing' (one worker call) it would do
               nothing — the "computing BLA…" readout covers that state. -->
          {#if running}
            <button class="btn danger-o" data-testid="bla-cancel" onclick={() => bla.cancel()}
              title="Stop after the capture in flight completes">Cancel</button>
            <span class="ml mono" data-testid="bla-progress">{progressText}</span>
          {:else if analysing}
            <span class="ml mono" data-testid="bla-analysing">computing BLA…</span>
          {/if}
        </div>
        {#if blockReason && !busy}
          <span class="msg-err" data-testid="bla-blocked">{blockReason}</span>
        {/if}
        <!-- Safety net: a finding whose code has no home in CODE_PLACEMENT
             still reaches the user here rather than disappearing. -->
        {#each unplacedMsgs as c (c.code + c.reason)}
          <span class={c.ok ? 'msg-note' : 'msg-err'} role="alert" data-testid="bla-msg">{c.reason}</span>
        {/each}
      </div>

      {#if msgsFor('path').length}
        <div class="grp">
          <span class="grp-lab">capture path</span>
          <div class="col">
            {#each msgsFor('path') as c (c.code + c.reason)}
              <span class={c.ok ? "msg-note" : "msg-err"} role="alert" data-testid="bla-msg">{c.reason}</span>
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

    <!-- ---------------- results ----------------
      Gated on what EXISTS, not on the phase: a cancelled or failed run still
      left hidden raw captures in the tray, and this is the only control that
      reveals them. Verdicts and captures gate separately for the same reason.
    -->
    {#if $runState.resultSetIds.length || $runState.rawSetIds.length}
      <div class="ctx-row" data-testid="bla-results">
        {#if $runState.resultSetIds.length}
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
        {/if}
        {#if anySigma}
          <div class="grp">
            <span class="grp-lab">σ lines</span>
            <div class="grp-ctl">
              <!-- Same viewstate write as the TF card's toggle (which keeps
                   its own `bla-sigma-toggle` testid) — this is just a second
                   reachable control for the same state, so the two never
                   drift out of sync. -->
              <label class="switch"><input type="checkbox" checked={blaSigma}
                onchange={(e) => viewState.setBlaSigma(e.currentTarget.checked)}
                aria-label="σ_NL/σ_n overlay" data-testid="bla-sigma-toggle-card" /></label>
            </div>
          </div>
        {/if}
        <div class="grp">
          <span class="grp-lab">captures</span>
          <div class="grp-ctl">
            {#if $runState.rawSetIds.length}
              <button class="btn" data-testid="bla-show-raw" onclick={toggleRaw}
                title="Show or hide this run's raw time captures in the tray and legend"
              >{rawVisible ? 'hide raw captures' : 'show raw captures'}</button>
            {/if}
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
  .out-row select {
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
  /* The green Start and the outlined Cancel are the SHARED `.btn.green` /
     `.btn.danger-o` variants in app.css (identical to Acquire's pair). */
  .run-count {
    font-size: 12px;
    color: var(--muted);
    white-space: nowrap;
  }
</style>
