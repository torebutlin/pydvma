/**
 * Output-stimulus signal generator (browser / Web Audio path).
 *
 * A faithful TypeScript port of pydvma's `acquisition.signal_generator`
 * (`pydvma/acquisition.py:331`) — the waveform pydvma plays out of the AO
 * device during a `log_data(..., output=y)` capture.  It is used by the Web
 * Audio provider (round-5 item 10: "make the browser mode as full-functioning
 * as sensible") to drive an `AudioBufferSourceNode` while recording, so a
 * no-install browser session can excite a system and measure its response the
 * same way the Qt / `pydvma serve` app does.
 *
 * ── Parity with pydvma (`signal_generator`) ───────────────────────────────
 * - **sweep**: `amplitude * scipy.signal.chirp(t, f0, T, f1)` — a LINEAR
 *   chirp (scipy's default `method='linear'`, `phi=0`), so the sample at time
 *   `t` is `amp·cos(2π(f0·t + ½·(f1−f0)/T·t²))`.  The instantaneous frequency
 *   is `f0 + (f1−f0)·t/T`: exactly `f0` at `t=0` and `f1` at `t=T`.  `f=[f1,f2]`
 *   are the sweep endpoints (Hz); when omitted pydvma uses `[0, fs/2]`.
 * - **uniform** ("white" in the UI): `uniform(−amp, amp)`; with a band it is
 *   band-pass filtered then renormalised so its RMS equals `amp`.
 * - **gaussian**: truncated normal, `scale=amp`, clipped to ±`limit`; with a
 *   band it is band-pass filtered then renormalised so its RMS equals `amp`.
 * - All three are multiplied by a raised-cosine fade-in/out window
 *   (`T_ramp = min(T/10, 0.1)`) and finally clamped to ±`limit`.
 *
 * ── Deliberate, documented divergences (browser has no calibrated DAC) ────
 * - **Amplitude is normalised, not volts.**  pydvma's `amplitude` is in volts
 *   and its safety `limit` is `settings.output_vmax()`.  The browser output is
 *   the ±1 float an `AudioBuffer` expects, so here `amp` is a normalised peak
 *   (0..1) and `limit` defaults to `1`.  The Acquire card still labels it
 *   "amp (V)"; on the Web Audio path that value is interpreted as a normalised
 *   gain and clamped to 1.0 at play time.
 * - **Band-pass filter is not byte-identical.**  pydvma uses a 3rd-order
 *   Butterworth `filtfilt` (SciPy).  This port cascades a 2nd-order
 *   Butterworth high-pass at `f1` and low-pass at `f2`, each applied
 *   forward-and-back (zero-phase), matching pydvma's `padtype=None` (no edge
 *   padding).  The RMS-normalisation makes the tested amplitude/RMS property
 *   exact regardless; only the exact spectral roll-off differs.  Byte-identity
 *   is not required for an un-calibrated browser stimulus — only the measured
 *   RESPONSE (captured from the mic) matters, and that is recorded live.
 *
 * The generator is pure and deterministic given an injected `rng` (uniform
 * `[0,1)`), so the noise paths are unit-testable.
 *
 * ── Multisine (Schoukens BLA excitation) ──────────────────────────────────
 * This module also carries {@link generateMultisine}, a SEPARATE signal
 * family for the Schoukens random-phase-multisine BLA workflow (design:
 * `dev/plans/2026-08-10-schoukens-bla-design.md`) — the TypeScript twin of
 * pydvma's `multisine_generator` (`pydvma/acquisition.py:609`). It does not
 * reuse `generateStimulus`: no fade window, no peak rescale, sample-domain
 * (not time-domain) spec, and a different, dedicated PRNG. See its own
 * docstring below for the signal law.
 */

export type StimulusType = 'sweep' | 'uniform' | 'gaussian';

