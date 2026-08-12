/**
 * BLA run store — the orchestration half of the Schoukens "Nonlin" stage
 * (design: `dev/plans/2026-08-10-schoukens-bla-design.md`).
 *
 * The engine owns the maths (`multisine_generator`, `calculate_bla`); this
 * store owns the RUN: it designs the excitation from a band + Δf, validates
 * the whole path BEFORE the first capture, drives `M × n_exc` ordinary
 * one-shot captures through `acquire.record()` (the single seam shared by
 * bridge-NI, bridge-soundcard and browser Web Audio), lands each capture as a
 * hidden raw set, then dispatches the whole ensemble to the `calc_bla` worker
 * op and lands one TF set per excitation.
 *
 * WHY ORDINARY CAPTURES: x and y share the ADC clock, so the unknown AO start
 * offset of each capture rotates X and Y by the same `e^(-jωτ)`, which cancels
 * in the per-realisation solve. A per-capture AO restart therefore costs only
 * the discarded transient periods — which is what makes "loop `record()`"
 * a legitimate implementation rather than a compromise.
 *
 * SAMPLES, NOT SECONDS: the excitation is defined as `N` samples per period
 * exciting integer DFT bins `k1..k2`, so periodicity is exact by construction
 * no matter what the hardware clock actually does (the USB-6003 coerces
 * 48000 → 48019.2 Hz). Everything downstream — capture duration, bin→Hz
 * reporting, the analysis `run_spec.fs` — is computed from the EFFECTIVE rate
 * `fsEff` (the bridge's coerced rate when it reported one, else the requested
 * rate), and each capture's real `fs` is verified against it.
 */
import { derived as svelteDerived, get, writable, type Readable } from 'svelte/store';
import type { AcquireStore } from './acquire';
import { recordingToItem } from './acquire';
import type { Selection } from './selection';
import type { EngineStore } from './engine';
import type { ViewId } from './viewstate';
import type { DvmaItem } from '../model/dataset';
import { generateMultisine } from '../audio/signal';
import type { MultisineStimulusConfig } from '../audio/source';
import {
  outputCapable,
  outputDevices,
  supportsRoutedAiClockAo,
  PYDVMA_DEFAULT_VMAX,
  type BridgeCaps,
  type BridgeConfig,
} from '../audio/provider';

// ---- types ----

/** Run lifecycle. `analysing` covers the single `calc_bla` worker call. */
export type BlaPhase = 'idle' | 'running' | 'analysing' | 'done' | 'error' | 'cancelled';

/**
 * Where the analysis reads excitation `q` from: the MEASURED input channel it
 * is wired to (default, and the only valid choice on any path that is not
 * sample-synced), or the COMMANDED drive regenerated analytically from the
 * seed (sample-synced NI only — see {@link commandedXSupported}).
 */
export type XMode = 'measured' | 'commanded';

/** One driven analog-output channel and the x-source the analysis pairs with it. */
export interface BlaOutputRow {
  /** AO channel index (0-based) this excitation drives. */
  aoChannel: number;
  /** Whether this output takes part in the run (`n_exc` counts the enabled rows). */
  enabled: boolean;
  /** Measured input channel, or the commanded drive. */
  xMode: XMode;
  /** INPUT channel the drive is measured on (`null` in commanded mode). */
  xChannel: number | null;
}

/** The user-facing design parameters of a run. */
export interface BlaDesign {
  /** Band start (Hz) — mapped to the excited bin `k1 = round(f1·N/fs)`. */
  f1Hz: number;
  /** Band end (Hz) — mapped to the excited bin `k2 = round(f2·N/fs)`. */
  f2Hz: number;
  /** Frequency resolution (Hz); fixes the period length `N = round(fs/Δf)`. */
  dfHz: number;
  /**
   * Per-excitation target RMS level. VOLTS on the bridge's NI path, a
   * normalised `0..1` gain on the browser / soundcard path (no calibrated DAC
   * there) — the card labels the unit; the run only needs the number and the
   * rail it is checked against (see {@link outputRailFor}).
   */
  ampRms: number;
  /** Realisations (fresh random phases each) — the σ_tot scatter sample. */
  M: number;
  /** Steady-state periods captured per experiment — the σ_n scatter sample. */
  P: number;
  /** Transient periods played and discarded before the steady-state window. */
  tPeriods: number;
  /** Base name for the run's raw capture sets (`<name> r1e1`, …). */
  testName: string;
  /** One row per driven AO channel. */
  outputs: BlaOutputRow[];
}

/** Everything the design + the live acquisition settings imply. */
export interface BlaDerivedValues {
  /** The rate every sample count is computed at (coerced rate when known). */
  fsEff: number;
  /** Period length in SAMPLES (`N`) — always shown beside {@link periodS}. */
  periodSamples: number;
  /** Period length in SECONDS (`N/fs`) — always shown beside {@link periodSamples}. */
  periodS: number;
  /** Lowest excited bin (0 when the design is not yet valid). */
  k1: number;
  /** Highest excited bin (0 when the design is not yet valid). */
  k2: number;
  /** Excited line count `k2 − k1 + 1`. */
  linesCount: number;
  /** Driven excitation count = enabled output rows. */
  nExc: number;
  /** Run-wide x-mode (mixed rows are rejected by preflight). */
  xMode: XMode;
  /** Measured-x input channels per excitation (empty in commanded mode). */
  xChannels: number[];
  /** Response channels = every input channel that is not a measured x. */
  respChannels: number[];
  /** Samples captured per (m, e) — `(t + P)·N` plus rounding slack. */
  captureSamples: number;
  /** Capture duration per (m, e) in seconds. */
  captureS: number;
  /** Wall-clock estimate for the whole run (`M · n_exc · captureS`). */
  totalRunS: number;
}

/** The `multisine` block of a BlaRunSpec — SNAKE_CASE, as the engine reads it. */
export interface BlaMultisineWire {
  n_samples: number;
  k1: number;
  k2: number;
  p_periods: number;
  t_periods: number;
  seed: number;
  amp_rms: number;
  n_exc: number;
  M: number;
}

/**
 * The `run_spec` argument of the `calc_bla` op (snake_case; see
 * `analysis.calculate_bla`). Stored in the run state so a finished run is
 * fully reproducible from the UI alone.
 */
export interface BlaRunSpec {
  multisine: BlaMultisineWire;
  x_mode: XMode;
  /** Measured-x channel per excitation, or `null` in commanded mode. */
  x_channels: number[] | null;
  resp_channels: number[];
  /** The ACTUAL capture rate (coerced), not the requested one. */
  fs: number;
}

/** Per-capture lifecycle in the progress grid. */
export type BlaCaptureStatus = 'pending' | 'running' | 'done';

/**
 * One cell of the `M × n_exc` progress grid (round-11 P6). A scalar
 * "realisation 2/6 · experiment 1/2" told the user where the run was but not
 * how much of it was behind them; the grid is the whole run at a glance, one
 * row per realisation.
 */
export interface BlaCapture {
  /** Realisation index (0-based). */
  m: number;
  /** Experiment index (0-based). */
  e: number;
  status: BlaCaptureStatus;
}

