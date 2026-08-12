/**
 * Sample-rate entry helpers (round-11).
 *
 * Setup's fs control was a `<select>`, and a value with no matching option —
 * an off-ladder 10000 from a `--settings` prefill — rendered BLANK: Svelte
 * leaves `selectedIndex` at −1, so the rate could be neither read nor
 * changed.  Two separate lab reports ("fs is unsettable", "the TF axis is
 * 10x wrong") traced back to that one blank box.  The control is now a typed
 * combo over these two pure helpers, so the current value is always visible
 * by construction and an off-ladder rate is a legitimate answer rather than
 * an unrepresentable one.
 */
import { expect, test } from 'vitest';
import { parseFs, fsOptionsFor } from '../../src/lib/stores/acquire';

test('parseFs takes plain hertz', () => {
  expect(parseFs('48000')).toBe(48000);
  expect(parseFs('8000')).toBe(8000);
  expect(parseFs(' 10000 ')).toBe(10000);
  // A coerced DSA rate must survive a round-trip through the field.
  expect(parseFs('8533.3')).toBeCloseTo(8533.3, 6);
});

test('parseFs takes k-notation, case- and space-insensitively', () => {
  expect(parseFs('3k')).toBe(3000);
  expect(parseFs('3.2k')).toBe(3200);
  expect(parseFs('48K')).toBe(48000);
  expect(parseFs('48 kHz')).toBe(48000);
  expect(parseFs('44.1k')).toBeCloseTo(44100, 9);
  expect(parseFs('0.5k')).toBe(500);
});

test('parseFs rejects anything that is not a usable rate', () => {
  for (const bad of ['', '   ', 'abc', 'k', '-8000', '0', '4 8 0 0 0', '8e3', '1/2', '12kk', 'NaN']) {
    expect(parseFs(bad), `expected ${JSON.stringify(bad)} to be rejected`).toBeNull();
  }
  // Sane upper bound: a typo must not allocate a 100 M-sample buffer.
  expect(parseFs('2000000')).toBeNull();
  expect(parseFs('1000000')).toBe(1e6);
});

test('fsOptionsFor always includes the current value, even off the ladder', () => {
  const ladder = [8000, 16000, 44100, 48000];
  // THE bug: 10000 is not on any ladder and must still be offered/visible.
  expect(fsOptionsFor(ladder, 10000)).toEqual([8000, 10000, 16000, 44100, 48000]);
  // An on-ladder value is not duplicated.
  expect(fsOptionsFor(ladder, 44100)).toEqual(ladder);
  // No current value → the ladder, sorted.
  expect(fsOptionsFor([48000, 8000])).toEqual([8000, 48000]);
});

test('fsOptionsFor drops junk from the ladder and ignores a junk current value', () => {
  expect(fsOptionsFor([0, -1, NaN, 8000], 0)).toEqual([8000]);
  expect(fsOptionsFor([8000], Number.NaN)).toEqual([8000]);
});