/** Parameters for {@link generateStimulus}. */
export interface StimulusSpec {
  /** Signal family — matches pydvma's `signal_generator` `sig` tokens. */
  type: StimulusType;
  /** Output sample rate in Hz. */
  fs: number;
  /** Duration in seconds. */
  durationS: number;
  /**
   * Target amplitude — a NORMALISED peak (0..1) for the browser DAC (pydvma's
   * volts have no meaning without a calibrated AO device).  For `sweep` it is
   * the peak; for the noise types it is the RMS after band-limiting (pydvma
   * renormalises), or the uniform half-range / gaussian scale when unbanded.
   */
  amp: number;
  /**
   * Frequency band `[f1, f2]` in Hz.  For `sweep` these are the chirp
   * endpoints (start / end frequency).  For the noise types they are the
   * pass-band corners; pass `null` (or a degenerate band) to skip filtering.
   */
  band?: [number, number] | null;
  /** Safety clamp (normalised full-scale).  Defaults to 1 (the ±1 AudioBuffer rail). */
  limit?: number;
  /** Uniform `[0,1)` source for the noise types.  Defaults to `Math.random`. */
  rng?: () => number;
}

/**
 * numpy `arange(0, T, 1/fs)` length — the sample count pydvma's generator
 * produces.  A tiny epsilon guards float overshoot so an exactly-divisible
 * `(T, fs)` (e.g. 1 s at 8 kHz → 8000) does not round up to 8001.
 */
export function stimulusLength(fs: number, durationS: number): number {
  return Math.max(0, Math.ceil(fs * durationS - 1e-9));
}

/**
 * Instantaneous frequency (Hz) of pydvma's linear sweep at time `t`:
 * `f0 + (f1 − f0)·t/T`.  Exactly `f0` at `t=0` and `f1` at `t=T` — the sweep
 * endpoints the round-5 task asks to verify.
 */
export function instantaneousFreqLinear(t: number, f0: number, f1: number, T: number): number {
  if (T <= 0) return f0;
  return f0 + ((f1 - f0) * t) / T;
}

/**
 * One sample of pydvma's linear chirp (unit amplitude) at time `t`:
 * `cos(2π(f0·t + ½·(f1−f0)/T·t²))` — scipy `chirp(..., method='linear',
 * phi=0)`.
 */
export function linearChirpSample(t: number, f0: number, f1: number, T: number): number {
  const phase = 2 * Math.PI * (f0 * t + (0.5 * (f1 - f0) / T) * t * t);
  return Math.cos(phase);
}

/**
 * Fill a unit-amplitude linear chirp over `N` samples at `fs`, sweeping `f0→f1`
 * across the scalar duration `T` (== `N`-sample window in pydvma, where the
 * chirp's `t1 = T`).  Returns `cos(phase)` per sample.
 */
export function linearChirp(N: number, fs: number, f0: number, f1: number, T: number): Float64Array {
  const y = new Float64Array(N);
  for (let n = 0; n < N; n++) y[n] = linearChirpSample(n / fs, f0, f1, T);
  return y;
}

/**
 * pydvma's raised-cosine fade window: `ones(N)` with a cosine ramp-up over the
 * first `N_ramp` samples and a matching ramp-down over the last `N_ramp`,
 * where `N_ramp = int(min(T/10, 0.1)·fs)`.  Endpoints are ≈0, so a stimulus
 * starts and ends smoothly (no click).  `N_ramp` is clamped to `⌊N/2⌋` so the
 * two ramps never overrun on very short buffers.
 */
export function raisedCosineWindow(N: number, fs: number, T: number): Float64Array {
  const win = new Float64Array(N).fill(1);
  const tRamp = Math.min(T / 10, 0.1);
  let nRamp = Math.floor(tRamp * fs);
  nRamp = Math.min(nRamp, Math.floor(N / 2));
  if (nRamp <= 0) return win;
  for (let i = 0; i < nRamp; i++) {
    // Ramp up 0→1 over [0, nRamp); ramp down 1→0 over the last nRamp.
    win[i] = 0.5 * (1 - Math.cos((i / nRamp) * Math.PI));
    win[N - nRamp + i] = 0.5 * (1 + Math.cos((i / nRamp) * Math.PI));
  }
  return win;
}

/** Root-mean-square of a signal. */
export function rms(x: ArrayLike<number>): number {
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i] * x[i];
  return x.length ? Math.sqrt(s / x.length) : 0;
}

