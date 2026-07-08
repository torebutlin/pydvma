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