/** Live run state (the card's progress + results surface). */
export interface BlaState {
  phase: BlaPhase;
  /** Realisation index of the capture in flight (0-based). */
  m: number;
  /** Experiment index of the capture in flight (0-based). */
  e: number;
  /**
   * Every capture the run will take, in `(m, e)` order, each with its own
   * status — the progress grid's model. Empty until a run starts.
   */
  captures: BlaCapture[];
  /** `Date.now()` when the run began (`0` while idle) — for the ETA readout. */
  runStartedAt: number;
  /** Hard-failure message (`''` when none). */
  error: string;
  /** The spec the current/last run was launched with. */
  runSpec: BlaRunSpec | null;
  /** Selection ids of the raw captures, in `(m, e)` order. */
  rawSetIds: number[];
  /** Selection ids of the landed BLA sets, one per excitation. */
  resultSetIds: number[];
  /** Advisory notes raised by preflight (e.g. "pretrigger disarmed"). */
  notes: string[];
}

/**
 * What Start does when a previous run's sets are still present (round-11 P6 —
 * Tore: "what happens if you run it, change settings, and go again — will it
 * add a huge new dataset or replace? That all needs options and clarity").
 *
 * - `replace` (default) removes the previous run's raw + result sets, with a
 *   one-level Undo toast.
 * - `keep` leaves them and SUFFIXES the new run's names (`bla#2 …`) so the two
 *   runs stay distinguishable in the tray and the legend.
 */
export type BlaRunMode = 'replace' | 'keep';

/**
 * Every identifier {@link preflightBla} can attach to a finding. A CLOSED
 * union on purpose: the card places each message beside the control its code
 * names, and its `CODE_PLACEMENT` map carries a type-level exhaustiveness
 * assertion over this union — so a code added here without being given a home
 * there fails to compile, instead of producing a message that only the card's
 * catch-all net keeps visible.
 */
export type BlaCheckCode =
  | 'fs'
  | 'design'
  | 'band'
  | 'lpf'
  | 'output-fs'
  | 'pretrigger'
  | 'n-exc'
  | 'x-mode'
  | 'commanded-sync'
  | 'ao-channels'
  | 'ao-prefix'
  | 'x-channels'
  | 'resp-channels'
  | 'peak';

/**
 * One preflight finding. `ok: false` is a HARD failure (the run refuses to
 * start); `ok: true` is an advisory the run acts on and reports (currently
 * only the pretrigger auto-disarm). A clean design yields an EMPTY list.
 */
export interface BlaCheck {
  ok: boolean;
  /** Stable identifier for tests / the card's per-field highlighting. */
  code: BlaCheckCode;
  /** User-facing sentence. */
  reason: string;
}

/** Everything {@link preflightBla} needs — a plain object, so it stays pure. */
export interface BlaPreflightInput {
  design: BlaDesign;
  values: BlaDerivedValues;
  /** `acquire.settings.sampleRate` — the rate the bridge's `output_fs` is compared to. */
  requestedFs: number;
  /** `acquire.settings.channelCount`. */
  channelCount: number;
  /** `acquire.settings.lpfOn`. */
  lpfOn: boolean;
  /** `bridgeConfig.pretrigArmed`. */
  pretrigArmed: boolean;
  providerKind: 'webaudio' | 'bridge';
  caps: BridgeCaps | null;
  inputDeviceId: string;
  /** `bridgeConfig.outputDeviceId` (unset ⇒ the input device). */
  outputDeviceId?: string;
  /** `bridgeConfig.outputFs` — the staged AO-rate clamp, if any. */
  stagedOutputFs?: number;
  /** Peak rail the generated waveform is checked against (volts, or ±1). */
  outputRail: number;
  /**
   * The seed the run will actually use. The peak guard generates every
   * realisation's waveform, and the crest factor depends on the seed, so it
   * has to be drawn before validation rather than after. Irrelevant (and left
   * at `0`) when the peak check is skipped.
   *
   * NB the browser path plays exactly these waveforms; the bridge regenerates
   * them from the same spec under numpy's PRNG, so there the sweep is a close
   * approximation guarded by {@link BLA_BRIDGE_PEAK_MARGIN}, not an exact
   * preview.
   */
  seed: number;
}

/** The actions surface a BLA run needs (structural, so tests stay light). */
export interface BlaActions {
  addRecordedSet(item: DvmaItem, opts?: { hidden?: boolean }): number;
  addBlaSets(
    results: unknown[],
    opts?: { names?: string[]; channelLabels?: string[]; timestring?: string },
  ): number[];
  /**
   * Drop a previous run's sets (dataset + tray + derived) and offer an Undo
   * toast. Optional so a test double can stay minimal; a store built without
   * it simply never replaces (see {@link BlaRunMode}).
   */
  removeBlaRun?(ids: readonly number[], opts?: { label?: string }): number;
}

/** Constructor dependencies. */
export interface BlaDeps {
  acquire: AcquireStore;
  actions: BlaActions;
  engine: EngineStore;
  selection: Selection;
  /** Optional view store, so a finished run can jump the plot to TF. */
  viewState?: { activate(view: ViewId): void };
}

export type BlaStore = ReturnType<typeof createBlaStore>;

// ---- constants + pure helpers ----

/**
 * Extra samples appended to every capture beyond the `(t + P)·N` the analysis
 * slices. The capture length reaches the device as SECONDS (`durationS`), and
 * both backends turn that back into a sample count by rounding — one sample
 * short and `calculate_bla` rejects the whole run ("capture too short"). A
 * small fixed slack removes that entire failure mode; the analysis reads the
 * first `(t + P)·N` samples and ignores the tail.
 */
export const BLA_CAPTURE_MARGIN_SAMPLES = 256;

/** Rate agreement tolerance (Hz) — matches the acquire store's coerced-fs test. */
export const BLA_FS_TOLERANCE_HZ = 0.5;

/**
 * Fraction of the output rail the preflight peak sweep allows on the BRIDGE
 * path — a deliberate safety margin, not a physical limit.
 *
 * The sweep generates the waveforms with the TypeScript generator
 * ({@link generateMultisine}, mulberry32). On the browser path those ARE the
 * waveforms that will play, so the check is exact. On the bridge the server
 * regenerates them from the same spec with numpy's `default_rng` — same
 * amplitude/rotation/periodicity LAW, but a different PRNG, so the phases (and
 * therefore the crest factor) differ realisation by realisation. A level a few
 * percent under the rail can pass here and trip
 * `multisine_generator`'s hard peak error mid-run, throwing away the captures
 * already taken. Checking against 97% of the rail keeps the client
 * conservative; the cost is refusing a sliver of levels the server would in
 * fact have accepted, which is the right way round.
 */
export const BLA_BRIDGE_PEAK_MARGIN = 0.97;

/**
 * Whether ANY capture path has been proven to start AO and AI with a fixed
 * sample offset — the property commanded-x actually needs, over and above a
 * shared/routed sample CLOCK.
 *
 * `false` since the 2026-08-11 hardware measurement (`dev/bridge_hw_check.py`
 * check G, USB-6212 and cDAQ-9174): the AI stream runs continuously and each
 * capture is a window of it, so the AO start lands on an arbitrary clock tick
 * per capture even on the routed-clock 6212. The random per-capture phase
 * collapses the commanded-x BLA mean by 1/√M (measured |G| ≈ 0.43 at M = 4
 * through a physical loopback that measured-x resolves to 1 exactly) and
 * inflates σ_NL to ~2.4·|G|. Flip this back only once the acquisition path
 * gains an AO/AI shared start trigger AND a hardware run proves a fixed
 * offset (same tracker as the cDAQ AO/AI sync gap in TODO.md).
 */