/** Max absolute value of a signal. */
function maxAbs(x: ArrayLike<number>): number {
  let m = 0;
  for (let i = 0; i < x.length; i++) { const a = Math.abs(x[i]); if (a > m) m = a; }
  return m;
}

// ---- Butterworth biquad band-limiting (2nd-order sections, zero-phase) ----

/** Biquad coefficients (normalised so `a0 = 1`). */
export interface Biquad {
  b0: number; b1: number; b2: number;
  a1: number; a2: number;
}

const BUTTER_Q = 1 / Math.SQRT2; // maximally-flat 2nd-order Butterworth

/** RBJ-cookbook 2nd-order Butterworth low-pass at cutoff `fc` (Hz). */
export function butterLowpass(fc: number, fs: number): Biquad {
  const w0 = (2 * Math.PI * fc) / fs;
  const cw = Math.cos(w0), sw = Math.sin(w0);
  const alpha = sw / (2 * BUTTER_Q);
  const a0 = 1 + alpha;
  return {
    b0: ((1 - cw) / 2) / a0,
    b1: (1 - cw) / a0,
    b2: ((1 - cw) / 2) / a0,
    a1: (-2 * cw) / a0,
    a2: (1 - alpha) / a0,
  };
}

/** RBJ-cookbook 2nd-order Butterworth high-pass at cutoff `fc` (Hz). */
export function butterHighpass(fc: number, fs: number): Biquad {
  const w0 = (2 * Math.PI * fc) / fs;
  const cw = Math.cos(w0), sw = Math.sin(w0);
  const alpha = sw / (2 * BUTTER_Q);
  const a0 = 1 + alpha;
  return {
    b0: ((1 + cw) / 2) / a0,
    b1: (-(1 + cw)) / a0,
    b2: ((1 + cw) / 2) / a0,
    a1: (-2 * cw) / a0,
    a2: (1 - alpha) / a0,
  };
}

/** Direct-form-I forward pass of one biquad (zero initial conditions). */
function lfilterBiquad(q: Biquad, x: ArrayLike<number>): Float64Array {
  const y = new Float64Array(x.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let n = 0; n < x.length; n++) {
    const xn = x[n];
    const yn = q.b0 * xn + q.b1 * x1 + q.b2 * x2 - q.a1 * y1 - q.a2 * y2;
    x2 = x1; x1 = xn; y2 = y1; y1 = yn;
    y[n] = yn;
  }
  return y;
}

/**
 * Zero-phase filtering (forward-then-reverse) of one biquad — the browser
 * analogue of SciPy `filtfilt(..., padtype=None)` (no edge padding).  Doubling
 * the pass halves the phase to zero and squares the magnitude response.
 */
export function filtfiltBiquad(q: Biquad, x: ArrayLike<number>): Float64Array {
  const fwd = lfilterBiquad(q, x);
  fwd.reverse();
  const back = lfilterBiquad(q, fwd);
  back.reverse();
  return back;
}

/**
 * Band-limit `x` to `[f1, f2]` with a high-pass∘low-pass Butterworth cascade,
 * each applied zero-phase.  Corners outside `(0, fs/2)` are skipped (a
 * degenerate band leaves the signal unfiltered), mirroring pydvma only
 * filtering when `f is not None` with a valid `Wn`.
 */
export function bandpass(x: Float64Array, f1: number, f2: number, fs: number): Float64Array {
  const nyq = fs / 2;
  let y = x;
  if (f1 > 0 && f1 < nyq) y = filtfiltBiquad(butterHighpass(f1, fs), y);
  if (f2 > 0 && f2 < nyq && f2 > f1) y = filtfiltBiquad(butterLowpass(f2, fs), y);
  return y;
}

// ---- noise sources ----

