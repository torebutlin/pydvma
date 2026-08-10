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
  deviceCapsFor,
  outputCapable,
  outputDevices,
  supportsSharedClockAo,
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
 * seed (NI shared-clock only — see {@link supportsSharedClockAo}).
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

/** Live run state (the card's progress + results surface). */
export interface BlaState {
  phase: BlaPhase;
  /** Realisation index of the capture in flight (0-based). */
  m: number;
  /** Experiment index of the capture in flight (0-based). */
  e: number;
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
 * One preflight finding. `ok: false` is a HARD failure (the run refuses to
 * start); `ok: true` is an advisory the run acts on and reports (currently
 * only the pretrigger auto-disarm). A clean design yields an EMPTY list.
 */
export interface BlaCheck {
  ok: boolean;
  /** Stable identifier for tests / the card's per-field highlighting. */
  code: string;
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
   * The seed the run will actually use. The peak guard checks the REAL
   * waveforms, so the seed has to be drawn before validation, not after —
   * every realisation's crest factor depends on it. Irrelevant (and left at
   * `0`) when the peak check is skipped.
   */
  seed: number;
}

/** The actions surface a BLA run needs (structural, so tests stay light). */
export interface BlaActions {
  addRecordedSet(item: DvmaItem): number;
  addBlaSets(
    results: unknown[],
    opts?: { names?: string[]; channelLabels?: string[]; timestring?: string },
  ): number[];
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
  return { phase: 'idle', m: 0, e: 0, error: '', runSpec: null, rawSetIds: [], resultSetIds: [], notes: [] };
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
 * Effective peak rail the generated waveform must stay inside, mirroring
 * `MySettings.output_vmax()`: the NI analog-output rail (the staged
 * `output_VmaxNI`, else the device's `ao_vmax`, else pydvma's 5 V default) on
 * an NI output, and `1` everywhere else — `VmaxSC` defaults to 1.0 on the
 * soundcard path and the browser's `AudioBuffer` rail is ±1.
 */
export function outputRailFor(
  providerKind: 'webaudio' | 'bridge',
  caps: BridgeCaps | null,
  cfg: BridgeConfig,
  inputDeviceId: string,
): number {
  if (providerKind !== 'bridge') return 1;
  const outDev = cfg.outputDeviceId || inputDeviceId;
  const sep = outDev.indexOf(':');
  const driver = sep >= 0 ? outDev.slice(0, sep) : outDev;
  if (driver !== 'nidaq') return 1;
  return cfg.outputVmaxNI ?? deviceCapsFor(caps, outDev)?.ao_vmax ?? PYDVMA_DEFAULT_VMAX;
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
 * - **commanded x** — only when the caps PROVE an NI shared clock on the same
 *   device at a matched rate; otherwise per-capture start jitter corrupts
 *   σ²_NL, so the fix is to measure the drive on an input channel.
 * - **pretrigger** — an advisory, not a failure: the run disarms it (a BLA
 *   capture is a fixed-length free-run window, and an armed capture would
 *   start at a threshold crossing somewhere inside the transient).
 * - **peak guard** — the crest factor varies per `(m, e)`, so a level that
 *   passes at (0,0) can clip at (3,1); generating every waveform up front
 *   turns a mid-run failure into a pre-run message. COST: this is
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
  const fail = (code: string, reason: string) => out.push({ ok: false, code, reason });

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
  if (values.xMode === 'commanded') {
    const synced = input.providerKind === 'bridge'
      && supportsSharedClockAo(input.caps, input.inputDeviceId, input.outputDeviceId)
      && !(input.stagedOutputFs != null
        && Math.abs(input.stagedOutputFs - input.requestedFs) > BLA_FS_TOLERANCE_HZ)
      && !input.lpfOn;
    if (!synced) {
      fail('commanded-sync', 'Commanded drive needs a hardware-synced NI output (AO and AI on the '
        + 'same device, sharing the sample clock at one rate) — measure the drive on an input '
        + 'channel instead.');
    }
  }
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
              limit: input.outputRail,
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
      outputRail: outputRailFor(kind, caps, cfg, s.deviceId),
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

  /** Display name for excitation `q`'s result set. */
  function resultName(d: BlaDesign, v: BlaDerivedValues, q: number): string {
    const via = v.xMode === 'commanded' ? 'commanded' : `via ch${v.xChannels[q]}`;
    return `${d.testName} BLA q${q + 1} (${via})`;
  }

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
      state.set({ ...emptyState(), phase: 'error', error: blocking });
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
    // Clear any previous run's results up front (still 'idle'), so a failure
    // during staging can't report itself on top of stale ids.
    state.set({ ...emptyState(), runSpec, notes });
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
          state.update((st) => ({ ...st, m, e }));
          const rec = await acquire.record({
            outputOverride: stimulusFor(d, v, seed, m, e, rail),
          });
          if (Math.abs(rec.fs - v.fsEff) > BLA_FS_TOLERANCE_HZ) {
            throw new Error(
              `The device captured at ${rec.fs} Hz but the run was designed for ${v.fsEff} Hz — `
              + `the ${v.periodSamples}-sample period would not be a whole number of periods at `
              + 'that rate. Set the sample rate to the rate the device actually runs and start again.',
            );
          }
          const item = recordingToItem(
            rec, `${d.testName} r${m + 1}e${e + 1}`, acquire.lastRecordingMeta,
          );
          const setId = actions.addRecordedSet(item);
          // M × n_exc raw sets would flood the tray/legend, so they land
          // hidden; the card offers a "show raw captures" toggle.
          selection.setSetVisible(setId, false);
          rawSetIds.push(setId);
          state.update((st) => ({ ...st, rawSetIds: rawSetIds.slice() }));
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
        names: list.map((_, q) => resultName(d, v, q)),
        channelLabels: v.respChannels.map((c) => `ch_${c}`),
      });
      state.update((st) => ({ ...st, phase: 'done', resultSetIds }));
      viewState?.activate('tf');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      // The Acquire card's own Cancel rejects the in-flight capture with
      // 'cancelled' — that is a cancellation, not a failure.
      state.update((st) => msg === 'cancelled'
        ? { ...st, phase: 'cancelled' }
        : { ...st, phase: 'error', error: msg });
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

  /** Clear a finished/failed run back to idle (leaves landed sets alone). */
  function reset(): void {
    cancelRequested = false;
    state.set(emptyState());
  }

  return {
    design,
    state: { subscribe: state.subscribe } as Readable<BlaState>,
    values,
    checks,
    fsEff,
    patch,
    setOutputs,
    start,
    cancel,
    setRawVisible,
    reset,
  };
}
