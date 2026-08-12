import { expect, test } from 'vitest';
import { editSonoBand, sonoFreqScaleFor } from '../../src/lib/analysis/sonoBand';

const auto = { fMin: null, fMax: null };

test('a lone bound is stored (the other side stays automatic)', () => {
  // The card's two boxes are independent: entering only a minimum used to be
  // dropped on the way to the engine, so the band never took effect.
  expect(editSonoBand('fMin', '120', auto)).toEqual({ patch: { fMin: 120 }, error: '' });
  expect(editSonoBand('fMax', '900', auto)).toEqual({ patch: { fMax: 900 }, error: '' });
});

test('blanking a box clears that side back to automatic', () => {
  expect(editSonoBand('fMin', '', { fMin: 120, fMax: 900 }))
    .toEqual({ patch: { fMin: null }, error: '' });
  expect(editSonoBand('fMax', '   ', { fMin: 120, fMax: 900 }))
    .toEqual({ patch: { fMax: null }, error: '' });
});

test('a reversed pair is REJECTED, not swapped or silently applied', () => {
  // Reversed bounds used to reach the engine, which substituted
  // f_max = 2*f_min — a confident analysis of a band nobody asked for.
  const lowered = editSonoBand('fMax', '50', { fMin: 120, fMax: 900 });
  expect(lowered.patch).toBeNull();
  expect(lowered.error).toMatch(/min must be below max/);
  const raised = editSonoBand('fMin', '2000', { fMin: 120, fMax: 900 });
  expect(raised.patch).toBeNull();
  expect(raised.error).toMatch(/min must be below max/);
  // Equal bounds are a zero-width band — also refused.
  expect(editSonoBand('fMin', '900', { fMin: 120, fMax: 900 }).patch).toBeNull();
});

test('an entry is judged only against a bound that is actually set', () => {
  // 2000 Hz is above the stored max, but the max has been cleared: nothing to
  // conflict with, so it stands.
  expect(editSonoBand('fMin', '2000', { fMin: 120, fMax: null }))
    .toEqual({ patch: { fMin: 2000 }, error: '' });
});

test('non-positive entries are refused with a reason; non-finite is a no-op', () => {
  const zero = editSonoBand('fMin', '0', auto);
  expect(zero.patch).toBeNull();
  expect(zero.error).toMatch(/above 0 Hz/);
  expect(editSonoBand('fMax', '-30', auto).patch).toBeNull();
  expect(editSonoBand('fMin', 'abc', auto)).toEqual({ patch: null, error: '' });
});

test('each sonogram method carries its own default frequency axis', () => {
  // The CWT is computed on a log (constant-Q) ladder and returned on that
  // native grid; drawn on a linear axis it collapses into a blocky band.
  expect(sonoFreqScaleFor('cwt')).toBe('log');
  expect(sonoFreqScaleFor('stft')).toBe('lin');
});
