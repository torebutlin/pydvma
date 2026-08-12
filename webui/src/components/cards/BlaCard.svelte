<script lang="ts">
  /**
   * Nonlin-stage context card — the user-facing surface of the Schoukens BLA
   * workflow (design: `dev/plans/2026-08-10-schoukens-bla-design.md`, "UX — a
   * new Nonlin stage").
   *
   * Three groups, top to bottom:
   *
   *  - **design** (`bla-design`) — band f1–f2, frequency resolution Δf with the
   *    period as a SECOND, equal-weight input (round-11 P6: editing either
   *    resolves the other through the sample count N, which is the primitive
   *    — the excitation is defined in samples so periodicity survives clock
   *    coercion — while seconds is what the run actually costs), excitation
   *    level, the M / P / transient counts, the per-AO-channel excitation
   *    table with its x-source choice, the response-channel readout, the
   *    run-length breakdown, and the note that the run drives the capture
   *    length itself.
   *  - **run** (`bla-run`) — the replace/keep choice for a previous run's
   *    sets, Start (disabled, with the reason, whenever preflight refuses),
   *    an `M × n_exc` progress GRID with a `capture 3/12 · ~9 s left`
   *    readout, "stop after this capture", and the advisory notes the run
   *    acted on (e.g. the pretrigger auto-disarm).
   *  - **results** (`bla-results`) — one plain-English verdict line per
   *    excitation (see `lib/analysis/blaVerdict.ts`), a self-gated "σ lines"
   *    toggle (review item 5 — the TF card's own toggle is unreachable from
   *    here, since the results render over the tf VIEW while the active
   *    STAGE stays 'bla'; this drives the identical `viewState.setBlaSigma`),
   *    WITH an inline dashed-line key and a one-line explainer of what σ_NL /
   *    σ_n are, a "show raw captures" toggle (the M×n raw sets land hidden)
   *    and "new run".
   *
   * The `.ctx-primary` slot carries the run's TOTAL WALL-CLOCK COST as the
   * card's headline number (round-11 P6 — Tore: "there should be a clear
   * number showing the total time that the experiment will take"); during a
   * run it becomes the live remaining estimate.
   *
   * The card OWNS no run state: everything reactive comes from the BLA store
   * (`design`, `values`, `checks`, `state`), which in turn reads the live
   * acquisition settings. Every failing check is rendered next to the control
   * its `code` points at rather than in one lump, so a refusal is legible
   * where the fix is.
   */
  import type {
    BlaStore, BlaOutputRow, BlaCheckCode, XMode, BlaCapture, BlaRunMode,
  } from '../../lib/stores/bla';
  import {
    commandedXSupported, excitationLabel, firstBlaError, outputRailFor,
    blaRemainingS, roundForPeriodBox, BLA_COMMANDED_X_REASON,
  } from '../../lib/stores/bla';
  import type { AcquireStore } from '../../lib/stores/acquire';
  import type { Actions } from '../../lib/analysis/actions';
  import type { Selection } from '../../lib/stores/selection';
  import { LINE_PALETTE } from '../../lib/stores/selection';
  import type { ViewState } from '../../lib/stores/viewstate';
  import type { Toasts } from '../../lib/stores/toast';
  import { outputDevices } from '../../lib/audio/provider';
  import { blaVerdicts, summariseBlaVerdicts, worstBlaChannel } from '../../lib/analysis/blaVerdict';
  import Segmented from '../Segmented.svelte';

  let {
    bla,
    acquire,
    actions,
    selection,
    viewState,
    toasts,
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
    /**
     * Shared toast queue. "new run" hands the previous run's raw captures
     * back to the tray and then forgets them, which is invisible unless it is
     * said out loud — so it is said out loud here.
     */
    toasts: Toasts;
  } = $props();

  const design = $derived(bla.design);
  const values = $derived(bla.values);
  const checks = $derived(bla.checks);
  const runState = $derived(bla.state);
  const runMode = $derived(bla.runMode);
  const hasPreviousRun = $derived(bla.hasPreviousRun);

  const settings = $derived(acquire.settings);
  /** Live seconds into the capture in flight — drives the running cell's fill. */
  const elapsed = $derived(acquire.elapsed);
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

  /** Wall-clock estimate: seconds under a minute, else `m min s s`. */
  function fmtDuration(s: number): string {
    if (!(s > 0)) return '—';
    if (s < 60) return `${s.toFixed(1)} s`;
    const m = Math.floor(s / 60);
    return `${m} min ${Math.round(s - 60 * m)} s`;
  }

  /** Per-capture length: short enough to read, precise enough to add up. */
  function fmtCaptureS(s: number): string {
    if (!(s > 0)) return '—';
    return s >= 10 ? `${s.toFixed(1)} s` : `${s.toFixed(2)} s`;
  }

  /**
   * The value shown in the period BOX. Derived from `N` (never from the raw
   * seconds) and rounded to a length that reads the same `N` back, so
   * committing the field without editing it can never move the design — see
   * `roundForPeriodBox`.
   */
  const periodBoxS = $derived(
    $values.periodSamples > 0 ? roundForPeriodBox($values.periodS) : '',
  );

  /**
   * What the linked pair RESOLVED to, in the primitive the excitation is
   * actually defined in — "N = 4096 samples · 993 lines". The two boxes above
   * carry the units the user thinks in; this is the sample count that makes
   * the periodicity exact.
   */
  const periodText = $derived(
    $values.periodSamples > 0
      ? `N = ${$values.periodSamples} samples · ${$values.linesCount} line${$values.linesCount === 1 ? '' : 's'}`
      : 'N = —',
  );

  /** Captures the design plans (`M × n_exc`). */
  const plannedCount = $derived(Math.max(0, Math.trunc($design.M)) * Math.max(1, $values.nExc));

  /** "6 × 2 captures × (2 + 4) periods" — where the total time comes from. */
  const totalText = $derived(
    `${Math.trunc($design.M)} realisation${Math.trunc($design.M) === 1 ? '' : 's'} × `
    + `${$values.nExc} excitation${$values.nExc === 1 ? '' : 's'} × `
    + `${Math.trunc($design.tPeriods) + Math.trunc($design.P)} periods `
    + `(${Math.trunc($design.tPeriods)} transient + ${Math.trunc($design.P)} steady)`,
  );

  const responsesText = $derived(
    $values.respChannels.length
      ? `responses: ${$values.respChannels.map((c) => `ch ${c}`).join(', ')}`
      : 'responses: none',
  );

  // ---- progress grid ----

  /**
   * The grid as rows of cells, one row per realisation — EXCEPT for the
   * common SISO case (`n_exc === 1`), where one cell per row would be a tall
   * one-wide column taking a card's full height to say what a single strip
   * says better. There the whole run is one row and the grid reads as a
   * segmented progress bar.
   */
  const gridRows = $derived.by(() => {
    const cells = $runState.captures;
    if (cells.every((c) => c.e === 0)) return cells.length ? [cells] : [];
    const rows: BlaCapture[][] = [];
    for (const c of cells) (rows[c.m] ??= []).push(c);
    return rows.filter((r) => r && r.length);
  });
  const doneCount = $derived($runState.captures.filter((c) => c.status === 'done').length);
  const inFlight = $derived($runState.captures.some((c) => c.status === 'running'));
  /** 1-based index of the capture in flight (or of the last one that ran). */
  const captureIndex = $derived(
    Math.min($runState.captures.length, doneCount + (inFlight ? 1 : 0)),
  );
  /** How full the running cell is drawn — the live capture's own clock. */
  const fillFrac = $derived(
    $values.captureS > 0 ? Math.max(0, Math.min(1, $elapsed / $values.captureS)) : 0,
  );
  const remainingS = $derived(blaRemainingS($runState.captures, $values.captureS, $elapsed));
  /** "capture 3/12 · ~9 s left" — position AND cost of what is left. */
  const progressText = $derived(
    `capture ${captureIndex}/${$runState.captures.length} · ~${fmtDuration(remainingS)} left`,
  );

  // ---- run semantics (replace vs keep both) ----

  const RUN_MODES: { value: BlaRunMode; label: string; title: string; testid: string }[] = [
    {
      value: 'replace',
      label: 'replace previous',
      title: 'Remove the last run\'s raw captures and BLA sets before this run starts '
        + '(one-click Undo offered afterwards)',
      testid: 'bla-run-mode-replace',
    },
    {
      value: 'keep',
      label: 'keep both',
      title: 'Keep the last run and name this one apart (bla#2 …) so the two can be '
        + 'compared — the usual choice for a level sweep',
      testid: 'bla-run-mode-keep',
    },
  ];

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
  // The two LINKED period fields (round-11 P6). Both route through the store's
  // single resolver, so whichever one the user edits, the other follows and
  // both describe the same whole-sample period.
  const onDf = (e: Event) => { const v = readNum(e); if (v != null) bla.setPeriod('df', v); };
  const onPeriod = (e: Event) => { const v = readNum(e); if (v != null) bla.setPeriod('period', v); };
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

  /**
   * "new run" hands the raw captures back (unhidden) and forgets the run. That
   * is deliberate — see `bla.reset()` — but from the card it looks like
   * nothing happened except the results group vanishing, so say what moved.
   */
  function onNewRun(): void {
    const n = $runState.rawSetIds.length;
    bla.reset();
    toasts.push(
      n
        ? `Run cleared. Its ${n} raw capture${n === 1 ? '' : 's'} and any BLA sets stay in the tray `
          + `(the captures are now shown) — start again to add another run.`
        : 'Run cleared — the design is kept.',
      { level: 'info' },
    );
  }

  // ---- σ key ----

  /**
   * The σ_NL swatch's colour. σ_NL draws in ITS OWN line's colour (model.ts),
   * so the key shows the colour of the first BLA line actually on screen
   * rather than a generic accent — a key that matched nothing would be worse
   * than none. Falls back to the palette head before any result lands.
   */
  const sigmaNlColor = $derived(
    (($runState.resultSetIds.length
      ? selection.lineColor($runState.resultSetIds[0], 0)
      : undefined) ?? LINE_PALETTE[0]),
  );
  /** σ_n's neutral grey — the literal `model.ts` uses for the noise line. */
  const SIGMA_N_COLOR = '#6b7280';
  /** Where the full explanation lives (offline: the link simply won't load). */
  const NONLIN_DOCS_URL = 'https://torebutlin.github.io/pydvma/web-logger/nonlin/';
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

      <!--
        RESOLUTION / PERIOD — two boxes of equal weight for ONE quantity
        (round-11 P6). Δf alone hid the fact that it was setting the
        multisine's period, which is the number that decides how long the run
        takes; both are editable and both carry their unit in the markup, not
        only in a tooltip.
      -->
      <div class="grp">
        <span class="grp-lab">resolution / period</span>
        <div class="grp-ctl">
          <span class="ml">Δf</span>
          <input
            type="number" step="any" min="0" style="width:64px"
            title="Frequency resolution. Linked to the period: N = round(fs/Δf) samples, T = N/fs"
            aria-label="frequency resolution" data-testid="bla-df"
            value={$design.dfHz} onchange={onDf} disabled={busy}
          />
          <span class="ml unit">Hz</span>
          <span class="ml link-eq" aria-hidden="true">=</span>
          <span class="ml">T</span>
          <input
            type="number" step="any" min="0" style="width:72px"
            title="Period length in seconds. Linked to Δf: N = round(T·fs) samples, Δf = fs/N"
            aria-label="period seconds" data-testid="bla-period-s"
            value={periodBoxS} onchange={onPeriod} disabled={busy}
          />
          <span class="ml unit">s</span>
        </div>
        <span class="ml mono sub" data-testid="bla-period">{periodText}</span>
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
        <span class="grp-lab">responses · run length</span>
        <div class="col">
          <span class="ml mono" data-testid="bla-responses">{responsesText}</span>
          <!-- The headline total lives in the primary slot; this is where the
               number COMES FROM, so a user who wants a shorter run can see
               which factor to cut. -->
          <span class="ml mono" data-testid="bla-total">{totalText}</span>
          <!-- The run overrides the Acquire card's capture length for its own
               captures and puts the user's value back afterwards. It used to
               do that silently, which is a surprising thing to discover by
               watching a duration field change on its own. -->
          <span class="msg-note" data-testid="bla-duration-note">
            Each capture runs for {fmtCaptureS($values.captureS)}, set by the design — the run
            overrides the Acquire duration while it runs and restores it afterwards.
          </span>
          {#each msgsFor('responses') as c (c.code + c.reason)}
            <span class="msg-err" role="alert" data-testid="bla-msg">{c.reason}</span>
          {/each}
        </div>
      </div>
    </div>

    <!-- ---------------- run ---------------- -->
    <div class="ctx-row" data-testid="bla-run">
      <!--
        PREVIOUS RUN (round-11 P6) — shown only when there is one to act on,
        and read at Start. Default 'replace' because the common case is
        iterating on a design; 'keep both' is the level-sweep case, and it
        renames the new run rather than letting two runs share byte-identical
        set names.

        Hidden while BUSY: the run in flight lands its sets as it goes, so
        `hasPreviousRun` goes true a second into the very first run — and a
        control captioned "the last run's captures are removed when this one
        starts" is at best noise, at worst alarming, while that run is the
        one filling the grid.
      -->
      {#if $hasPreviousRun && !busy}
        <div class="grp" data-testid="bla-prev-run">
          <span class="grp-lab">previous run</span>
          <div class="grp-ctl">
            <Segmented
              options={RUN_MODES}
              value={$runMode}
              onchange={(v) => runMode.set(v)}
              ariaLabel="what to do with the previous run"
              testid="bla-run-mode"
            />
          </div>
          <span class="msg-note">
            {$runMode === 'replace'
              ? 'The last run\'s captures and BLA sets are removed when this one starts (Undo offered).'
              : 'The last run stays; this one is named apart so both can be compared.'}
          </span>
        </div>
      {/if}

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
               nothing — the "computing BLA…" readout covers that state. The
               label says what the button DOES: the capture in flight always
               completes (a half-played multisine is a useless set). -->
          {#if running}
            <button class="btn danger-o" data-testid="bla-cancel" onclick={() => bla.cancel()}
              title="The capture in flight completes; the run stops before the next one"
            >stop after this capture</button>
            <span class="ml mono" data-testid="bla-progress">{progressText}</span>
          {:else if analysing}
            <span class="ml mono" data-testid="bla-analysing">computing BLA…</span>
          {/if}
        </div>
        <!--
          PROGRESS GRID — one row per realisation, one cell per excitation.
          Pending cells are outlines, the cell in flight fills from the live
          capture clock, done cells are solid, so "how far in am I" is one
          glance rather than an arithmetic problem. Kept up after a cancel so
          the user can see exactly which captures they have.
        -->
        {#if $runState.captures.length && (busy || phase === 'cancelled')}
          <div
            class="cap-grid" data-testid="bla-grid"
            role="img"
            aria-label={`capture progress: ${doneCount} of ${$runState.captures.length} done`}
          >
            {#each gridRows as row, m (m)}
              <div class="cap-row">
                {#each row as cell (`${cell.m}:${cell.e}`)}
                  <span
                    class="cap-cell {cell.status}"
                    title={`realisation ${cell.m + 1}, excitation ${cell.e + 1} — ${cell.status}`}
                  >
                    {#if cell.status === 'running'}
                      <span class="cap-fill" style="width:{(fillFrac * 100).toFixed(1)}%"></span>
                    {/if}
                  </span>
                {/each}
              </div>
            {/each}
          </div>
        {/if}
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
              <!--
                What the reader is actually looking at, in one line (round-11
                P6: "no idea… what plots were showing, or what all the new data
                chans were"). Every clause here is load-bearing: which line is
                which, that the σ values are per-realisation, and the √M step
                to the BLA's own error bar.
              -->
              <span class="explain" data-testid="bla-explain">
                Each BLA set is the best linear fit for one excitation; the dashed σ_NL is
                nonlinear distortion and σ_n is noise, in the TF's own units, per realisation
                — divide by √M for the error on the mean.
                <a href={NONLIN_DOCS_URL} target="_blank" rel="noopener noreferrer"
                  data-testid="bla-docs-link">read more</a>
              </span>
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
              <!--
                A KEY, because the σ lines carry no legend entry: the legend is
                built from the view's set/channel entries and the σ overlays
                are extra lines attached to a channel, not channels of their
                own. Rather than reshape the legend model for two annotation
                lines, the card says which dash is which — and draws the σ_NL
                swatch in the colour it actually has on screen.
              -->
              <span class="sig-key" data-testid="bla-sigma-key">
                <svg width="20" height="7" viewBox="0 0 20 7" aria-hidden="true">
                  <line x1="0" y1="3.5" x2="20" y2="3.5" stroke={sigmaNlColor}
                    stroke-width="1.4" stroke-dasharray="4 3" opacity="0.7" />
                </svg>
                σ_NL (line colour)
                <svg width="20" height="7" viewBox="0 0 20 7" aria-hidden="true">
                  <line x1="0" y1="3.5" x2="20" y2="3.5" stroke={SIGMA_N_COLOR}
                    stroke-width="1.4" stroke-dasharray="4 3" />
                </svg>
                σ_n (grey)
              </span>
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
            <button class="btn" data-testid="bla-new-run" onclick={onNewRun}
              title="Clear the run state and keep the design for another run — the landed sets stay in the tray"
            >new run</button>
          </div>
        </div>
      </div>
    {/if}
  </div>
  <div class="ctx-primary">
    <!--
      THE HEADLINE. Before P6 this slot showed a capture COUNT while the total
      wall-clock time — the number that decides whether a design is worth
      pressing Start on — sat as the second mono line of a readout at the
      bottom of the design row. The count is still here; it is now the
      supporting half of the sentence rather than the whole of it.
    -->
    <div class="run-headline" data-testid="bla-status">
      {#if running}
        <span class="hl-big">~{fmtDuration(remainingS)} left</span>
        <span class="hl-sub">{doneCount}/{$runState.captures.length} captures done</span>
      {:else if analysing}
        <span class="hl-big">analysing…</span>
        <span class="hl-sub">computing BLA from {$runState.rawSetIds.length} captures</span>
      {:else if phase === 'done'}
        <span class="hl-big">{$runState.resultSetIds.length} BLA
          set{$runState.resultSetIds.length === 1 ? '' : 's'}</span>
        <span class="hl-sub">from {$runState.rawSetIds.length} captures</span>
      {:else}
        <span class="hl-big" data-testid="bla-total-time">≈ {fmtDuration($values.totalRunS)}</span>
        <span class="hl-sub">
          {plannedCount} capture{plannedCount === 1 ? '' : 's'} × {fmtCaptureS($values.captureS)}
        </span>
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
  /* The one-line σ explainer + docs link: readable prose, not a status note. */
  .explain {
    font-size: 10.5px;
    line-height: 1.4;
    color: var(--muted);
    max-width: 520px;
    white-space: normal;
  }
  .explain a {
    color: var(--blue);
  }
  /* Unit suffixes on the linked Δf / T boxes. Visible at all times: the units
     were previously only in a tooltip, and a period in seconds sitting next to
     a resolution in hertz is exactly where a missing unit costs an hour. */
  .unit {
    color: var(--muted);
    font-size: 10.5px;
  }
  /* The `=` between the two linked boxes — they are one quantity in two
     currencies, not two independent settings. */
  .link-eq {
    color: var(--muted-2);
  }
  /* The resolved sample count, under its two input boxes. */
  .sub {
    font-size: 10.5px;
    color: var(--muted);
  }
  /* σ key: two dashed swatches drawn with the SAME dash pattern the plot uses,
     so the key reads as a sample of the line rather than a decoration. */
  .sig-key {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    color: var(--muted);
    white-space: nowrap;
  }
  .sig-key svg {
    flex: 0 0 auto;
  }
  /* ---- progress grid ---- */
  .cap-grid {
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-top: 3px;
  }
  .cap-row {
    display: flex;
    gap: 2px;
  }
  .cap-cell {
    position: relative;
    width: 14px;
    height: 8px;
    border: 1px solid var(--border-strong);
    border-radius: 2px;
    background: var(--surface-2);
    overflow: hidden;
  }
  .cap-cell.done {
    background: var(--green);
    border-color: var(--green);
  }
  /* The in-flight cell fills left-to-right from the live capture clock; the
     transition keeps the ~4 Hz elapsed poll from looking like a stutter. */
  .cap-fill {
    position: absolute;
    inset: 0 auto 0 0;
    background: var(--green);
    transition: width 120ms linear;
  }
  /* The green Start and the outlined stop button are the SHARED `.btn.green` /
     `.btn.danger-o` variants in app.css (identical to Acquire's pair). */
  .run-headline {
    display: flex;
    flex-direction: column;
    line-height: 1.2;
    white-space: nowrap;
  }
  .hl-big {
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .hl-sub {
    font-size: 10.5px;
    color: var(--muted);
  }
</style>