export const BLA_COMMANDED_X_START_SYNC_PROVEN = false;

/**
 * Why the COMMANDED x-mode is refused — the card shows this on the disabled
 * "commanded drive" option, and {@link preflightBla} reports the same
 * sentence if a run asks for it anyway.
 */
export const BLA_COMMANDED_X_REASON =
  'Commanded drive is disabled: even with a routed AI sample clock the AO start lands on an '
  + 'arbitrary tick of the free-running capture stream, so each capture carries a random phase '
  + 'offset (hardware-measured 2026-08-11: the BLA mean collapses by 1/√M). '
  + 'Measure the drive on an input channel instead.';

/**
 * Whether the analysis may read the excitation from the COMMANDED drive
 * (regenerated from the seed) rather than from a measured input channel.
 *
 * Currently `false` on EVERY path — see
 * {@link BLA_COMMANDED_X_START_SYNC_PROVEN}. The original design admitted a
 * bridge NI device with the AI sample clock routed to the AO
 * ({@link supportsRoutedAiClockAo}), but the routed clock only locks the
 * RATE; the 2026-08-11 hardware run showed the AO START still lands on an
 * arbitrary tick of the free-running capture stream, which is fatal for
 * commanded-x (the regenerated x assumes a zero per-capture offset). The
 * full condition is kept in place so proving start sync later reopens the
 * gate without re-deriving the rest. Measured-x is unaffected and works
 * everywhere: x and y share the ADC clock, so the common phase rotation
 * cancels in the solve.
 *
 * @param input The preflight fields describing the capture path.
 * @returns Whether commanded-x is admissible.
 */
export function commandedXSupported(
  input: Pick<BlaPreflightInput,
    'providerKind' | 'caps' | 'inputDeviceId' | 'outputDeviceId' | 'stagedOutputFs' | 'requestedFs' | 'lpfOn'>,
): boolean {
  return BLA_COMMANDED_X_START_SYNC_PROVEN
    && input.providerKind === 'bridge'
    && supportsRoutedAiClockAo(input.caps, input.inputDeviceId, input.outputDeviceId)
    && !(input.stagedOutputFs != null
      && Math.abs(input.stagedOutputFs - input.requestedFs) > BLA_FS_TOLERANCE_HZ)
    && !input.lpfOn;
}

/**
 * How one excitation is named wherever the UI refers to it: `q1 (via ch0)` for
 * a measured drive, `q1 (commanded)` for a regenerated one. The result set's
 * display name and the card's verdict line both build on this, so the two can
 * never disagree about which channel carried `q`.
 *
 * @param q Zero-based excitation index (displayed 1-based).
 * @param xMode Whether the run reads x measured or commanded.
 * @param xChannels Measured-x input channels in excitation order (ignored in
 *   commanded mode; a missing entry renders as `ch?`).
 * @returns The label, without any test-name prefix.
 */
export function excitationLabel(
  q: number,
  xMode: XMode,
  xChannels?: readonly (number | null)[] | null,
): string {
  const via = xMode === 'commanded' ? 'commanded' : `via ch${xChannels?.[q] ?? '?'}`;
  return `q${q + 1} (${via})`;
}

/** A fresh design: 20 Hz–2 kHz at 5 Hz resolution, Schoukens' M/P defaults. */
export function defaultBlaDesign(): BlaDesign {
  return {
    f1Hz: 20,
    f2Hz: 2000,
    dfHz: 5,
    ampRms: 0.1,
    M: 6,
    P: 4,
    tPeriods: 2,
    testName: 'bla',
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 0 }],
  };
}

/** Fresh run state (idle, nothing landed). */
function emptyState(): BlaState {
  return {
    phase: 'idle', m: 0, e: 0, captures: [], runStartedAt: 0, error: '',
    runSpec: null, rawSetIds: [], resultSetIds: [], notes: [],
  };
}

/** The `M × n_exc` grid a run starts from — every cell pending, in `(m, e)` order. */
export function plannedCaptures(M: number, nExc: number): BlaCapture[] {
  const rows = Math.max(0, Math.trunc(M));
  const cols = Math.max(0, Math.trunc(nExc));
  const out: BlaCapture[] = [];
  for (let m = 0; m < rows; m++) for (let e = 0; e < cols; e++) out.push({ m, e, status: 'pending' });
  return out;
}

/**
 * Period length in samples for a requested frequency resolution:
 * `N = round(fs/Δf)`. Returns `0` for a nonsensical request (preflight then
 * reports it) so callers never divide by a garbage `N`.
 */
export function periodSamplesFor(fs: number, dfHz: number): number {
  if (!(fs > 0) || !(dfHz > 0) || !Number.isFinite(fs) || !Number.isFinite(dfHz)) return 0;
  return Math.round(fs / dfHz);
}

/**
 * Which of the two linked period fields the user just edited.
 * @see resolveBlaPeriod
 */
export type BlaPeriodQuantity = 'df' | 'period';

/** A resolved period: the sample count `N` and both of its user-facing faces. */
export interface BlaPeriodResolution {
  /** Period length in samples — the primitive the excitation is defined in. */
  periodSamples: number;
  /** Frequency resolution (Hz). */
  dfHz: number;
  /** Period length (s). */
  periodS: number;
}

/**
 * Resolve the LINKED period pair from whichever field was edited (round-11
 * P6). Tore's report: "took a while to spot that changing delta f was
 * actually setting the period, which was quite a critical number to notice" —
 * so the card offers Δf AND T as two equal inputs, and this is the single
 * coupling entry point they and their tests share (the `resolveFrom` pattern
 * from `analysis/resolutionControl.ts`).
 *
 * `N` is the primitive either way, because the excitation is defined in
 * SAMPLES so its periodicity survives a coerced clock:
 *
 * - editing **Δf** ⇒ `N = round(fs/Δf)`, `T = N/fs`, and Δf is echoed back
 *   verbatim (the user's typed intent stays in its own box);
 * - editing **T** ⇒ `N = round(T·fs)`, and BOTH readouts come from that `N`
 *   (`Δf = fs/N`, `T = N/fs`), because a typed T is a request for a period
 *   length and the achievable one is the rounded sample count.
 *
 * A nonsensical request (non-positive or non-finite fs / value, or a period
 * under one sample) resolves to `N = 0` rather than NaN or Infinity;
 * {@link preflightBla} then reports it against the field.
 *
 * @param quantity Which field was edited.
 * @param value Its new value (Hz for `'df'`, seconds for `'period'`).
 * @param fs Effective sample rate the design resolves against.
 * @returns The resolved `{periodSamples, dfHz, periodS}` triple.
 */
