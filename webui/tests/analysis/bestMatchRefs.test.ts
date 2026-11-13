/**
 * The TF lines Best Match can take as its reference, labelled as the tray
 * labels their cards (`lib/analysis/bestMatchRefs.ts`).
 */
import { expect, test } from 'vitest';
import { bestMatchRefs, tfLineChannels, tfLineName } from '../../src/lib/analysis/bestMatchRefs';

const chLabel = (_setId: number, ch: number) => `ch_${ch}`;

test('a TF column maps back to its source channel, skipping the input', () => {
  expect(tfLineChannels(0, 1)).toEqual([1]);
  expect(tfLineChannels(1, 2)).toEqual([0, 2]);
  // An orphan TF (no measured input): the columns are the channels.
  expect(tfLineChannels(null, 2)).toEqual([0, 1]);
});

test('a card with one TF line is named by the card alone', () => {
  const refs = bestMatchRefs(
    [{ id: 3, name: 'hammer_input_6.0s' }, { id: 4, name: 'noise_input_30.0s' }],
    () => ({ chIn: 0, nCols: 1 }),
    chLabel,
  );
  expect(refs).toEqual([
    { key: '3:1', setId: 3, ch: 1, label: 'hammer_input_6.0s' },
    { key: '4:1', setId: 4, ch: 1, label: 'noise_input_30.0s' },
  ]);
});

test('a card with several TF lines names each line as the tray does', () => {
  const refs = bestMatchRefs([{ id: 1, name: 'rig' }], () => ({ chIn: 0, nCols: 2 }), chLabel);
  expect(refs.map((r) => r.label)).toEqual(['rig · ch_1/ch_0', 'rig · ch_2/ch_0']);
  expect(refs.map((r) => r.ch)).toEqual([1, 2]);
});

test('an orphan TF lists its columns by channel label', () => {
  const refs = bestMatchRefs([{ id: 1, name: 'jw' }], () => ({ chIn: null, nCols: 2 }), chLabel);
  expect(refs.map((r) => r.label)).toEqual(['jw · ch_0', 'jw · ch_1']);
});

test('sets with no TF yet are left out, and custom channel labels are used', () => {
  const tf: Record<number, { chIn: number | null; nCols: number } | undefined> = {
    1: undefined, 2: { chIn: 0, nCols: 0 }, 3: { chIn: 1, nCols: 2 },
  };
  const label = (_s: number, ch: number) => ['force', 'accel A', 'accel B'][ch];
  const refs = bestMatchRefs(
    [{ id: 1, name: 'raw' }, { id: 2, name: 'empty' }, { id: 3, name: 'beam' }],
    (id) => tf[id],
    label,
  );
  expect(refs.map((r) => r.label)).toEqual(['beam · force/accel A', 'beam · accel B/accel A']);
});

test('tfLineName matches the list', () => {
  expect(tfLineName('rig', 2, 0, 1, chLabel)).toBe('rig');
  expect(tfLineName('rig', 2, 0, 2, chLabel)).toBe('rig · ch_2/ch_0');
  expect(tfLineName('jw', 1, null, 2, chLabel)).toBe('jw · ch_1');
});
