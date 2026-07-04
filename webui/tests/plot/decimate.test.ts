import { expect, test } from 'vitest';
import { minMaxDecimate } from '../../src/lib/plot/decimate';

test('preserves extremes: a single spike survives 100x decimation', () => {
  const n = 100_000;
  const y = new Float64Array(n).fill(0); y[54321] = 5;
  const pts = minMaxDecimate(y, 0, n - 1, 800);
  expect(Math.max(...pts.map(p => p[1]))).toBe(5);
  expect(pts.length).toBeLessThanOrEqual(800 * 2 + 2);
});

test('passes short arrays through untouched', () => {
  const y = Float64Array.from([1, 2, 3]);
  expect(minMaxDecimate(y, 0, 2, 800).length).toBe(3);
});

test('respects the index window: samples outside [i0, i1] are ignored', () => {
  const y = new Float64Array(10_000).fill(0);
  y[0] = 99;        // outside window
  y[9999] = -99;    // outside window
  y[5000] = 7;      // inside window
  const pts = minMaxDecimate(y, 1000, 8999, 100);
  const vals = pts.map(p => p[1]);
  expect(Math.max(...vals)).toBe(7);
  expect(Math.min(...vals)).toBe(0);
  for (const [i] of pts) {
    expect(i).toBeGreaterThanOrEqual(1000);
    expect(i).toBeLessThanOrEqual(8999);
  }
});

test('columns seed min/max from the first FINITE sample (leading NaN keeps the spike)', () => {
  const n = 10_000;                 // > 2*columns so real decimation runs
  const y = new Float64Array(n).fill(0);
  y[0] = NaN;                       // heads the first pixel column
  y[1] = 5;                         // spike right behind it
  const pts = minMaxDecimate(y, 0, n - 1, 100);
  const vals = pts.map(p => p[1]);
  expect(Math.max(...vals.filter(Number.isFinite))).toBe(5);
  // With finite seeding, no NaN can be emitted from decimated columns.
  expect(vals.every(Number.isFinite)).toBe(true);
});

test('emitted indices are non-decreasing (paths never double back)', () => {
  const y = Float64Array.from({ length: 50_000 }, (_, i) => Math.sin(i / 7));
  const pts = minMaxDecimate(y, 0, 49_999, 500);
  for (let k = 1; k < pts.length; k++) {
    expect(pts[k][0]).toBeGreaterThanOrEqual(pts[k - 1][0]);
  }
});
