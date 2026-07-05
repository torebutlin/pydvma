/**
 * Axis-scale helpers for the SVG plot layer: 1-2-5 "nice" tick
 * generation, linear domain→range mapping, and tick-label formatting.
 *
 * Pure functions — no DOM, no Svelte. Unit-tested in
 * `tests/plot/scales.test.ts`.
 */

/**
 * Generate "nice" tick positions covering `[min, max]` using a 1-2-5
 * step ladder, aiming for roughly `target` intervals.
 *
 * Ticks land on multiples of the chosen step; values that round to
 * zero (within floating-point noise of the step) are snapped to exact
 * `0` so labels never read `-0` or `1e-17`. Degenerate domains
 * (`max <= min`) return `[min]`.
 */
export function niceTicks(min: number, max: number, target = 6): number[] {
  if (!(max > min)) return [min];
  const span = max - min;
  const step0 = span / Math.max(1, target);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const norm = step0 / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return out;
}

/**
 * Linear scale factory: maps domain `[d0, d1]` onto range `[r0, r1]`.
 *
 * Inverted ranges are the normal case for SVG y-axes (pass
 * `r0 = height, r1 = 0` so larger data values render higher up).
 * No clamping — out-of-domain inputs extrapolate.
 */
export const scaleLinear = (d0: number, d1: number, r0: number, r1: number) =>
  (v: number) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);

/**
 * Log10 scale factory: maps domain `[d0, d1]` (both must be > 0) onto
 * range `[r0, r1]`, linear in log10 space so each decade occupies an
 * equal pixel band. Used for the frequency axis when the view's
 * `xScale` is `'log'` (R3 Bode-style toggle).
 *
 * Inputs ≤ 0 map to non-finite (`log10(0) = -Inf`, `log10(<0) = NaN`);
 * the path builder already skips non-finite pixel coordinates, so a DC
 * (f=0) bin simply drops out rather than throwing. Callers must ensure
 * the DOMAIN is positive — see `logDomain` — since a non-positive `d0`
 * would make the mapping degenerate.
 */
export const scaleLog = (d0: number, d1: number, r0: number, r1: number) => {
  const l0 = Math.log10(d0), l1 = Math.log10(d1);
  return (v: number) => r0 + ((Math.log10(v) - l0) / (l1 - l0)) * (r1 - r0);
};

/**
 * Positive-clamped domain for a log axis. Autoscale extents can include
 * `0` (the DC frequency bin) or, defensively, negatives; log10 has no
 * value there. Returns `[max(d0, fallback), d1]` when `d0 <= 0`, where
 * `fallback` is the smallest positive datum the caller knows (e.g. the
 * first positive frequency bin). With no positive fallback we degrade
 * to a tiny epsilon so the domain is never non-positive.
 */
export function logDomain(d: [number, number], fallback: number | undefined): [number, number] {
  if (d[0] > 0) return d;
  const lo = fallback !== undefined && fallback > 0 ? fallback : 1e-6;
  return [lo, d[1]];
}

/**
 * Tick positions at powers of ten within `[min, max]` (log axis). Only
 * decades that fall inside the domain are returned — a sub-decade window
 * containing no power of ten yields `[]` (the axis still draws, just
 * without major ticks). A non-positive `min` is treated as the smallest
 * positive value log can represent (starts at 10^0 = 1 unless `max`
 * forces lower), so a domain including the DC bin never throws.
 */
export function decadeTicks(min: number, max: number): number[] {
  if (!(max > 0)) return [];
  // A non-positive lower bound (e.g. the DC bin) has no log; start at
  // 10^0 = 1, the smallest decade the toggle ever shows in practice.
  const e0 = min > 0 ? Math.ceil(Math.log10(min) - 1e-9) : 0;
  const e1 = Math.floor(Math.log10(max) + 1e-9);
  const out: number[] = [];
  for (let e = e0; e <= e1; e++) out.push(10 ** e);
  return out;
}

/**
 * Format a tick value for display, choosing decimal places from the
 * axis span: 0 decimals for spans >= 100, scaling up to more decimals
 * as the span shrinks (span 50 → 1 dp, span 5 → 2 dp, span 0.5 → 3 dp,
 * capped at 8). Trailing zeros are stripped via numeric round-trip.
 *
 * Spans below 1e-6 switch to exponential notation (1 decimal of
 * mantissa) — the fixed 8-dp cap would otherwise mislabel ticks on
 * e.g. a 1e-9 span. Exact `0` still renders as `'0'`.
 */
export function fmtTick(v: number, span: number): string {
  if (!(span > 0) || !Number.isFinite(span)) return String(v);
  if (span < 1e-6) return v === 0 ? '0' : v.toExponential(1);
  const d = Math.max(0, Math.min(8, 2 - Math.floor(Math.log10(span))));
  return (+v.toFixed(d)).toString();
}