export function resolveBlaPeriod(
  quantity: BlaPeriodQuantity,
  value: number,
  fs: number,
): BlaPeriodResolution {
  const okFs = Number.isFinite(fs) && fs > 0;
  if (quantity === 'df') {
    const N = periodSamplesFor(fs, value);
    return { periodSamples: N, dfHz: value, periodS: N > 0 && okFs ? N / fs : 0 };
  }
  const N = okFs && Number.isFinite(value) && value > 0 ? Math.round(value * fs) : 0;
  return {
    periodSamples: N,
    dfHz: N > 0 ? fs / N : 0,
    periodS: N > 0 ? N / fs : 0,
  };
}

/**
 * Significant figures the card's period boxes display. Enough that reading a
 * displayed value back resolves to the SAME `N` (the round-trip needs a
 * relative error under `0.5/N`, so 7 figures covers every `N` below 10⁷ — a
 * period of two minutes at 96 kHz), while staying short enough to read.
 */
export const BLA_PERIOD_DISPLAY_SIGFIGS = 7;

/** Round to {@link BLA_PERIOD_DISPLAY_SIGFIGS} without trailing-zero padding. */
export function roundForPeriodBox(v: number): number {
  if (!Number.isFinite(v) || v === 0) return 0;
  return Number(v.toPrecision(BLA_PERIOD_DISPLAY_SIGFIGS));
}

/**
 * The base name this run's sets should carry, given the names already in the
 * tray (round-11 P6, the "keep both" arm of {@link BlaRunMode}).
 *
 * A run's sets are all named `<base> …` — raw captures `<base> r1e1`, results
 * `<base> BLA q1 (via ch0)`. Landing a second run under the SAME test name
 * would produce byte-identical names, leaving the user with two
 * indistinguishable groups of tray cards. So: if any existing name already
 * belongs to a run of this test name, the new run takes the next free
 * `#n` suffix. A test name the user CHANGED between runs collides with
 * nothing and is used verbatim — renaming is the explicit way to say "these
 * are different runs".
 *
 * @param testName The design's test name.
 * @param existingNames Every set name currently in the tray.
 * @returns The base name to build this run's set names from
 *   (`'bla'` → `'bla#2'` → `'bla#3'`).
 */
export function blaRunBaseName(testName: string, existingNames: readonly string[]): string {
  const base = testName.trim();
  if (!base) return testName;
  // `bla` matches "bla r1e1" and "bla#3 BLA q1 (…)", but NOT "blast r1e1":
  // the base must be followed by an optional #n and then a space.
  const escaped = base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`^${escaped}(?:#(\\d+))?\\s`);
  let highest = 0;
  for (const name of existingNames) {
    const m = re.exec(name);
    if (!m) continue;
    highest = Math.max(highest, m[1] ? Number(m[1]) : 1);
  }
  return highest === 0 ? base : `${base}#${highest + 1}`;
}

/**
 * Mark one cell of the progress grid, returning a NEW array (the state is
 * replaced wholesale so Svelte sees the change).
 *
 * @param cells The current grid.
 * @param m Realisation index of the capture whose status changed.
 * @param e Experiment index of that capture.
 * @param status Its new status.
 * @returns The updated grid.
 */
export function markBlaCapture(
  cells: readonly BlaCapture[],
  m: number,
  e: number,
  status: BlaCaptureStatus,
): BlaCapture[] {
  return cells.map((c) => (c.m === m && c.e === e ? { ...c, status } : c));
}

/**
 * Seconds of capture still to come: the untouched captures in full, plus
 * whatever is left of the one in flight. Deliberately counts CAPTURE time
 * only — the analysis call that follows has no progress model at all (one
 * opaque worker call), so folding a guess for it into the number the user
 * reads as "time left" would make the estimate dishonest rather than
 * complete; the card shows `computing BLA…` for that phase instead.
 *
 * @param cells The progress grid.
 * @param captureS Seconds per capture.
 * @param elapsedS Seconds elapsed in the capture currently in flight.
 * @returns Estimated seconds remaining (never negative).
 */
export function blaRemainingS(
  cells: readonly BlaCapture[],
  captureS: number,
  elapsedS: number,
): number {
  if (!(captureS > 0)) return 0;
  const left = cells.filter((c) => c.status !== 'done').length;
  const inFlight = cells.some((c) => c.status === 'running')
    ? Math.min(Math.max(elapsedS, 0), captureS)
    : 0;
  return Math.max(0, left * captureS - inFlight);
}

/**
 * Excited DFT bin for a frequency: `k = round(f·N/fs)`, clamped to the legal
 * range `1 .. floor((N−1)/2)` — bin 0 is DC and, for even `N`, the Nyquist bin
 * is excluded because its rfft coefficient is real and cannot carry a random
 * phase (the same bound `multisine_generator` and `calculate_bla` enforce).
 * Returns `0` when no legal bin exists.
 */
export function binFor(fHz: number, N: number, fs: number): number {
  if (!(N > 0) || !(fs > 0) || !Number.isFinite(fHz)) return 0;
  const kMax = Math.floor((N - 1) / 2);
  if (kMax < 1) return 0;
  return Math.min(Math.max(Math.round((fHz * N) / fs), 1), kMax);
}

/**
 * Resolve a design against the live acquisition settings: period length (in
 * BOTH samples and seconds — the card must always label both), excited bins,
 * channel roles, per-capture duration and the total run time.
 *
 * Response channels are every input channel that is not carrying a measured
 * drive; in commanded mode nothing is subtracted, so ALL inputs are responses.
 * `n_resp` is independent of `n_exc` — non-square systems are first-class.
 */
export function deriveBla(design: BlaDesign, fsEff: number, channelCount: number): BlaDerivedValues {
  const fs = Number.isFinite(fsEff) && fsEff > 0 ? fsEff : 0;
  const N = periodSamplesFor(fs, design.dfHz);
  const k1 = binFor(design.f1Hz, N, fs);
  const k2 = binFor(design.f2Hz, N, fs);
  const enabled = design.outputs.filter((o) => o.enabled);
  const nExc = enabled.length;
  // A run has ONE x_mode; a mixed table is rejected by preflight rather than
  // silently resolved, so the reported mode is 'commanded' only when EVERY
  // enabled row asks for it.
  const xMode: XMode = nExc > 0 && enabled.every((o) => o.xMode === 'commanded')
    ? 'commanded'
    : 'measured';
  const xChannels = xMode === 'commanded'
    ? []
    : enabled.map((o) => (o.xChannel == null ? -1 : Math.trunc(o.xChannel)));
  const nCh = Math.max(0, Math.trunc(channelCount));
  const respChannels: number[] = [];
  for (let c = 0; c < nCh; c++) if (!xChannels.includes(c)) respChannels.push(c);
  const periods = Math.max(0, Math.trunc(design.tPeriods)) + Math.max(0, Math.trunc(design.P));
  const captureSamples = N > 0 ? periods * N + BLA_CAPTURE_MARGIN_SAMPLES : 0;
  const captureS = fs > 0 ? captureSamples / fs : 0;
  return {
    fsEff: fs,
    periodSamples: N,
    periodS: fs > 0 ? N / fs : 0,
    k1,
    k2,
    linesCount: k2 >= k1 && k1 > 0 ? k2 - k1 + 1 : 0,
    nExc,
    xMode,
    xChannels,
    respChannels,
    captureSamples,
    captureS,
    totalRunS: Math.max(0, Math.trunc(design.M)) * nExc * captureS,
  };
}