/** One standard-normal sample via Box–Muller from a uniform `[0,1)` source. */
function nextGaussian(rng: () => number): number {
  const u1 = Math.max(rng(), 1e-12);
  const u2 = rng();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

// ---- the generator ----

/**
 * Generate a single-channel output stimulus, faithfully following pydvma's
 * `signal_generator` (see the module docstring for the exact laws and the
 * documented browser divergences).  Returns the time axis `t` (seconds) and
 * the waveform `y` (normalised, |y| ≤ `limit`), both length
 * {@link stimulusLength}`(fs, durationS)`.
 */
export function generateStimulus(spec: StimulusSpec): { t: Float64Array; y: Float64Array } {
  const { type, fs, durationS: T } = spec;
  const amp = spec.amp;
  const limit = spec.limit ?? 1;
  const rng = spec.rng ?? Math.random;
  const N = stimulusLength(fs, T);

  const t = new Float64Array(N);
  for (let n = 0; n < N; n++) t[n] = n / fs;

  let y: Float64Array = new Float64Array(N);
  const band = spec.band ?? null;

  if (type === 'sweep') {
    const f0 = band ? band[0] : 0;
    const f1 = band ? band[1] : fs / 2;
    for (let n = 0; n < N; n++) y[n] = amp * linearChirpSample(t[n], f0, f1, T);
  } else if (type === 'uniform') {
    for (let n = 0; n < N; n++) y[n] = (rng() * 2 - 1) * amp; // uniform[-amp, amp]
    if (band) {
      y = bandpass(y, band[0], band[1], fs);
      const r = rms(y);
      if (r > 0) for (let n = 0; n < N; n++) y[n] = (amp * y[n]) / r; // RMS → amp
    }
  } else if (type === 'gaussian') {
    for (let n = 0; n < N; n++) {
      // Truncated normal, scale=amp, clipped to ±limit (pydvma uses truncnorm).
      let v = nextGaussian(rng) * amp;
      if (v > limit) v = limit; else if (v < -limit) v = -limit;
      y[n] = v;
    }
    if (band) {
      y = bandpass(y, band[0], band[1], fs);
      const r = rms(y);
      if (r > 0) for (let n = 0; n < N; n++) y[n] = (amp * y[n]) / r; // RMS → amp
      const m = maxAbs(y);
      if (m > limit) for (let n = 0; n < N; n++) y[n] = (limit * y[n]) / m;
    }
  } else {
    // Unknown type → silence (pydvma prints and returns zeros).
    return { t, y };
  }

  // Raised-cosine fade in/out.
  const win = raisedCosineWindow(N, fs, T);
  for (let n = 0; n < N; n++) y[n] *= win[n];

  // Final safety clamp: rescale so the peak never exceeds ±limit.
  const peak = maxAbs(y);
  if (peak > limit) for (let n = 0; n < N; n++) y[n] = (limit * y[n]) / peak;

  return { t, y };
}

// ---- multisine generator (Schoukens BLA excitation) ----------------------

/**
 * mulberry32 — a small, fast, deterministic 32-bit PRNG returning uniform
 * `[0,1)` floats from a `[0, 2^32)` integer seed.
 *
 * Deliberately NOT numpy-compatible: pydvma's twin (`multisine_generator`)
 * draws from `numpy.random.default_rng([seed, m])`, a different algorithm
 * entirely. That is fine by design — one path (this browser generator, or
 * the Python bridge/soundcard driver) produces every capture of a single
 * BLA run, and the analysis only ever reads the *measured* excitation `x`,
 * never the PRNG stream itself. What MUST match between the two twins is
 * the signal LAW (amplitude, rotation, periodicity — see
 * {@link generateMultisine}), not the phase values.
 *
 * Chosen for being tiny, dependency-free, and — critically — stable
 * forever: given the same 32-bit seed this returns the identical sequence
 * on every JS engine, for all time, which is what lets a saved
 * {@link MultisineSpec} reproduce the exact waveform from metadata alone.
 * This exact algorithm must never change.
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Mix a `(seed, m)` pair into a single 32-bit stream seed for
 * {@link mulberry32}. Realisation `m` gets its own independent phase draw
 * while `seed` stays the one value recorded in — and shared across — a
 * whole BLA run's metadata. The mixing constant `0x9E3779B9` is the
 * standard 32-bit golden-ratio "bit-spreading" multiplier; `Math.imul`
 * performs the multiplication with correct 32-bit wraparound (plain `*`
 * would lose precision for large `m`). This exact formula must never
 * change — a saved spec's reproducibility depends on it forever.
 */
export function multisineStreamSeed(seed: number, m: number): number {
  return (seed ^ Math.imul(m, 0x9e3779b9)) >>> 0;
}

/**
 * Parameters for {@link generateMultisine} — one (realisation, experiment)
 * capture's worth of Schoukens random-phase-multisine excitation. camelCase
 * here; the bridge message layer maps these to the snake_case wire keys
 * used by `pydvma_serve` (not this module's job).
 */
export interface MultisineSpec {
  /** Period length `N` — samples per period (also fixes Δf = fs/N given `fs`). */
  nSamples: number;
  /** Lowest excited DFT bin, inclusive. Integer, `1 <= k1 <= k2 <= floor((N-1)/2)`. */
  k1: number;
  /** Highest excited DFT bin, inclusive. Integer, `1 <= k1 <= k2 <= floor((N-1)/2)`. */
  k2: number;
  /** Steady-state periods captured per experiment (Schoukens' `P`). */
  pPeriods: number;
  /** Discarded transient periods played before the steady-state window (`n_trans`). */
  tPeriods: number;
  /** PRNG seed (uint32) recorded in metadata — reproduces the whole run's waveforms exactly. */
  seed: number;
  /** Realisation index (0-based) — every realisation draws fresh random phases. */
  m: number;
  /** Experiment index within a realisation (0-based), `0 <= e < nExc`. */
  e: number;
  /** Number of driven excitation channels in this realisation (Schoukens' `n_exc`). */
  nExc: number;
  /** Target per-channel RMS, NORMALISED `0..1` for the browser DAC (no calibrated AO device here). */
  ampRms: number;
  /** Peak guard rail, normalised full-scale. Defaults to `1` — the ±1 `AudioBuffer` rail. */
  limit?: number;
}

/**
 * Generate the Schoukens random-phase multisine excitation for one BLA
 * capture — the TypeScript twin of pydvma's `multisine_generator`
 * (`pydvma/acquisition.py:609`). Returns one `Float64Array` per excitation
 * channel (`spec.nExc` of them), each of length
 * `(spec.tPeriods + spec.pPeriods) * spec.nSamples`: `spec.tPeriods`
 * discarded transient periods followed by `spec.pPeriods` steady-state
 * periods, every one an EXACT repeat of a single generated period (exact
 * periodicity by construction — survives sample-rate coercion downstream,
 * unlike a time-domain design).
 *
 * `fs` is accepted only for API symmetry with {@link generateStimulus} and
 * so callers can derive a time axis (`t = arange(N_total)/fs`); the
 * waveform itself depends ONLY on `spec` — this generator is defined in
 * samples, not seconds (see the design doc rationale).
 *
 * ── Signal law (MUST match the Python twin exactly; the PRNG itself need
 * not — see {@link mulberry32}) ──
 * - Flat-amplitude lines on integer bins `k1..k2`: `A = ampRms·√(2/nLines)`,
 *   `nLines = k2 − k1 + 1`, identical for every line.
 * - Phases: uniform `[0, 2π)` per (channel, line), drawn from
 *   {@link mulberry32} seeded via {@link multisineStreamSeed}`(seed, m)` —
 *   channel-major order (all `nLines` phases of channel 0, then channel 1,
 *   …), mirroring the Python twin's `(n_exc, n_lines)` row-major draw from
 *   `default_rng([seed, m])`.
 * - Experiment rotation: channel `q`'s phases (every line) shift by
 *   `−2π·q·e/nExc` — the orthogonal DFT-matrix column that keeps each
 *   channel's amplitude spectrum identical across the `nExc` experiments of
 *   a realisation, and is what lets the BLA solve invert `X` per bin.
 * - One period: `y[n] = Σ_k A·cos(2π·k·n/N + φ_{q,k})`, summed directly in
 *   the time domain (`O(N·nLines)`; no FFT needed at these sizes).
 *
 * ── Peak guard ──
 * The peak is checked ONCE, globally across every channel's period (mirrors
 * the Python twin's `np.max(np.abs(period))` over the full `(n_exc, N)`
 * array). If it exceeds `spec.limit` (default `1`, the ±1 `AudioBuffer`
 * rail) this throws — NO silent rescale, NO fade window (either would break
 * exact periodicity, the entire point of a sample-domain design).
 *
 * @throws Error on any spec validation failure (see the {@link MultisineSpec}
 *   field docs) or a peak-guard violation (message names the peak and the limit).
 */
export function generateMultisine(spec: MultisineSpec, fs: number): Float64Array[] {
  void fs; // accepted for API symmetry / caller time-axis derivation only — see docstring
  const { nSamples: N, k1, k2, pPeriods, tPeriods, seed, m, e, nExc, ampRms } = spec;
  const limit = spec.limit ?? 1;

  const nOk = Number.isInteger(N) && N >= 1;
  const kOk =
    nOk &&
    Number.isInteger(k1) &&
    Number.isInteger(k2) &&
    1 <= k1 &&
    k1 <= k2 &&
    k2 <= Math.floor((N - 1) / 2);
  if (!kOk) {
    throw new Error(
      `multisine bins must satisfy 1 <= k1 <= k2 <= floor((N-1)/2) (got k1=${k1}, k2=${k2}, N=${N})`
    );
  }
  if (!Number.isInteger(nExc) || nExc < 1) {
    throw new Error(`multisine nExc must be an integer >= 1 (got ${nExc})`);
  }
  if (!Number.isInteger(tPeriods) || !Number.isInteger(pPeriods) || tPeriods + pPeriods < 1) {
    throw new Error(
      `multisine needs at least one period total: tPeriods + pPeriods must be >= 1 ` +
        `(got tPeriods=${tPeriods}, pPeriods=${pPeriods})`
    );
  }
  if (!Number.isInteger(e) || !(0 <= e && e < nExc)) {
    throw new Error(`multisine e must satisfy 0 <= e < nExc (got e=${e}, nExc=${nExc})`);
  }
  if (!Number.isInteger(m) || m < 0) {
    throw new Error(`multisine m must be a non-negative integer (got ${m})`);
  }
  if (!Number.isFinite(seed)) {
    throw new Error(`multisine seed must be a finite number (got ${seed})`);
  }

  const nLines = k2 - k1 + 1;
  const A = ampRms * Math.sqrt(2 / nLines);

  // Base phases: drawn once per (seed, m), channel-major, so a saved spec
  // reproduces the whole realisation (every experiment e) exactly.
  const rand = mulberry32(multisineStreamSeed(seed, m));
  const basePhases: number[][] = [];
  for (let q = 0; q < nExc; q++) {
    const row = new Array<number>(nLines);
    for (let i = 0; i < nLines; i++) row[i] = rand() * 2 * Math.PI;
    basePhases.push(row);
  }

  // DFT-matrix rotation: excitation q's phase shifts by -2*pi*q*e/n_exc on
  // every line — keeps the per-channel amplitude spectrum flat across all
  // nExc experiments of a realisation.
  const periods: Float64Array[] = [];
  let peak = 0;
  for (let q = 0; q < nExc; q++) {
    const rotation = (-2 * Math.PI * q * e) / nExc;
    const period = new Float64Array(N);
    for (let n = 0; n < N; n++) {
      let s = 0;
      for (let i = 0; i < nLines; i++) {
        const k = k1 + i;
        s += A * Math.cos((2 * Math.PI * k * n) / N + basePhases[q][i] + rotation);
      }
      period[n] = s;
      const a = Math.abs(s);
      if (a > peak) peak = a;
    }
    periods.push(period);
  }

  if (peak > limit) {
    throw new Error(
      `multisine peak ${peak.toPrecision(3)} exceeds the limit ±${limit} ` +
        `— lower ampRms.`
    );
  }

  // Tile each channel's single period (tPeriods + pPeriods) times — exact
  // repeats, so periodicity is exact by construction.
  const nPeriodsTotal = tPeriods + pPeriods;
  const nTotal = nPeriodsTotal * N;
  return periods.map((period) => {
    const full = new Float64Array(nTotal);
    for (let p = 0; p < nPeriodsTotal; p++) full.set(period, p * N);
    return full;
  });
}
