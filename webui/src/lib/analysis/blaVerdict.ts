/**
 * BLA verdict banding — turning the σ pair of a Schoukens BLA set into the one
 * sentence a lab user actually needs ("is this system linear at this level?").
 *
 * The inputs are the arrays `calculate_bla` returns: `sigmaNl` (per-realisation
 * NONLINEAR-DISTORTION standard deviation) and `sigmaN` (per-realisation
 * MEASUREMENT-NOISE standard deviation), both REAL and both in LINEAR FRF
 * units — the same units as `abs(tf_data)`. Everything here squares them
 * before comparing, because the physics is a VARIANCE comparison
 * (σ²_NL vs σ²_n) even though the stored arrays are standard deviations.
 *
 * The band split is LOG-spaced across the excited band: nonlinear distortion
 * is a broadband, level-dependent phenomenon whose behaviour changes by decade
 * rather than by linear frequency, and a BLA's frequency axis is exactly the
 * excited lines (`k·fs/N`), so a log split gives each decade a comparable say.
 * Medians (not means) summarise a band, so a single resonance line inside it
 * cannot flip the verdict.
 *
 * Nothing here plots or formats units; {@link summariseBlaVerdicts} composes the
 * card's per-excitation sentence from the band list.
 */

/** One log-spaced sub-band of the excited range, with its verdict. */
export interface BlaBandVerdict {
  /** Lowest excited frequency that fell in this band (Hz). */
  f1: number;
  /** Highest excited frequency that fell in this band (Hz). */
  f2: number;
  /** Median σ_NL over the band, in LINEAR FRF units (not squared). */
  sigmaNl: number;
  /** Median σ_n over the band, in LINEAR FRF units (not squared). */
  sigmaN: number;
  /**
   * Variance ratio `median(σ_NL)² / median(σ_n)²`. `Infinity` when the noise
   * median is zero and the distortion median is not (a noiseless synthetic
   * case); `0` when both are zero.
   */
  ratio: number;
  /** Whether {@link ratio} exceeds {@link BLA_NL_RATIO}. */
  nonlinear: boolean;
  /** Sentence fragment for this band alone. */
  verdict: string;
  /**
   * Excited lines that fell in the band. At least {@link MIN_BAND_LINES}
   * unless the whole excited range holds fewer than that — undersized bands
   * are folded into a neighbour before any verdict is computed.
   */
  count: number;
}

/**
 * Fewest excited lines a band may summarise. A median over one or two lines is
 * not a median — a single noisy line would decide the band — so a sparse band
 * is folded into its neighbour rather than reported on its own. Only a whole
 * excited range shorter than this yields a smaller band.
 */
export const MIN_BAND_LINES = 3;

/**
 * Variance ratio above which a band reads as distortion-dominated. σ²_NL is
 * the distortion in ONE realisation and σ²_n the noise in one realisation, so
 * equality (ratio 1) means "distortion is exactly at the noise floor" — where
 * neither term is separable in practice. A factor of 2 keeps a band from
 * flipping to "nonlinear" on the estimator's own scatter (σ²_NL is a
 * difference of two noisy variances and is itself noisy at small M).
 */
export const BLA_NL_RATIO = 2;

/** Verdict text for a band whose distortion sits at or below the noise floor. */
export const BLA_LINEAR_TEXT = 'linear at this level (averaging helps)';
/** Verdict text for a band where distortion dominates the noise. */
export const BLA_NONLINEAR_TEXT = 'nonlinearity dominates';
/** Advice appended once whenever any band is distortion-dominated. */
export const BLA_LEVEL_ADVICE = 'level-dependent, repeat at 2–3 amplitudes';

