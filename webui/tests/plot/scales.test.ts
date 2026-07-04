import { expect, test } from 'vitest';
import { niceTicks, scaleLinear, fmtTick } from '../../src/lib/plot/scales';

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
