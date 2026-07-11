/**
 * Peak detection + peak-step targeting for the frequency navigator
 * (dev/plans/2026-07-11-freq-navigator-design.md).
 *
 * Runs client-side on the navigator strip's own magnitude lines — no engine
 * round-trip. The composite max-envelope across all lines is binned onto a
 * uniform grid over the scope (uniform in log10 space when `log`), local
 * maxima are found on the compacted (gap-free) envelope, and each must clear
 * a prominence threshold measured as a fraction of the envelope's total
 * y-span — so noise ripple never becomes a "peak".
 */

/** One strip line: paired x (frequency, Hz) / y (magnitude, any units) arrays. */
export interface NavLine { x: ArrayLike<number>; y: ArrayLike<number>; }

/** Envelope grid resolution (bins across the scope). */
const N_BINS = 512;
/** Min peak prominence as a fraction of the envelope's y-span. */
const PROMINENCE_FRAC = 0.05;

/**
 * Detect peak frequencies (ascending, Hz) of the composite max-envelope of
 * `lines` within `scope`. `log` bins uniformly in log10(f) — pass the strip's
 * axis mode so detection resolution matches what the user sees. Degenerate
 * input (no lines, empty scope, flat envelope) returns `[]`.
 */
export function detectPeaks(lines: NavLine[], scope: [number, number], log = false): number[] {
  const [lo, hi] = scope;
  if (!(hi > lo) || lines.length === 0) return [];
  const L = log && lo > 0;
  const tLo = L ? Math.log10(lo) : lo;
  const tHi = L ? Math.log10(hi) : hi;

  // 1) composite max-envelope on a uniform grid (in axis space)
  const env = new Float64Array(N_BINS).fill(-Infinity);
  for (const l of lines) {
    const n = Math.min(l.x.length, l.y.length);
    for (let i = 0; i < n; i++) {
      const x = l.x[i], y = l.y[i];
      if (!Number.isFinite(x) || !Number.isFinite(y) || x < lo || x > hi) continue;
      const t = L ? Math.log10(x) : x;
      const b = Math.min(N_BINS - 1, Math.max(0, Math.floor(((t - tLo) / (tHi - tLo)) * N_BINS)));
      if (y > env[b]) env[b] = y;
    }
  }

  // 2) compact away empty bins (sparse data ⇒ gaps; local-max tests need neighbours)
  const ys: number[] = [], centres: number[] = [];
  for (let b = 0; b < N_BINS; b++) {
    if (env[b] === -Infinity) continue;
    ys.push(env[b]);
    const tc = tLo + ((b + 0.5) / N_BINS) * (tHi - tLo);
    centres.push(L ? 10 ** tc : tc);
  }
  if (ys.length < 3) return [];
  let yMin = Infinity, yMax = -Infinity;
  for (const y of ys) { if (y < yMin) yMin = y; if (y > yMax) yMax = y; }
  const minProm = (yMax - yMin) * PROMINENCE_FRAC;
  if (!(minProm > 0)) return [];   // flat envelope

  // 3) local maxima + prominence: walk each side to the nearest HIGHER sample
  //    (or the end), tracking the valley minimum; prominence = peak − the
  //    higher of the two valley minima (the standard definition).
  const peaks: number[] = [];
  for (let i = 1; i < ys.length - 1; i++) {
    if (!(ys[i] > ys[i - 1] && ys[i] >= ys[i + 1])) continue;
    let lMin = ys[i], rMin = ys[i];
    for (let j = i - 1; j >= 0; j--) { if (ys[j] > ys[i]) break; if (ys[j] < lMin) lMin = ys[j]; }
    for (let j = i + 1; j < ys.length; j++) { if (ys[j] > ys[i]) break; if (ys[j] < rMin) rMin = ys[j]; }
    if (ys[i] - Math.max(lMin, rMin) >= minProm) peaks.push(centres[i]);
  }
  return peaks;
}

/**
 * The window produced by ONE peak-step press: centre the current window
 * (width kept — as a log10 RATIO when `log`, matching the brush's translate
 * semantics) on the nearest peak beyond the window centre in direction `dir`,
 * clamped inside `scope` (hugging the edge, width preserved). Candidates
 * whose clamped window reproduces the CURRENT window — compared in axis
 * (log10 when `log`) space — are skipped (an edge-clamped window must not
 * re-target the same peak forever). Returns `null` when no candidate yields
 * a different window ⇒ disable the button.
 *
 * Special case (the "home" rule): a window spanning ≥90% of the scope — where
 * keep-width is meaningless — steps at scope-span/10 width instead.
 */
export function stepWindow(
  peaks: number[],
  window: [number, number],
  scope: [number, number],
  dir: 1 | -1,
  log = false,
): [number, number] | null {
  const [sLo, sHi] = scope;
  if (!(sHi > sLo) || peaks.length === 0) return null;
  const L = log && sLo > 0;
  const fwd = (v: number) => (L ? Math.log10(v) : v);
  const inv = (t: number) => (L ? 10 ** t : t);
  const tSLo = fwd(sLo), tSHi = fwd(sHi);
  const span = tSHi - tSLo;

  let width = fwd(window[1]) - fwd(window[0]);
  let centre = (fwd(window[0]) + fwd(window[1])) / 2;
  if (!Number.isFinite(width) || width <= 0 || width >= 0.9 * span) width = span / 10;
  if (!Number.isFinite(centre)) centre = (tSLo + tSHi) / 2;

  const cands = peaks.map(fwd)
    .filter((t) => Number.isFinite(t) && t >= tSLo && t <= tSHi)
    .filter((t) => (dir === 1 ? t > centre : t < centre))
    .sort((a, b) => (dir === 1 ? a - b : b - a));

  const tolT = span * 1e-6;
  const wLoT = fwd(window[0]), wHiT = fwd(window[1]);
  for (const t of cands) {
    let lo = t - width / 2, hi = t + width / 2;
    if (lo < tSLo) { lo = tSLo; hi = tSLo + width; }
    else if (hi > tSHi) { hi = tSHi; lo = tSHi - width; }
    // Skip a candidate that reproduces the current window (compared in axis
    // space so the guard scales correctly on log axes); a non-finite current
    // window (log axis, non-positive edge) always counts as different.
    const differs = !Number.isFinite(wLoT) || !Number.isFinite(wHiT)
      || Math.abs(lo - wLoT) > tolT || Math.abs(hi - wHiT) > tolT;
    if (differs) return [inv(lo), inv(hi)];
  }
  return null;
}
