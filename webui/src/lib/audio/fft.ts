/**
 * Minimal radix-2 FFT for the Live oscilloscope's frequency pane
 * (Plan 2 — Live tab).
 *
 * The analysis app's spectra go through pydvma/pyodide, but the Live
 * scope needs a spectrum computed *in the browser*, per animation frame,
 * from the monitor ring-buffer snapshot — pyodide is far too heavy for a
 * 30–60 fps hot path.  This is a small, self-contained, dependency-free
 * radix-2 Cooley–Tukey transform plus a one-sided amplitude-spectrum
 * helper with an optional Hann window.
 *
 * It is deliberately NOT a general spectral-analysis kit: it operates on
 * power-of-two lengths only and is tuned for real-time display, not
 * measurement accuracy (that is the analysis FFT card's job).
 */

/** Largest power of two that is ≤ `n` (returns 1 for `n` < 1). */
export function prevPow2(n: number): number {
  if (n < 1) return 1;
  let p = 1;
  while (p * 2 <= n) p *= 2;
  return p;
}

/** Smallest power of two that is ≥ `n` (returns 1 for `n` ≤ 1). */
export function nextPow2(n: number): number {
  let p = 1;
  while (p < n) p *= 2;
  return p;
}

/**
 * Hann window of length `n`: `w[i] = 0.5 (1 − cos(2πi/(n−1)))`.  Reduces
 * spectral leakage so a live tone shows a clean peak rather than a smear.
 */
export function hannWindow(n: number): Float64Array {
  const w = new Float64Array(n);
  if (n === 1) { w[0] = 1; return w; }
  for (let i = 0; i < n; i++) w[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (n - 1)));
  return w;
}

/**
 * In-place iterative radix-2 Cooley–Tukey FFT.  `re`/`im` carry the real
 * and imaginary parts of the input and, on return, of the transform
 * `X[k] = Σ x[n] e^{−2πi kn/N}`.  Both arrays MUST be the same length and
 * that length MUST be a power of two (throws otherwise).
 */
export function fftRadix2(re: Float64Array, im: Float64Array): void {
  const n = re.length;
  if (n <= 1) return;
  if ((n & (n - 1)) !== 0) throw new Error(`fftRadix2: length ${n} is not a power of two`);

  // Bit-reversal permutation.
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      const tr = re[i]; re[i] = re[j]; re[j] = tr;
      const ti = im[i]; im[i] = im[j]; im[j] = ti;
    }
  }

  // Danielson–Lanczos butterflies, doubling the transform length each pass.
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wr = Math.cos(ang), wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1, ci = 0;               // twiddle factor, updated per k
      const half = len >> 1;
      for (let k = 0; k < half; k++) {
        const a = i + k, b = a + half;
        const tr = re[b] * cr - im[b] * ci;
        const ti = re[b] * ci + im[b] * cr;
        re[b] = re[a] - tr; im[b] = im[a] - ti;
        re[a] += tr;        im[a] += ti;
        const ncr = cr * wr - ci * wi;   // advance twiddle: c *= w
        ci = cr * wi + ci * wr; cr = ncr;
      }
    }
  }
}

/** Result of {@link magnitudeSpectrum}. */
export interface SpectrumResult {
  /** One-sided amplitude spectrum, length `size / 2 + 1` (bin 0 = DC). */
  mag: Float64Array;
  /** FFT length actually used (a power of two ≤ input length). */
  size: number;
}

/**
 * One-sided amplitude spectrum of a real signal for the Live scope.
 *
 * Uses the most recent `prevPow2(samples.length)` samples so the
 * transform stays radix-2 without an explicit resample, and applies a
 * Hann window by default (matching the analysis FFT card's default).
 * Amplitudes are scaled so a full-scale sinusoid reads ≈ its peak
 * amplitude: bin 0 (DC) and the Nyquist bin by `1/N`, interior bins by
 * `2/N`.  When Hann-windowed the coherent-gain correction `N/Σw` is
 * folded in so windowed and un-windowed amplitudes stay comparable.
 *
 * Returns an empty spectrum for inputs shorter than 2 samples.
 */
export function magnitudeSpectrum(
  samples: Float32Array | Float64Array | number[],
  applyHann = true,
): SpectrumResult {
  const total = samples.length;
  if (total < 2) return { mag: new Float64Array(1), size: 1 };

  const size = prevPow2(total);
  const start = total - size;            // keep the most recent `size` samples
  const re = new Float64Array(size);
  const im = new Float64Array(size);

  let coherentGain = 1;
  if (applyHann) {
    const w = hannWindow(size);
    let wsum = 0;
    for (let i = 0; i < size; i++) { re[i] = samples[start + i] * w[i]; wsum += w[i]; }
    coherentGain = wsum > 0 ? size / wsum : 1;
  } else {
    for (let i = 0; i < size; i++) re[i] = samples[start + i];
  }

  fftRadix2(re, im);

  const half = size >> 1;
  const mag = new Float64Array(half + 1);
  for (let k = 0; k <= half; k++) {
    const a = (Math.hypot(re[k], im[k]) / size) * coherentGain;
    mag[k] = (k === 0 || k === half) ? a : a * 2;
  }
  return { mag, size };
}