/**
 * Effective peak rail the generated waveform must stay inside — an exact
 * mirror of `MySettings.output_vmax()`, which is what `multisine_generator`
 * checks the peak against server-side: `output_VmaxNI` on an NI output,
 * `output_VmaxSC` (default 1.0) on the soundcard, and the browser's
 * `AudioBuffer` rail is ±1 too, so everything that is not NI is `1`.
 *
 * The NI arm is the STAGED `outputVmaxNI` or pydvma's 5 V default — NOT the
 * device's `ao_vmax`. That distinction is load-bearing: `ao_vmax` is a
 * hardware CAPABILITY the acquire store clamps *down* to (a 9260's ±4.2426 V
 * rail), never a value the server adopts. On a device whose AO can swing wider
 * than the default (the 6212/6003 report 10 V) the store leaves `outputVmaxNI`
 * unset and the server still runs at 5 V, so checking the peak against 10 V
 * would pass a level here and hard-fail at capture (0, 0) — precisely the
 * mid-run failure the preflight sweep exists to prevent.
 */
export function outputRailFor(
  providerKind: 'webaudio' | 'bridge',
  cfg: BridgeConfig,
  inputDeviceId: string,
): number {
  if (providerKind !== 'bridge') return 1;
  const outDev = cfg.outputDeviceId || inputDeviceId;
  const sep = outDev.indexOf(':');
  const driver = sep >= 0 ? outDev.slice(0, sep) : outDev;
  if (driver !== 'nidaq') return 1;
  return cfg.outputVmaxNI ?? PYDVMA_DEFAULT_VMAX;
}

/**
 * Validate a whole run BEFORE the first capture. Returns one {@link BlaCheck}
 * per PROBLEM found (empty ⇒ everything is fine); any entry with `ok: false`
 * refuses the run. Written as a pure function of a plain input object so every
 * failure mode is unit-testable without a provider, an engine or a DOM.
 *
 * The rules, and why each one is a hard failure rather than a silent fix:
 * - **`output_fs === fs`** — a staged AO-rate clamp (the acquire store's
 *   `reclampOutputFs`, e.g. a USB-6003 whose AO tops out at 5 kS/s) means the
 *   drive plays at a different rate than the capture: the multisine's integer
 *   periods stop being integer, and on NI it also disables the shared clock.
 *   In BLA mode that must be visible, never clamped away.
 * - **`lpf_on` off** — the digital low-pass captures oversampled and RESAMPLES
 *   down, so the recorded period is no longer a whole number of samples and
 *   the leakage it introduces lands in the realisation scatter as fake σ_NL.
 * - **commanded x** — only when the caps PROVE a routed AI sample clock on the
 *   same non-chassis NI device at a matched rate ({@link commandedXSupported});
 *   otherwise per-capture start jitter corrupts σ²_NL, so the fix is to
 *   measure the drive on an input channel.
 * - **pretrigger** — an advisory, not a failure: the run disarms it (a BLA
 *   capture is a fixed-length free-run window, and an armed capture would
 *   start at a threshold crossing somewhere inside the transient).
 * - **peak guard** — the crest factor varies per `(m, e)`, so a level that
 *   passes at (0,0) can clip at (3,1); generating every waveform up front
 *   turns a mid-run failure into a pre-run message. EXACT on the browser path
 *   (those are the waveforms that play); on the bridge the server redraws the
 *   phases with numpy's PRNG under the same amplitude/rotation law, so the
 *   sweep is an approximation and is checked against
 *   {@link BLA_BRIDGE_PEAK_MARGIN} of the rail instead. COST: this is
 *   `O(M · n_exc² · N · n_lines)` time-domain sums — milliseconds for a normal
 *   design, but SECONDS at a very fine Δf (large `N`) with several excitations,
 *   and it runs synchronously. Pass `opts.peakCheck: false` for the live
 *   card-side validation and leave it on for the real start.
 */
