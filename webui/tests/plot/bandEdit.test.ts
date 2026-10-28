/**
 * The frequency navigator's typed band edges (`typedBand`). 4C6 lab test
 * (2026-10-27): with the band at 100–140 Hz, typing 290 into the minimum was
 * refused but stayed in the field, then typing 330 into the maximum committed
 * 100–330 Hz under fields reading "290 – 330", and Fit 1 found 120 Hz.
 */
import { expect, test } from 'vitest';
import { typedBand } from '../../src/lib/plot/bandEdit';

const domain = [0, 5000] as const;

test('an edge typed inside the band moves just that edge', () => {
  expect(typedBand('lo', '110', [100, 140], domain)).toEqual([110, 140]);
  expect(typedBand('hi', '200', [100, 140], domain)).toEqual([100, 200]);
});

test('a minimum typed above the maximum moves the band up, keeping its width', () => {
  expect(typedBand('lo', '290', [100, 140], domain)).toEqual([290, 330]);
});

test('a maximum typed below the minimum moves the band down, keeping its width', () => {
  expect(typedBand('hi', '60', [100, 140], domain)).toEqual([20, 60]);
});

test('on a log axis the band keeps its ratio', () => {
  expect(typedBand('lo', '1000', [10, 20], domain, true)).toEqual([1000, 2000]);
  expect(typedBand('hi', '50', [100, 400], domain, true)).toEqual([12.5, 50]);
});

test('a moved band is clipped to the domain', () => {
  expect(typedBand('lo', '4990', [100, 140], domain)).toEqual([4990, 5000]);
  expect(typedBand('hi', '10', [100, 140], domain)).toEqual([0, 10]);
});

test('nothing to commit: not a number, no change, or no room left', () => {
  expect(typedBand('lo', '', [100, 140], domain)).toBeNull();
  expect(typedBand('lo', 'abc', [100, 140], domain)).toBeNull();
  expect(typedBand('lo', '100', [100, 140], domain)).toBeNull();
  expect(typedBand('lo', '6000', [100, 140], domain)).toBeNull();   // clamps to fmax: zero width
});
