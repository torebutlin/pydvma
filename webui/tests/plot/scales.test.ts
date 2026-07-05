import { expect, test } from 'vitest';
import { niceTicks, scaleLinear, scaleLog, decadeTicks, logDomain, fmtTick } from '../../src/lib/plot/scales';

test('1-2-5 ticks over a simple domain', () => {
  expect(niceTicks(0, 500, 6)).toEqual([0, 100, 200, 300, 400, 500]);
});

test('handles negative and fractional domains', () => {
  const t = niceTicks(-0.25, 0.25, 5);
  expect(t[0]).toBeLessThanOrEqual(-0.2);
  expect(t).toContain(0);
});

test('degenerate domain collapses to a single tick', () => {
  expect(niceTicks(3, 3)).toEqual([3]);
});

test('scaleLinear maps domain to range (including inverted ranges)', () => {
  const s = scaleLinear(0, 10, 0, 100);
  expect(s(5)).toBe(50);
  const flipped = scaleLinear(0, 10, 100, 0); // SVG y grows downwards
  expect(flipped(0)).toBe(100);
  expect(flipped(10)).toBe(0);
});

test('fmtTick picks decimals from the span', () => {
  expect(fmtTick(200, 500)).toBe('200');
  expect(fmtTick(2.5, 50)).toBe('2.5');
  expect(fmtTick(0.25, 0.5)).toBe('0.25');
  expect(fmtTick(-0.1, 0.5)).toBe('-0.1');
});

test('fmtTick handles very large spans with 0 decimals', () => {
  expect(fmtTick(2_000_000, 1e6)).toBe('2000000');
  expect(fmtTick(-500_000, 1e6)).toBe('-500000');
});

test('fmtTick switches to exponential below 1e-6 spans', () => {
  // The old fixed 8-dp cap would render every tick on a 1e-9 span as '0'.
  expect(fmtTick(3e-9, 1e-9)).toBe('3.0e-9');
  expect(fmtTick(2.5e-9, 1e-9)).toBe('2.5e-9');
  expect(fmtTick(-1.5e-8, 1e-8)).toBe('-1.5e-8');
  expect(fmtTick(0, 1e-9)).toBe('0');
});

// ---- log10 axis (R3: frequency lin↔log toggle) ----

test('scaleLog maps decades linearly in log space', () => {
  // domain [1, 1000] over range [0, 300] px: each decade is 100 px.
  const s = scaleLog(1, 1000, 0, 300);
  expect(s(1)).toBeCloseTo(0, 9);
  expect(s(10)).toBeCloseTo(100, 9);
  expect(s(100)).toBeCloseTo(200, 9);
  expect(s(1000)).toBeCloseTo(300, 9);
});

test('scaleLog honours inverted (SVG y) ranges', () => {
  const s = scaleLog(1, 100, 200, 0);   // r0=200, r1=0
  expect(s(1)).toBeCloseTo(200, 9);
  expect(s(100)).toBeCloseTo(0, 9);
});

test('scaleLog on a non-positive value yields non-finite (skipped downstream)', () => {
  const s = scaleLog(1, 1000, 0, 300);
  expect(Number.isFinite(s(0))).toBe(false);     // log10(0) = -Inf
  expect(Number.isFinite(s(-5))).toBe(false);    // log10(<0) = NaN
});

test('decadeTicks places ticks at powers of ten spanning the domain', () => {
  // [1, 1000] → 1, 10, 100, 1000.
  expect(decadeTicks(1, 1000)).toEqual([1, 10, 100, 1000]);
  // [2, 900] → decades fully inside: 10, 100 (endpoints not on a decade).
  expect(decadeTicks(2, 900)).toEqual([10, 100]);
  // sub-decade domain still yields the enclosing decade edges.
  expect(decadeTicks(3, 8)).toEqual([]);          // no power of ten in (3,8)
});

test('decadeTicks ignores a non-positive lower bound (log has no ≤0)', () => {
  // A domain starting at 0 (DC bin) must not blow up; ticks start at the
  // first positive decade covered by the upper bound.
  expect(decadeTicks(0, 100)).toEqual([1, 10, 100]);
  expect(decadeTicks(-50, 100)).toEqual([1, 10, 100]);
});

test('logDomain clamps a non-positive lower bound to the smallest positive value', () => {
  // Autoscale extent may include f=0 (DC). Log-x needs a positive lower
  // bound; clamp to the smallest positive datum the caller supplies.
  expect(logDomain([0, 5000], 0.5)).toEqual([0.5, 5000]);
  expect(logDomain([-10, 5000], 2)).toEqual([2, 5000]);
  // Already-positive lower bound is left untouched.
  expect(logDomain([10, 5000], 0.5)).toEqual([10, 5000]);
  // No positive fallback available → degrade to a tiny epsilon, never ≤0.
  const [lo] = logDomain([0, 100], undefined);
  expect(lo).toBeGreaterThan(0);
});