/** Median of a numeric list (assumes non-empty; even counts average the pair). */
function median(values: number[]): number {
  const v = values.slice().sort((a, b) => a - b);
  const n = v.length;
  const mid = n >> 1;
  return n % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

/**
 * Format a frequency for a verdict sentence: whole hertz from 100 Hz up (nobody
 * reads "813.4 Hz" as more informative than "813"), one decimal between 10 and
 * 100, two below that.
 */
export function fmtVerdictHz(f: number): string {
  if (!Number.isFinite(f)) return '?';
  if (f >= 100) return String(Math.round(f));
  if (f >= 10) return f.toFixed(1).replace(/\.0$/, '');
  return f.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
}

/**
 * Split the excited band into `nBands` log-spaced sub-bands and judge each one
 * by comparing the median distortion variance with the median noise variance.
 *
 * All three arrays are read positionally (element `i` of each describes the
 * same excited line) and only points where the frequency is finite and
 * positive and BOTH σ values are finite and non-negative take part — a BLA
 * whose arrays carry NaNs (an unexcited line that slipped through, a channel
 * with no response) simply contributes fewer points. Fewer usable points than
 * requested bands collapses the split, so a 2-line array yields at most 2
 * bands rather than empty ones, and any band left holding fewer than
 * {@link MIN_BAND_LINES} lines is folded into its neighbour so no verdict ever
 * rests on a one-line "median" — with a BLA's uniformly spaced excited lines
 * it is always the LOWEST log band that runs thin. Returns `[]` when nothing
 * is usable, which the caller renders as "no usable σ data" rather than as a
 * verdict.
 *
 * The frequency axis is assumed ASCENDING (`k·fs/N` by construction), so each
 * band's edges are its first and last line.
 *
 * @param freqAxis Excited-line frequencies (Hz), ascending.
 * @param sigmaNl Per-line σ_NL, LINEAR units (squared internally).
 * @param sigmaN Per-line σ_n, LINEAR units (squared internally).
 * @param nBands Requested sub-band count (default 4; clamped to ≥ 1).
 * @returns One entry per non-empty sub-band, ascending in frequency.
 */
export function blaVerdicts(
  freqAxis: ArrayLike<number>,
  sigmaNl: ArrayLike<number>,
  sigmaN: ArrayLike<number>,
  nBands = 4,
): BlaBandVerdict[] {
  const n = Math.min(freqAxis.length, sigmaNl.length, sigmaN.length);
  const f: number[] = [];
  const nl: number[] = [];
  const noise: number[] = [];
  for (let i = 0; i < n; i++) {
    const fi = freqAxis[i];
    const a = sigmaNl[i];
    const b = sigmaN[i];
    if (!Number.isFinite(fi) || fi <= 0) continue;
    if (!Number.isFinite(a) || a < 0 || !Number.isFinite(b) || b < 0) continue;
    f.push(fi);
    nl.push(a);
    noise.push(b);
  }
  if (!f.length) return [];

  let fMin = Infinity;
  let fMax = -Infinity;
  for (const v of f) {
    if (v < fMin) fMin = v;
    if (v > fMax) fMax = v;
  }
  // Never ask for more bands than there are lines to fill them, and never
  // fewer than one — a single-line array still deserves a verdict.
  const nb = Math.max(1, Math.min(Math.trunc(nBands) || 1, f.length));
  const span = Math.log(fMax / fMin);
  type Bin = { f: number[]; nl: number[]; noise: number[] };
  const bins: Bin[] = Array.from({ length: nb }, () => ({ f: [], nl: [], noise: [] }));
  for (let i = 0; i < f.length; i++) {
    // A degenerate span (all lines at one frequency) puts everything in band 0.
    const t = span > 0 ? Math.log(f[i] / fMin) / span : 0;
    const j = Math.min(nb - 1, Math.max(0, Math.floor(t * nb)));
    bins[j].f.push(f[i]);
    bins[j].nl.push(nl[i]);
    bins[j].noise.push(noise[i]);
  }

  // Drop empties and fold anything too thin to carry a meaningful median into
  // the band ABOVE it — one forward pass, because a band only ever absorbs its
  // successor. `push` into the accumulator keeps everything ascending, since
  // the bands themselves are in frequency order.
  const absorb = (into: Bin, from: Bin): void => {
    into.f = into.f.concat(from.f);
    into.nl = into.nl.concat(from.nl);
    into.noise = into.noise.concat(from.noise);
  };
  const kept: Bin[] = [];
  for (const bin of bins) {
    if (!bin.f.length) continue;
    const prev = kept[kept.length - 1];
    if (prev && prev.f.length < MIN_BAND_LINES) absorb(prev, bin);
    else kept.push(bin);
  }
  // The TOP band has no successor to absorb, so an undersized one folds back
  // into its predecessor instead. A lone band is kept whatever its size —
  // there is nothing left to merge it with.
  if (kept.length > 1 && kept[kept.length - 1].f.length < MIN_BAND_LINES) {
    absorb(kept[kept.length - 2], kept[kept.length - 1]);
    kept.pop();
  }

  return kept.map((bin) => {
    const mNl = median(bin.nl);
    const mN = median(bin.noise);
    const varNl = mNl * mNl;
    const varN = mN * mN;
    const ratio = varN > 0 ? varNl / varN : (varNl > 0 ? Infinity : 0);
    const nonlinear = ratio > BLA_NL_RATIO;
    return {
      // First/last, not min/max: the axis is ascending, and spreading a
      // 100k-line band into Math.min would blow the argument limit.
      f1: bin.f[0],
      f2: bin.f[bin.f.length - 1],
      sigmaNl: mNl,
      sigmaN: mN,
      ratio,
      nonlinear,
      verdict: nonlinear ? BLA_NONLINEAR_TEXT : BLA_LINEAR_TEXT,
      count: bin.f.length,
    };
  });
}

/**
 * Compose the one-line reading of a band list: adjacent bands with the same
 * verdict merge, so a clean low band plus three dirty ones reads
 * "linear below 800 Hz; nonlinearity dominates 800–5000 Hz — level-dependent,
 * repeat at 2–3 amplitudes" rather than four separate clauses. An all-linear
 * result says so without naming any band (the whole excited range is linear),
 * and the level advice is appended once, at the end, whenever any band is
 * distortion-dominated — that is the actionable next measurement.
 *
 * @param bands Output of {@link blaVerdicts} (ascending in frequency).
 * @returns The sentence fragment after "q1 (via ch0): ", or a "no usable σ
 *   data" note for an empty list.
 */
export function summariseBlaVerdicts(bands: BlaBandVerdict[]): string {
  if (!bands.length) return 'no usable σ data';
  // Merge runs of like verdicts.
  const runs: { nonlinear: boolean; f1: number; f2: number }[] = [];
  for (const b of bands) {
    const last = runs[runs.length - 1];
    if (last && last.nonlinear === b.nonlinear) last.f2 = b.f2;
    else runs.push({ nonlinear: b.nonlinear, f1: b.f1, f2: b.f2 });
  }
  if (runs.length === 1 && !runs[0].nonlinear) return BLA_LINEAR_TEXT;

  const parts = runs.map((r, i) => {
    const first = i === 0;
    const last = i === runs.length - 1;
    if (r.nonlinear) {
      return `${BLA_NONLINEAR_TEXT} ${fmtVerdictHz(r.f1)}–${fmtVerdictHz(r.f2)} Hz`;
    }
    if (first) return `linear below ${fmtVerdictHz(r.f2)} Hz`;
    if (last) return `linear above ${fmtVerdictHz(r.f1)} Hz`;
    return `linear ${fmtVerdictHz(r.f1)}–${fmtVerdictHz(r.f2)} Hz`;
  });
  const advice = runs.some((r) => r.nonlinear) ? ` — ${BLA_LEVEL_ADVICE}` : '';
  return `${parts.join('; ')}${advice}`;
}

/**
 * Reduce a BLA set's `(Nf, Nout)` σ arrays to ONE representative pair of
 * per-line σ values by picking, at each frequency, the response channel with
 * the largest distortion-to-noise ratio.
 *
 * A BLA set carries every response channel as a column; the verdict answers
 * "is the system linear at this level", so the honest reduction is the WORST
 * channel — a nonlinearity that shows on one response is a nonlinearity. The
 * pair is taken from the SAME column (never max σ_NL against min σ_n), so the
 * ratio the verdict then computes is a ratio that actually occurred.
 *
 * Arrays are row-major `[f * nCols + c]`, matching the marshalled worker
 * arrays. A non-positive `nCols`, or a length that does not cover the implied
 * rows, yields an empty pair.
 *
 * @param sigmaNl Flat `(Nf, Nout)` σ_NL array.
 * @param sigmaN Flat `(Nf, Nout)` σ_n array.
 * @param nCols Column (response-channel) count.
 * @returns Per-line σ pair, `Nf` long each.
 */
export function worstBlaChannel(
  sigmaNl: ArrayLike<number>,
  sigmaN: ArrayLike<number>,
  nCols: number,
): { sigmaNl: Float64Array; sigmaN: Float64Array } {
  const cols = Math.trunc(nCols);
  const len = Math.min(sigmaNl.length, sigmaN.length);
  if (!(cols > 0) || len < cols) return { sigmaNl: new Float64Array(0), sigmaN: new Float64Array(0) };
  const rows = Math.floor(len / cols);
  const outNl = new Float64Array(rows);
  const outN = new Float64Array(rows);
  for (let r = 0; r < rows; r++) {
    let bestRatio = -Infinity;
    let bestNl = NaN;
    let bestN = NaN;
    for (let c = 0; c < cols; c++) {
      const a = sigmaNl[r * cols + c];
      const b = sigmaN[r * cols + c];
      if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
      const ratio = b > 0 ? (a * a) / (b * b) : (a > 0 ? Infinity : 0);
      if (ratio > bestRatio) {
        bestRatio = ratio;
        bestNl = a;
        bestN = b;
      }
    }
    outNl[r] = bestNl;
    outN[r] = bestN;
  }
  return { sigmaNl: outNl, sigmaN: outN };
}
