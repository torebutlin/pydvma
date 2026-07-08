import { expect, test } from 'vitest';
import {
  defaultChannelLabel, tfColumn, tfLineLabel, tfTransformEntries,
} from '../../src/lib/plot/tfChannels';

test('defaultChannelLabel: ch_${n}', () => {
  expect(defaultChannelLabel(0)).toBe('ch_0');
  expect(defaultChannelLabel(3)).toBe('ch_3');
});

test('tfColumn: input channel has no column', () => {
  expect(tfColumn(0, 0, 3)).toBeNull();   // ch_0 is the input
  expect(tfColumn(1, 1, 3)).toBeNull();
});

test('tfColumn chIn=0: contiguous outputs shift down by one', () => {
  // channels ∖ {0} = [1, 2] → columns [0, 1]
  expect(tfColumn(1, 0, 3)).toBe(0);
  expect(tfColumn(2, 0, 3)).toBe(1);
});

test('tfColumn chIn=1: outputs remap around the gap', () => {
  // channels ∖ {1} = [0, 2] → columns [0, 1]
  expect(tfColumn(0, 1, 3)).toBe(0);
  expect(tfColumn(2, 1, 3)).toBe(1);
});

test('tfColumn chIn=2 (last): outputs keep their index', () => {
  // channels ∖ {2} = [0, 1] → columns [0, 1]
  expect(tfColumn(0, 2, 3)).toBe(0);
  expect(tfColumn(1, 2, 3)).toBe(1);
});

test('tfColumn: channel outside the set → null', () => {
  expect(tfColumn(3, 0, 3)).toBeNull();   // no ch_3 in a 3-channel set
  expect(tfColumn(-1, 0, 3)).toBeNull();
});

test('tfColumn chIn=null (orphan TF): identity — columns are the lines', () => {
  // Round-5 item 3: no measured input to drop, so every channel maps to its
  // OWN column and NONE is skipped. 11 columns → 11 lines, ch_c → column c.
  for (let c = 0; c < 11; c++) expect(tfColumn(c, null, 11)).toBe(c);
  expect(tfColumn(11, null, 11)).toBeNull();   // still bounded by nChannels
  expect(tfColumn(-1, null, 11)).toBeNull();
});

test('tfLineLabel: output/input, default ch_${n}', () => {
  expect(tfLineLabel(0, 1, 0)).toBe('ch_1/ch_0');   // args: setId, chOut, chIn
  expect(tfLineLabel(5, 2, 0)).toBe('ch_2/ch_0');
});

test('tfLineLabel: custom label accessor relabels both halves (R5 hook)', () => {
  const custom = (setId: number, ch: number) => `s${setId}c${ch}`;
  expect(tfLineLabel(7, 2, 1, custom)).toBe('s7c2/s7c1');
});

test('tfTransformEntries: drops input channel, relabels out/in, keeps set prefix', () => {
  const entries = [
    { setId: 0, ch: 0, label: 'A · ch_0' },
    { setId: 0, ch: 1, label: 'A · ch_1' },
    { setId: 0, ch: 2, label: 'A · ch_2' },
  ];
  const out = tfTransformEntries(entries, () => 0);   // chIn=0 for set 0
  expect(out.map(e => e.ch)).toEqual([1, 2]);          // ch_0 (input) dropped
  expect(out.map(e => e.label)).toEqual(['A · ch_1/ch_0', 'A · ch_2/ch_0']);
});

test('tfTransformEntries: no set prefix (bare label) → bare out/in', () => {
  const entries = [{ setId: 0, ch: 0, label: 'ch_0' }, { setId: 0, ch: 1, label: 'ch_1' }];
  const out = tfTransformEntries(entries, () => 0);
  expect(out.map(e => e.label)).toEqual(['ch_1/ch_0']);
});

test('tfTransformEntries: set with no TF yet passes through unchanged', () => {
  const entries = [{ setId: 9, ch: 0, label: 'B · ch_0' }, { setId: 9, ch: 1, label: 'B · ch_1' }];
  const out = tfTransformEntries(entries, () => undefined);   // no chIn known
  expect(out).toEqual(entries);
});

test('tfTransformEntries: orphan TF (chIn null) keeps every column, plain labels', () => {
  // Round-5 item 3: an orphan TF drops nothing and does NOT relabel to out/in
  // — the columns are the lines, listed per-channel. Every entry survives with
  // its original plain label.
  const entries = [
    { setId: 0, ch: 0, label: 'ruler · ch_0' },
    { setId: 0, ch: 1, label: 'ruler · ch_1' },
    { setId: 0, ch: 2, label: 'ruler · ch_2' },
  ];
  const out = tfTransformEntries(entries, () => null);   // orphan: no input
  expect(out).toEqual(entries);
});

test('tfTransformEntries: per-set chIn, mixed sets', () => {
  const entries = [
    { setId: 0, ch: 0, label: 'A0' }, { setId: 0, ch: 1, label: 'A1' },
    { setId: 1, ch: 0, label: 'B0' }, { setId: 1, ch: 1, label: 'B1' },
  ];
  const chInFor = (setId: number) => (setId === 0 ? 0 : 1);   // set0 in=0, set1 in=1
  const out = tfTransformEntries(entries, chInFor);
  // set 0: drop ch_0 → [ch_1/ch_0]; set 1: drop ch_1 → [ch_0/ch_1]
  expect(out.map(e => `${e.setId}:${e.ch}:${e.label}`)).toEqual([
    '0:1:ch_1/ch_0',
    '1:0:ch_0/ch_1',
  ]);
});

test('tfTransformEntries: custom channel labels (R5) reach the out/in label', () => {
  // The App call site passes selection.channelLabel as the accessor, so a
  // renamed line reads e.g. `hammer/accel` in the TF out/in label. The
  // "set · " prefix from the raw legend label is preserved.
  const entries = [
    { setId: 0, ch: 0, label: 'A · accel' },   // ch_0 renamed → accel (input)
    { setId: 0, ch: 1, label: 'A · hammer' },  // ch_1 renamed → hammer (output)
  ];
  const label = (_setId: number, ch: number) => (ch === 0 ? 'accel' : 'hammer');
  const out = tfTransformEntries(entries, () => 0, label);   // chIn=0
  expect(out.map(e => e.label)).toEqual(['A · hammer/accel']);
});

test('tfTransformEntries: preserves extra entry fields (colour/state)', () => {
  const entries = [
    { setId: 0, ch: 0, label: 'in', color: '#111', state: 'on' as const },
    { setId: 0, ch: 1, label: 'out', color: '#222', state: 'fade' as const },
  ];
  const out = tfTransformEntries(entries, () => 0);
  expect(out).toHaveLength(1);
  expect(out[0]).toMatchObject({ setId: 0, ch: 1, color: '#222', state: 'fade', label: 'ch_1/ch_0' });
});
