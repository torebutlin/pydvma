import { expect, test } from 'vitest';
import { bandLevels, bandTable, weightingDb } from '../../src/lib/analysis/acoustics';

// Known-answer vectors mirrored VERBATIM from
// `pydvma.acoustics.ACOUSTICS_VECTORS` (f, A dB, C dB). A change on either
// side must change both.
// tests/test_acoustics.py::ACOUSTICS_VECTORS (defined in pydvma/acoustics.py)
const ACOUSTICS_VECTORS: [number, number, number][] = [
  [10.0, -70.435081, -14.330693],
  [31.5, -39.529007, -3.030738],
  [100.0, -19.145096, -0.299668],
  [1000.0, 0.0, 0.0],
  [4000.0, 0.963456, -0.826015],
  [16000.0, -6.70626, -8.63479],
];

const exact = (n: number) => 1000 * 10 ** (Math.round(10 * Math.log10(n / 1000)) / 10);

test('weighting reproduces the shared vectors', () => {
  for (const [f, a, c] of ACOUSTICS_VECTORS) {
    expect(Math.abs(weightingDb(f, 'A') - a)).toBeLessThan(1e-6);
    expect(Math.abs(weightingDb(f, 'C') - c)).toBeLessThan(1e-6);
  }
  expect(Math.abs(weightingDb(1000, 'A'))).toBeLessThan(1e-12);
  expect(weightingDb(123, 'Z')).toBe(0);
  expect(weightingDb(0, 'A')).toBe(-Infinity);
});

test('IEC spot checks', () => {
  for (const [n, want] of [[10, -70.4], [100, -19.1], [4000, 1.0], [16000, -6.6]]) {
    expect(Math.abs(weightingDb(exact(n), 'A') - want)).toBeLessThanOrEqual(0.1);
  }
  for (const [n, want] of [[31.5, -3.0], [8000, -3.0], [20000, -11.2]]) {
    expect(Math.abs(weightingDb(exact(n), 'C') - want)).toBeLessThanOrEqual(0.1);
  }
  expect(bandTable('octave', 22, 22400).map((r) => r.nominal)).toEqual([31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]);
  expect(bandTable('third-octave', 890, 1125).map((r) => r.nominal)).toEqual([1000]);
});

test('white noise density integrates to D x bandwidth, DC bin harmless under A', () => {
  const f = Float64Array.from({ length: 24000 }, (_, i) => i);
  const D = 3e-6;
  const rows = bandLevels(f, new Float64Array(24000).fill(D), 'octave');
  const r = rows.find((x) => x.nominal === 1000)!;
  expect(Math.abs(r.power - D * (r.upper - r.lower))).toBeLessThanOrEqual(1.5 * D);
  for (const x of bandLevels(f, new Float64Array(24000).fill(D), 'octave', 'A')) expect(Number.isFinite(x.power)).toBe(true);
});

test('bands with too few bins are dropped', () => {
  const f = Float64Array.from({ length: 2000 }, (_, i) => i * 5.86);
  const nominals = bandLevels(f, new Float64Array(2000).fill(1), 'third-octave').map((r) => r.nominal);
  expect(nominals).not.toContain(25);
  expect(nominals).toContain(1000);
});