/** Options for {@link welchPsd}. */
export interface WelchOptions {
  /** Sample rate in Hz — sets the PSD's per-Hz normalisation and axis. */
  fs: number;
  /**
   * Target number of averaging segments.  The segment length is derived
   * from this and the input length assuming 50 % overlap
   * (`nperseg ≈ 2·L/(segments+1)`, rounded DOWN to a power of two), so a
   * larger count trades frequency resolution for a smoother estimate.
   * Clamped to ≥ 1; the *actual* segments averaged is returned as
   * `nSegments` (it can differ once `nperseg` is snapped to a power of two).
   */
  segments?: number;
  /** Apply a Hann window per segment (default true — reduces leakage). */
  applyHann?: boolean;
}

/** Result of {@link welchPsd}. */
export interface WelchResult {
  /**
   * One-sided power spectral density, length `nperseg/2 + 1`, in
   * units of (signal-unit)²/Hz.  Bin 0 (DC) and Nyquist are NOT doubled;
   * interior bins carry the one-sided ×2 factor, so
   * `Σ psd[k]·df ≈ mean-square(signal)` (Parseval for the density scaling).
   */
  psd: Float64Array;
  /** Matching one-sided frequency axis in Hz (`freqs[k] = k·df`). */
  freqs: Float64Array;
  /** Segment length actually used (a power of two ≤ input length). */
  nperseg: number;
  /** Number of overlapping segments actually averaged (≥ 1). */
  nSegments: number;
  /** Frequency resolution in Hz (`fs / nperseg`). */
  df: number;
}

/**
 * Welch power-spectral-density estimate for the Live scope's averaged
 * FFT ("PSD") mode.
 *
 * The window is split into 50 %-overlapping segments of length `nperseg`
 * (a power of two derived from the requested `segments` count), each
 * Hann-windowed and transformed, and the modified periodograms are
 * averaged.  This trades frequency resolution for a much lower-variance
 * spectrum than a single instantaneous FFT — the standard tool for
 * reading a noise floor or a steady tone's level.
 *
 * Scaling is scipy-style "density": each periodogram is
 * `|X[k]|² / (fs·Σw²)`, one-sided (interior bins ×2), so the result is a
 * true PSD in unit²/Hz and integrates back to the signal's mean square.
 * For white noise of variance σ² the interior PSD is flat at ≈ 2σ²/fs.
 *
 * Returns a length-1 empty PSD for inputs shorter than 2 samples or a
 * non-positive `fs`.
 */
export function welchPsd(
  samples: Float32Array | Float64Array | number[],
  opts: WelchOptions,
): WelchResult {
  const L = samples.length;
  const fs = opts.fs;
  if (L < 2 || !(fs > 0)) {
    return { psd: new Float64Array(1), freqs: new Float64Array(1), nperseg: 1, nSegments: 0, df: 0 };
  }
  const applyHann = opts.applyHann ?? true;
  const target = Math.max(1, Math.floor(opts.segments ?? 4));

  // Segment length from the target count assuming 50 % overlap, snapped
  // DOWN to a power of two and never longer than the input.
  let nperseg = prevPow2(Math.floor((2 * L) / (target + 1)));
  nperseg = Math.max(2, Math.min(nperseg, prevPow2(L)));
  const step = Math.max(1, nperseg >> 1); // 50 % overlap
  const half = nperseg >> 1;

  // Window + its power Σw² for the density normalisation.
  const w = applyHann ? hannWindow(nperseg) : null;
  let U = nperseg;
  if (w) { U = 0; for (let i = 0; i < nperseg; i++) U += w[i] * w[i]; }
  const norm = fs * (U || 1);

  const acc = new Float64Array(half + 1);
  const re = new Float64Array(nperseg);
  const im = new Float64Array(nperseg);
  let nSeg = 0;
  for (let start = 0; start + nperseg <= L; start += step) {
    im.fill(0);
    for (let i = 0; i < nperseg; i++) {
      const v = samples[start + i];
      re[i] = w ? v * w[i] : v;
    }
    fftRadix2(re, im);
    for (let k = 0; k <= half; k++) {
      const p = (re[k] * re[k] + im[k] * im[k]) / norm;
      acc[k] += (k === 0 || k === half) ? p : 2 * p;
    }
    nSeg++;
  }

  const psd = new Float64Array(half + 1);
  const inv = nSeg > 0 ? 1 / nSeg : 0;
  for (let k = 0; k <= half; k++) psd[k] = acc[k] * inv;

  const df = fs / nperseg;
  const freqs = new Float64Array(half + 1);
  for (let k = 0; k <= half; k++) freqs[k] = k * df;

  return { psd, freqs, nperseg, nSegments: nSeg, df };
}