export function preflightBla(
  input: BlaPreflightInput,
  opts: { peakCheck?: boolean } = {},
): BlaCheck[] {
  const { design, values } = input;
  const out: BlaCheck[] = [];
  const fail = (code: BlaCheckCode, reason: string) => out.push({ ok: false, code, reason });

  // ---- 1. design sanity + effective rate ----
  if (!(values.fsEff > 0)) {
    fail('fs', 'No sample rate is set — choose a device and rate in Setup first.');
  }
  if (!(design.dfHz > 0)) {
    fail('design', 'Frequency resolution Δf must be greater than zero.');
  }
  if (!(design.f2Hz > design.f1Hz)) {
    fail('design', `Band end must be above band start (got ${design.f1Hz} → ${design.f2Hz} Hz).`);
  }
  if (!(design.ampRms > 0)) {
    fail('design', 'Excitation level must be greater than zero.');
  }
  if (!(design.M >= 2)) {
    fail('design', `BLA needs at least 2 realisations to estimate the realisation scatter (M = ${design.M}).`);
  }
  if (!(design.P >= 2)) {
    fail('design', `BLA needs at least 2 steady-state periods to estimate the noise (P = ${design.P}).`);
  }
  if (design.tPeriods < 0) {
    fail('design', 'Transient periods cannot be negative.');
  }

  // ---- 2. band → bins ----
  if (values.fsEff > 0 && design.f2Hz > values.fsEff / 2) {
    fail('band', `Band end ${design.f2Hz} Hz is above the Nyquist frequency `
      + `${(values.fsEff / 2).toFixed(1)} Hz for a ${values.fsEff} Hz capture.`);
  }
  if (values.periodSamples > 0 && !(1 <= values.k1 && values.k1 <= values.k2
      && values.k2 <= Math.floor((values.periodSamples - 1) / 2))) {
    fail('band', `The band maps to no usable excitation lines at Δf = ${design.dfHz} Hz `
      + `(period N = ${values.periodSamples} samples, k1 = ${values.k1}, k2 = ${values.k2}) `
      + '— widen the band or lower Δf.');
  }

  // ---- 3. capture path ----
  if (input.lpfOn) {
    fail('lpf', 'Turn the digital low-pass off for a BLA run — it resamples the capture, '
      + 'which destroys the multisine periodicity the analysis depends on.');
  }
  if (input.providerKind === 'bridge' && input.stagedOutputFs != null
      && Math.abs(input.stagedOutputFs - input.requestedFs) > BLA_FS_TOLERANCE_HZ) {
    fail('output-fs', `The output rate is clamped to ${input.stagedOutputFs} Hz while the capture `
      + `runs at ${input.requestedFs} Hz. A BLA run needs output_fs = fs (a mismatched drive rate `
      + 'breaks the multisine periodicity), so lower the sample rate to the device’s AO limit '
      + 'or choose an output device that can keep up.');
  }
  if (input.pretrigArmed) {
    out.push({
      ok: true,
      code: 'pretrigger',
      reason: 'Pretrigger disarmed for this run — BLA captures are fixed-length free-run windows.',
    });
  }

  // ---- 4. excitation table ----
  const enabled = design.outputs.filter((o) => o.enabled);
  if (values.nExc < 1) {
    fail('n-exc', 'Enable at least one output channel to drive.');
  }
  const mixed = enabled.some((o) => o.xMode === 'commanded') && enabled.some((o) => o.xMode === 'measured');
  if (mixed) {
    fail('x-mode', 'Every excitation must use the same x source — mix of measured and commanded '
      + 'drive is not supported in one run.');
  }
  // The excitation table's `aoChannel` is DECORATIVE in V1: the run reduces the
  // enabled rows to a COUNT (`n_exc`), and both generators write excitation q
  // to buffer column q — which the server maps onto the device's first n_exc
  // analog outputs (`build_ao_channel_string` with no `output_channels_spec`).
  // So enabling ao1 alone would drive ao0, and the user would see a physically
  // inexplicable result (a near-singular X, or a response to a channel they
  // believe is silent). Refuse anything that is not the prefix ao0..ao(n−1),
  // IN ORDER, rather than quietly re-routing.
  if (values.nExc > 0 && enabled.some((o, i) => Math.trunc(o.aoChannel) !== i)) {
    const listed = enabled.map((o) => `ao${o.aoChannel}`).join(', ');
    fail('ao-prefix', `A BLA run drives ao0…ao${values.nExc - 1} in order, but the table enables `
      + `${listed}. Enable the FIRST ${values.nExc} output${values.nExc === 1 ? '' : 's'} instead `
      + '— per-channel routing is a follow-up.');
  }
  if (values.xMode === 'commanded' && !commandedXSupported(input)) {
    fail('commanded-sync', BLA_COMMANDED_X_REASON);
  }
  // AO width is preflightable on the BRIDGE only: the server advertises each
  // device's output channel count in its capability document. The BROWSER's
  // equivalent (`destination.maxChannelCount`) is only readable from a live
  // `AudioContext`, which this function — pure, DOM-free, and re-run on every
  // keystroke by the card's live `checks` store — must not construct. There,
  // `multisineStimulusBuffer` (source.ts) raises "output device exposes N
  // channels; run needs M" while building the FIRST capture's stimulus, before
  // any samples are recorded, so a too-wide browser run fails loudly at capture
  // (0, 0) rather than silently down-mixing the excitations into each other.
  if (values.nExc > 0 && input.providerKind === 'bridge' && input.caps) {
    const outDev = input.outputDeviceId || input.inputDeviceId;
    if (!outputCapable(input.caps, outDev)) {
      fail('ao-channels', 'The selected device reports no analog output — a BLA run has to drive '
        + 'the excitation.');
    } else {
      const maxOut = outputDevices(input.caps).find((d) => d.deviceId === outDev)?.maxChannels;
      if (maxOut != null && values.nExc > maxOut) {
        fail('ao-channels', `The run drives ${values.nExc} excitations but the output device has `
          + `only ${maxOut} analog-output channel${maxOut === 1 ? '' : 's'}.`);
      }
    }
  }

  // ---- 5. channel roles ----
  if (values.xMode === 'measured' && values.nExc > 0) {
    const seen = new Set<number>();
    for (const ch of values.xChannels) {
      if (!Number.isInteger(ch) || ch < 0 || ch >= input.channelCount) {
        fail('x-channels', `Measured-x channel ${ch < 0 ? '(unset)' : ch} is outside the `
          + `${input.channelCount} captured input channel${input.channelCount === 1 ? '' : 's'}.`);
        break;
      }
      if (seen.has(ch)) {
        fail('x-channels', `Input channel ${ch} is assigned to more than one excitation — each `
          + 'drive needs its own measured channel.');
        break;
      }
      seen.add(ch);
    }
  }
  if (values.respChannels.length < 1) {
    fail('resp-channels', 'No response channels are left — capture at least one input channel '
      + 'beyond the measured drives.');
  }

  // ---- 6. peak guard, every (m, e) ----
  // Only worth running once the design itself is sound; the generator would
  // otherwise just re-report a bad bin range.
  if ((opts.peakCheck ?? true) && out.every((c) => c.ok) && values.nExc > 0 && values.linesCount > 0) {
    // On the bridge the SERVER regenerates these waveforms with a different
    // PRNG, so the phases — and the crest factor — are not the ones checked
    // here; leave headroom so a near-rail level is refused now rather than
    // mid-run by `multisine_generator`. The browser plays exactly what is
    // generated here, so it gets the full rail.
    const limit = input.providerKind === 'bridge'
      ? input.outputRail * BLA_BRIDGE_PEAK_MARGIN
      : input.outputRail;
    try {
      for (let m = 0; m < design.M; m++) {
        for (let e = 0; e < values.nExc; e++) {
          // ONE period is enough: the tiled buffer repeats it exactly, so the
          // peak is identical while the allocation is (t + P)× smaller.
          generateMultisine(
            {
              nSamples: values.periodSamples,
              k1: values.k1,
              k2: values.k2,
              pPeriods: 1,
              tPeriods: 0,
              seed: input.seed,
              m,
              e,
              nExc: values.nExc,
              ampRms: design.ampRms,
              limit,
            },
            values.fsEff,
          );
        }
      }
    } catch (err) {
      fail('peak', err instanceof Error ? err.message : String(err));
    }
  }

  return out;
}

/** First hard-failure reason in a check list, or `''` when the run may start. */
export function firstBlaError(checks: BlaCheck[]): string {
  return checks.find((c) => !c.ok)?.reason ?? '';
}

// ---- store factory ----

/**
 * Create the BLA run store. The card binds `design` (writable), reads `values`
 * / `checks` (derived, live) and `state`, and calls `start()` / `cancel()`.
 */
