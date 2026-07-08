import { expect, test } from 'vitest';
import { csdPairEntries } from '../../src/lib/plot/csdChannels';

test('csdPairEntries: keeps only the pair Y-channel row, relabels S(x,y)', () => {
  const entries = [
    { setId: 0, ch: 0, label: 'A · ch_0' },
    { setId: 0, ch: 1, label: 'A · ch_1' },
    { setId: 0, ch: 2, label: 'A · ch_2' },
  ];
  const out = csdPairEntries(entries, () => ({ i: 0, j: 2 }));
  expect(out).toHaveLength(1);              // one line per set (the pair)
  expect(out[0].ch).toBe(2);               // carried on the Y channel
  expect(out[0].label).toBe('A · S(ch_0,ch_2)');
});

test('csdPairEntries: no set prefix → bare S(x,y)', () => {
  const entries = [{ setId: 0, ch: 0, label: 'ch_0' }, { setId: 0, ch: 1, label: 'ch_1' }];
  const out = csdPairEntries(entries, () => ({ i: 0, j: 1 }));
  expect(out.map((e) => e.label)).toEqual(['S(ch_0,ch_1)']);
});

test('csdPairEntries: a set with no CSD yet passes through unchanged', () => {
  const entries = [{ setId: 9, ch: 0, label: 'B · ch_0' }, { setId: 9, ch: 1, label: 'B · ch_1' }];
  expect(csdPairEntries(entries, () => undefined)).toEqual(entries);
  expect(csdPairEntries(entries, () => null)).toEqual(entries);
});

test('csdPairEntries: custom channel labels (R5) reach the S(x,y) label', () => {
  const entries = [
    { setId: 0, ch: 0, label: 'A · hammer' },
    { setId: 0, ch: 1, label: 'A · accel' },
  ];
  const label = (_setId: number, ch: number) => (ch === 0 ? 'hammer' : 'accel');
  const out = csdPairEntries(entries, () => ({ i: 0, j: 1 }), label);
  expect(out.map((e) => e.label)).toEqual(['A · S(hammer,accel)']);
});

test('csdPairEntries: preserves extra fields (colour/state) on the pair row', () => {
  const entries = [
    { setId: 0, ch: 0, label: 'x', color: '#111', state: 'on' as const },
    { setId: 0, ch: 1, label: 'y', color: '#222', state: 'fade' as const },
  ];
  const out = csdPairEntries(entries, () => ({ i: 0, j: 1 }));
  expect(out).toHaveLength(1);
  expect(out[0]).toMatchObject({ setId: 0, ch: 1, color: '#222', state: 'fade' });
});

test('csdPairEntries: per-set pairs, mixed sets', () => {
  const entries = [
    { setId: 0, ch: 0, label: 'A0' }, { setId: 0, ch: 1, label: 'A1' }, { setId: 0, ch: 2, label: 'A2' },
    { setId: 1, ch: 0, label: 'B0' }, { setId: 1, ch: 1, label: 'B1' },
  ];
  const pairFor = (setId: number) => (setId === 0 ? { i: 1, j: 2 } : { i: 0, j: 1 });
  const out = csdPairEntries(entries, pairFor);
  expect(out.map((e) => `${e.setId}:${e.ch}:${e.label}`)).toEqual([
    '0:2:S(ch_1,ch_2)',
    '1:1:S(ch_0,ch_1)',
  ]);
});
