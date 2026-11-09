import { expect, test } from 'vitest';
import { sigFigs } from '../src/lib/format';

test('sigFigs rounds to 3 s.f. and strips trailing zeros', () => {
  // The round-2 case: a logged-time badge of 1.999977 s reads "2 s".
  expect(sigFigs(1.999977)).toBe('2');
  expect(sigFigs(1.23456)).toBe('1.23');
  expect(sigFigs(0.204999)).toBe('0.205');
  expect(sigFigs(1234.5)).toBe('1230');        // 3 s.f. of a big value
  expect(sigFigs(0.5)).toBe('0.5');            // no fabricated trailing zeros
});

test('sigFigs handles zero, negatives, and a custom figure count', () => {
  expect(sigFigs(0)).toBe('0');
  expect(sigFigs(-1.999977)).toBe('-2');
  expect(sigFigs(3.14159, 4)).toBe('3.142');
});

test('sigFigs passes non-finite inputs through as strings', () => {
  expect(sigFigs(NaN)).toBe('NaN');
  expect(sigFigs(Infinity)).toBe('Infinity');
});

test('sigFigs keeps a mic channel\'s millivolt full scale readable (iD44 at 60 dB)', () => {
  // 18 dBu − 60 dB → 8.7 mV peak: three figures, where toFixed(2) said 0.01.
  const v = Math.SQRT2 * 0.7746 * 10 ** ((18 - 60) / 20);
  expect(sigFigs(v)).toBe('0.0087');
  expect(sigFigs(1.9036)).toBe('1.9');
  expect(sigFigs(13.8)).toBe('13.8');
});
