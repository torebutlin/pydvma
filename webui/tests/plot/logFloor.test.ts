import { expect, test } from 'vitest';
import { LOG_FREQ_DECADES, logFreqFloor, minPositiveX } from '../../src/lib/plot/logFloor';

test('three decades, the twin of pydvma.analysis.LOG_FREQ_DECADES', () => {
  expect(LOG_FREQ_DECADES).toBe(3);
});

test('the floor is the top over 1000, raised to the first positive frequency', () => {
  expect(logFreqFloor(1500, 0.05)).toBeCloseTo(1.5, 12);     // 3 kHz record, long
  expect(logFreqFloor(24000, 11.7)).toBeCloseTo(24, 12);      // 48 kHz soundcard
  expect(logFreqFloor(1500, 3)).toBe(3);                      // a short record's first bin wins
  expect(logFreqFloor(1500, undefined)).toBeCloseTo(1.5, 12);
});

test('never returns a non-positive bound', () => {
  expect(logFreqFloor(0, undefined)).toBeGreaterThan(0);
  expect(logFreqFloor(NaN, 2)).toBe(2);
  expect(logFreqFloor(-5, 0)).toBeGreaterThan(0);
});

test('minPositiveX skips DC, negatives and non-finite samples', () => {
  const lines = [
    { x: Float64Array.from([0, 0.5, 1]) },
    { x: Float64Array.from([NaN, -1, 0.25, 4]) },
  ];
  expect(minPositiveX(lines)).toBe(0.25);
  expect(minPositiveX([{ x: Float64Array.from([0, -2]) }])).toBeUndefined();
});