export function createBlaStore(deps: BlaDeps) {
  const { acquire, actions, engine, selection, viewState } = deps;
  const design = writable<BlaDesign>(defaultBlaDesign());
  const state = writable<BlaState>(emptyState());
  /**
   * What the next Start does with a previous run's sets. Deliberately NOT part
   * of {@link BlaDesign}: it describes the act of running, not the excitation,
   * so it must not travel into the run spec a saved result carries.
   */
  const runMode = writable<BlaRunMode>('replace');
  /** Set by {@link cancel}; checked between captures. */
  let cancelRequested = false;

  /** The rate every sample count is derived at: the coerced rate when the
   *  bridge reported one, else the requested rate. */
  const fsEff: Readable<number> = svelteDerived(
    [acquire.settings, acquire.coercedFs],
    ([$s, $c]) => ($c ? $c.configured : $s.sampleRate),
  );

  const values: Readable<BlaDerivedValues> = svelteDerived(
    [design, fsEff, acquire.settings],
    ([$d, $fs, $s]) => deriveBla($d, $fs, $s.channelCount),
  );

  /** The preflight input assembled from the live stores, for a given seed. */
  function preflightInput(seed = 0): BlaPreflightInput {
    const s = get(acquire.settings);
    const cfg = get(acquire.bridgeConfig);
    const caps = get(acquire.bridgeCaps);
    const kind = get(acquire.kind);
    return {
      design: get(design),
      values: get(values),
      requestedFs: s.sampleRate,
      channelCount: s.channelCount,
      lpfOn: s.lpfOn,
      pretrigArmed: !!cfg.pretrigArmed,
      providerKind: kind,
      caps,
      inputDeviceId: s.deviceId,
      outputDeviceId: cfg.outputDeviceId,
      stagedOutputFs: cfg.outputFs,
      outputRail: outputRailFor(kind, cfg, s.deviceId),
      seed,
    };
  }

  /**
   * Live validation for the card (Start disabled with a reason). The peak
   * guard is SKIPPED here — it is O(M · n_exc² · N · n_lines) and would run on
   * every keystroke; `start()` runs the full check including the peak.
   */
  const checks: Readable<BlaCheck[]> = svelteDerived(
    [design, values, acquire.settings, acquire.bridgeConfig, acquire.bridgeCaps, acquire.kind],
    () => preflightBla(preflightInput(), { peakCheck: false }),
  );

  /** Build one capture's stimulus spec. */
  function stimulusFor(
    d: BlaDesign, v: BlaDerivedValues, seed: number, m: number, e: number, rail: number,
  ): MultisineStimulusConfig {
    return {
      type: 'multisine',
      nSamples: v.periodSamples,
      k1: v.k1,
      k2: v.k2,
      pPeriods: Math.trunc(d.P),
      tPeriods: Math.trunc(d.tPeriods),
      seed,
      m,
      e,
      nExc: v.nExc,
      ampRms: d.ampRms,
      limit: rail,
    };
  }

  /**
   * Display name for excitation `q`'s result set — the run's base name in
   * front of the shared {@link excitationLabel}, so the tray name and the
   * card's verdict line always describe the same geometry.
   */
  function resultName(base: string, v: BlaDerivedValues, q: number): string {
    return `${base} BLA ${excitationLabel(q, v.xMode, v.xChannels)}`;
  }

  /**
   * Whether a previous run's sets are still in the tray — the gate on the
   * replace/keep choice, and the reason it appears at all. Checked against the
   * LIVE tray rather than the id list alone, so a run whose sets the user
   * deleted by hand stops offering to replace them.
   */
  const hasPreviousRun: Readable<boolean> = svelteDerived(
    [state, selection.sets],
    ([$st, $sets]) => {
      const live = new Set($sets.map((s) => s.id));
      return [...$st.rawSetIds, ...$st.resultSetIds].some((id) => live.has(id));
    },
  );

  /**
   * Run the whole thing: preflight → `M × n_exc` captures → `calc_bla` →
   * result sets. Resolves when the run settles (done / cancelled / error);
   * failures land in `state.error`, never as a rejection, so a card click
   * handler needs no try/catch.
   *
   * Per-capture duration is staged onto the acquire store (`durationS`) — the
   * only way `record()` takes a length — and the user's own value is restored
   * in a `finally`, on every exit path including cancel and error. The armed
   * pretrigger is disarmed and restored the same way.
   *
   * `opts.seed` pins the run's PRNG seed (tests / a deliberate repeat);
   * omitted, a fresh uint32 is drawn — before validation, so the peak guard
   * checks the waveforms this run will actually play.
   */
  async function start(opts: { seed?: number } = {}): Promise<void> {
    const phase = get(state).phase;
    if (phase === 'running' || phase === 'analysing') return;

    // uint32 seed: recorded in the run spec, so every waveform of the run can
    // be regenerated from metadata alone.
    const seed = opts.seed != null
      ? opts.seed >>> 0
      : Math.floor(Math.random() * 4294967296) >>> 0;
    const input = preflightInput(seed);
    const results = preflightBla(input);
    const blocking = firstBlaError(results);
    if (blocking) {
      // A refused preflight captured NOTHING, so the previous run's sets are
      // still exactly as they were — keep pointing at them. Wiping the ids here
      // stranded the last run's raw captures: they stay HIDDEN in the tray, and
      // the card gates its "show raw captures" button on `rawSetIds`, so the
      // one control that reveals them disappeared because an unrelated new run
      // failed to start.
      state.update((st) => ({
        ...st, phase: 'error', error: blocking, m: 0, e: 0, notes: [],
      }));
      return;
    }
    const notes = results.filter((c) => c.ok).map((c) => c.reason);

    const d = get(design);
    const v = get(values);
    const rail = input.outputRail;
    const runSpec: BlaRunSpec = {
      multisine: {
        n_samples: v.periodSamples,
        k1: v.k1,
        k2: v.k2,
        p_periods: Math.trunc(d.P),
        t_periods: Math.trunc(d.tPeriods),
        seed,
        amp_rms: d.ampRms,
        n_exc: v.nExc,
        M: Math.trunc(d.M),
      },
      x_mode: v.xMode,
      x_channels: v.xMode === 'commanded' ? null : v.xChannels.slice(),
      resp_channels: v.respChannels.slice(),
      fs: v.fsEff,
    };

    cancelRequested = false;

    // ---- run semantics: replace the previous run, or keep both ----
    // REPLACE first, so the name scan below sees a tray with the old run
    // already gone and the new run keeps the plain test name. That ordering
    // also closes the silent-orphan path the old code had: resetting the
    // state dropped the previous run's rawSetIds while leaving those sets
    // HIDDEN, and the card's "show raw captures" button — the only control
    // that revealed them — moved to the new run.
    const previous = [...get(state).rawSetIds, ...get(state).resultSetIds];
    if (get(runMode) === 'replace' && previous.length && actions.removeBlaRun) {
      actions.removeBlaRun(previous);
    }
    // KEEP BOTH (or a stale run this store no longer tracks) ⇒ suffix the
    // names so the two runs are told apart in the tray and the legend.
    const baseName = blaRunBaseName(d.testName, get(selection.sets).map((s) => s.name));

    // Clear any previous run's results up front (still 'idle'), so a failure
    // during staging can't report itself on top of stale ids.
    state.set({
      ...emptyState(),
      runSpec,
      notes,
      captures: plannedCaptures(runSpec.multisine.M, v.nExc),
      runStartedAt: Date.now(),
    });
    const userDurationS = get(acquire.settings).durationS;
    const wasArmed = !!get(acquire.bridgeConfig).pretrigArmed;
    const rawSetIds: number[] = [];
    // Payloads in the exact `[(m, e) for m in … for e in …]` order
    // `analysis.calculate_bla` requires — a plain list carries the order, so
    // nothing tags the captures; building it here IS the contract.
    const captures: { time_axis: Float64Array; time_data: Float64Array; n_channels: number; fs: number }[] = [];

    try {
      // Stage the device BEFORE announcing the run, so a subscriber that reacts
      // to `phase === 'running'` already sees the run's own duration and a
      // disarmed pretrigger rather than the user's standing values.
      if (wasArmed) acquire.patchBridge({ pretrigArmed: false });
      acquire.patch({ durationS: v.captureS });
      state.update((st) => ({ ...st, phase: 'running' }));

      for (let m = 0; m < runSpec.multisine.M; m++) {
        for (let e = 0; e < v.nExc; e++) {
          if (cancelRequested) break;
          // The grid's single write point for 'running' — one cell in flight
          // at a time, by construction of this loop.
          state.update((st) => ({ ...st, m, e, captures: markBlaCapture(st.captures, m, e, 'running') }));
          const rec = await acquire.record({
            outputOverride: stimulusFor(d, v, seed, m, e, rail),
          });
          // The advice differs by path, because only ONE of them self-heals.
          // BRIDGE: a DSA device coerces an off-ladder rate (8000 → 8533.33 Hz)
          // and the coerced value reaches the store on the configure
          // round-trip, so by the time this throws `fsEff` already reads the
          // true rate and a second Start is designed correctly — "start again"
          // is real advice, and "set the sample rate" would not even be
          // possible (48019.2077 Hz is not a typeable ladder value).
          // WEB AUDIO: there is no coerced-fs channel at all (`onConfigured`
          // is bridge-only), so `fsEff` will report the same requested rate
          // forever and retrying loops. The user has to move the requested
          // rate onto what the browser actually opened.
          if (Math.abs(rec.fs - v.fsEff) > BLA_FS_TOLERANCE_HZ) {
            const lead = `The device captured at ${rec.fs} Hz but the run was designed for `
              + `${v.fsEff} Hz — the ${v.periodSamples}-sample period would not be a whole `
              + 'number of periods at that rate. ';
            throw new Error(lead + (get(acquire.kind) === 'bridge'
              ? 'The real rate is known now, so simply start the run again; the design readouts '
                + '(period, band, run time) already follow it.'
              : `This browser opened the device at ${rec.fs} Hz: set the sample rate to `
                + `${rec.fs} Hz in Setup, then start the run.`));
          }
          const item = recordingToItem(
            rec, `${baseName} r${m + 1}e${e + 1}`, acquire.lastRecordingMeta,
          );
          // M × n_exc raw sets would flood the tray/legend, so they land
          // hidden — ATOMICALLY (`hidden: true`), not by hiding them after the
          // fact: a post-hoc hide leaves one frame in which the capture is a
          // visible new time line, which the axis notifier acts on (a pointless
          // time-view rescale per capture). The card offers a "show raw
          // captures" toggle.
          const setId = actions.addRecordedSet(item, { hidden: true });
          rawSetIds.push(setId);
          state.update((st) => ({
            ...st,
            rawSetIds: rawSetIds.slice(),
            captures: markBlaCapture(st.captures, m, e, 'done'),
          }));
          captures.push({
            time_axis: rec.timeAxis, time_data: rec.data, n_channels: rec.nChannels, fs: rec.fs,
          });
        }
        if (cancelRequested) break;
      }

      if (cancelRequested) {
        // Whatever landed stays: the raw sets are ordinary time sets the user
        // can keep, plot or save.
        state.update((st) => ({ ...st, phase: 'cancelled' }));
        return;
      }

      state.update((st) => ({ ...st, phase: 'analysing' }));
      // MANDATORY: without this kick a session whose FIRST compute is a BLA
      // run parks forever (the engine never boots — see calcDamping).
      engine.boot();
      const res = await engine.enqueue<unknown[]>('calc_bla', {
        time_arrays: captures,
        run_spec: runSpec,
      });
      const list = Array.isArray(res) ? res : [];
      const resultSetIds = actions.addBlaSets(list, {
        names: list.map((_, q) => resultName(baseName, v, q)),
        // Name each line after the RESPONSE CHANNEL it came from. `resp ch N`,
        // not the default `ch_N`: a BLA set's columns are a SUBSET of the
        // capture's channels (the measured drives are not responses), so a
        // bare `ch_1` on the second column would read as input channel 1 when
        // it is in fact channel 2. The prefix says which role the number has.
        channelLabels: v.respChannels.map((c) => `resp ch ${c}`),
      });
      state.update((st) => ({ ...st, phase: 'done', resultSetIds }));
      viewState?.activate('tf');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // The Acquire card's own Cancel rejects the in-flight capture with
      // 'cancelled' — that is a cancellation, not a failure.
      state.update((st) => {
        // The capture that threw never landed, so its cell goes back to
        // pending rather than staying 'running' — a cell left mid-fill after
        // the run stopped reads as "still going" forever.
        const captures = st.captures.map((c) => (c.status === 'running' ? { ...c, status: 'pending' as const } : c));
        return msg === 'cancelled'
          ? { ...st, phase: 'cancelled', captures }
          : { ...st, phase: 'error', error: msg, captures };
      });
    } finally {
      acquire.patch({ durationS: userDurationS });
      if (wasArmed) acquire.patchBridge({ pretrigArmed: true });
    }
  }

  /**
   * Ask the run to stop. The capture in flight COMPLETES (cancelling a
   * half-played multisine would leave a truncated set for no benefit); the
   * loop then stops before the next one and the phase becomes `cancelled`.
   */
  function cancel(): void {
    cancelRequested = true;
  }

  /** Show or hide every raw capture of the last run (the card's toggle). */
  function setRawVisible(visible: boolean): void {
    for (const id of get(state).rawSetIds) selection.setSetVisible(id, visible);
  }

  /** Patch design fields (the card's inputs). */
  function patch(p: Partial<BlaDesign>): void {
    design.update((d) => ({ ...d, ...p }));
  }

  /** Replace the output/excitation table. */
  function setOutputs(rows: BlaOutputRow[]): void {
    design.update((d) => ({ ...d, outputs: rows.map((r) => ({ ...r })) }));
  }

  /**
   * Clear a finished/failed run back to idle, keeping the design for another
   * run. The landed SETS are not deleted — but the raw captures are UNHIDDEN
   * first: the store is about to forget their ids, and with them the card's
   * "show raw captures" button, so leaving them hidden would put sets in the
   * tray that this card can no longer reveal. (They are ordinary time sets, so
   * unhiding them adds nothing to the TF view the run just jumped to; a tray
   * card click hides them again.)
   */
  function reset(): void {
    cancelRequested = false;
    setRawVisible(true);
    state.set(emptyState());
  }

  /**
   * Set the frequency resolution from EITHER of the card's two linked boxes
   * (round-11 P6). Both write the same design field — `dfHz` is the stored
   * primitive — but a typed PERIOD is first quantised to a whole number of
   * samples and converted back, so the pair the card shows is always a
   * consistent, achievable `(Δf, T)`.
   *
   * @param quantity Which box was edited.
   * @param value Hz for `'df'`, seconds for `'period'`.
   */
  function setPeriod(quantity: BlaPeriodQuantity, value: number): void {
    if (quantity === 'df') {
      patch({ dfHz: value });
      return;
    }
    const r = resolveBlaPeriod('period', value, get(fsEff));
    // A sub-sample period resolves to N = 0 and no meaningful Δf; keep the
    // request visible as a zero so preflight reports it against the field
    // rather than silently restoring the old value.
    patch({ dfHz: r.periodSamples > 0 ? roundForPeriodBox(r.dfHz) : 0 });
  }

  return {
    design,
    state: { subscribe: state.subscribe } as Readable<BlaState>,
    // The effective rate is not exposed on its own: it is already `values.fsEff`
    // (with everything derived from it), and a second copy would be one more
    // thing for a consumer to read the stale half of.
    values,
    checks,
    /** Replace-vs-keep for the NEXT run (the card's Segmented control). */
    runMode,
    /** Whether a previous run's sets are still present (gates that control). */
    hasPreviousRun: { subscribe: hasPreviousRun.subscribe } as Readable<boolean>,
    patch,
    setPeriod,
    setOutputs,
    start,
    cancel,
    setRawVisible,
    reset,
  };
}
