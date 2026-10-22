import { expect, test } from 'vitest';
import { get } from 'svelte/store';
import { constantsFromMatrix, createModalStore, fitColumnLabels } from '../../src/lib/stores/modal';

/** A marshalled real array. */
const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
/** A marshalled complex array; `data` interleaved [re,im,…]. */
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

/** A canned `calc_fit` engine result: two modes + local + global recon. */
const fitResult = () => ({
  M: real([2, 6], [80, 0.02, 1, 0, 0, 0, 220, 0.015, 0.6, 0, 0, 0]),
  fn: real([2], [80, 220]),
  zn: real([2], [0.02, 0.015]),
  an: real([2, 1], [1, 0.6]),
  pn: real([2, 1], [0, 0]),
  message: 'fn=80.00 (Hz)',
  recon_freq_axis: real([3], [60, 80, 110]),
  recon_tf_data: cplx([3, 1], [1, 0, 2, 0, 1, 0]),
  global_freq_axis: real([2], [0, 500]),
  global_tf_data: cplx([2, 1], [0.5, 0, 0.5, 0]),
});

test('applyResult decodes modes, matrix, and both recon slices', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);
  const s = get(m);
  expect(s.setId).toBe(3);
  expect(s.chIn).toBe(0);
  expect(s.nChannels).toBe(2);
  expect(s.modes.map((x) => x.fn)).toEqual([80, 220]);
  // Q = 1/(2ζ)
  expect(s.modes[0].Q).toBeCloseTo(25, 6);
  expect(s.modes[1].Q).toBeCloseTo(1 / (2 * 0.015), 6);
  expect(s.message).toBe('fn=80.00 (Hz)');
  expect(s.matrix?.shape).toEqual([2, 6]);
  expect(s.local?.axis.length).toBe(3);
  expect(Array.from(s.local!.data.re)).toEqual([1, 2, 1]);
  expect(s.global?.axis.length).toBe(2);
});

test('an empty M (reject to nothing) clears matrix/modes and setId', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);
  // A reject that empties the model: zero-row M, empty summaries + recon.
  m.applyResult({
    M: real([0, 0], []), fn: real([0], []), zn: real([0], []),
    an: real([0, 0], []), pn: real([0, 0], []), message: 'Mode fits deleted.',
    recon_freq_axis: real([0], []), recon_tf_data: cplx([0, 1], []),
    global_freq_axis: real([0], []), global_tf_data: cplx([0, 1], []),
  }, [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);
  const s = get(m);
  expect(s.matrix).toBeNull();
  expect(s.setId).toBeNull();
  expect(s.modes).toEqual([]);
  expect(s.local).toBeNull();
  expect(s.global).toBeNull();
});

test('reconMode defaults to global, setReconMode flips it, and it survives a fresh fit', () => {
  const m = createModalStore();
  // 'global' is the default — the durable slice, so today's default look.
  expect(get(m).reconMode).toBe('global');
  m.setReconMode('local');
  expect(get(m).reconMode).toBe('local');
  m.applyResult(fitResult(), [{ setId: 1, chIn: 0, nChannels: 2, nCols: 1 }]);
  // A new fit must NOT silently flip the chosen mode back.
  expect(get(m).reconMode).toBe('local');
  m.setReconMode('global');
  expect(get(m).reconMode).toBe('global');
});

test('reset returns to the empty state', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), [{ setId: 1, chIn: 0, nChannels: 2, nCols: 1 }]);
  m.setReconMode('local');
  m.reset();
  const s = get(m);
  expect(s.setId).toBeNull();
  expect(s.modes).toEqual([]);
  expect(s.matrix).toBeNull();
  expect(s.reconMode).toBe('global');
  expect(s.muted).toEqual([]);
  expect(s.undo).toBeNull();
});

test('mt mirrors the card', () => {
  const m = createModalStore();
  expect(get(m).mt).toBe('acc');
  m.setMt('vel');
  expect(get(m).mt).toBe('vel');
});

test('undo slot: pushUndo snapshots, undo restores, one level only', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);  // 2 modes
  expect(get(m).undo).toBeNull();

  m.pushUndo();                                   // snapshot the 2-mode model
  expect(get(m).undo).not.toBeNull();

  // A destructive change: reject down to nothing.
  m.applyResult({
    M: real([0, 0], []), fn: real([0], []), zn: real([0], []),
    an: real([0, 0], []), pn: real([0, 0], []), message: 'Mode fits deleted.',
    recon_freq_axis: real([0], []), recon_tf_data: cplx([0, 1], []),
    global_freq_axis: real([0], []), global_tf_data: cplx([0, 1], []),
  }, [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);
  expect(get(m).modes).toEqual([]);

  m.undo();                                        // restore the 2-mode model
  const s = get(m);
  expect(s.modes.map((x) => x.fn)).toEqual([80, 220]);
  expect(s.setId).toBe(3);
  expect(s.undo).toBeNull();                       // slot cleared after undo
});

test('seedFromMatrix decodes the mode summary from M rows (fn=col0, zn=col1) without a recon', () => {
  const m = createModalStore();
  // Two modes, 1 channel: M row = [fn, zn, an, pn, rk, rm].
  const M = real([2, 6], [80, 0.02, 1, 0, 0, 0, 220, 0.01, 0.6, 0, 0, 0]);
  m.seedFromMatrix(M, [{ setId: 7, chIn: 0, nChannels: 2, nCols: 1 }], 'vel');
  const s = get(m);
  expect(s.setId).toBe(7);
  expect(s.chIn).toBe(0);
  expect(s.nChannels).toBe(2);
  expect(s.mt).toBe('vel');
  expect(s.modes.map((x) => x.fn)).toEqual([80, 220]);
  expect(s.modes.map((x) => x.zn)).toEqual([0.02, 0.01]);
  expect(s.modes[0].Q).toBeCloseTo(25, 6);
  expect(s.matrix?.shape).toEqual([2, 6]);
  // No recon overlays yet — they are recomputed once the TF is available.
  expect(s.local).toBeNull();
  expect(s.global).toBeNull();
  expect(s.muted).toEqual([false, false]);
});

test('seedFromMatrix with an empty matrix leaves the model empty (setId null)', () => {
  const m = createModalStore();
  m.seedFromMatrix(real([0, 6], []), [{ setId: 7, chIn: 0, nChannels: 2, nCols: 1 }], 'acc');
  const s = get(m);
  expect(s.setId).toBeNull();
  expect(s.matrix).toBeNull();
  expect(s.modes).toEqual([]);
});

test('clearWithUndo empties the model but a single undo restores it (with cached recon)', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);   // 2 modes + global
  expect(get(m).global).not.toBeNull();

  m.clearWithUndo();
  const cleared = get(m);
  expect(cleared.modes).toEqual([]);
  expect(cleared.matrix).toBeNull();
  expect(cleared.global).toBeNull();
  expect(cleared.undo).not.toBeNull();               // snapshot stashed

  m.undo();                                           // one click brings it back
  const back = get(m);
  expect(back.modes.map((x) => x.fn)).toEqual([80, 220]);
  expect(back.setId).toBe(3);
  expect(back.global).not.toBeNull();                 // cached recon restored (no engine)
  expect(back.undo).toBeNull();
});

test('mute: toggleMute flips flags, mutedIndices reports them, preserved across same-count applyResult', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);  // 2 modes
  expect(get(m).muted).toEqual([false, false]);

  m.toggleMute(1);
  expect(get(m).muted).toEqual([false, true]);
  expect(m.mutedIndices()).toEqual([1]);

  // A recon recompute (same mode count) must PRESERVE the mute flags…
  m.applyResult(fitResult(), [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);
  expect(get(m).muted).toEqual([false, true]);

  // …but a structural change (different count) resets them.
  m.applyResult({
    M: real([1, 6], [80, 0.02, 1, 0, 0, 0]),
    fn: real([1], [80]), zn: real([1], [0.02]),
    an: real([1, 1], [1]), pn: real([1, 1], [0]), message: '',
    recon_freq_axis: real([2], [60, 110]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
    global_freq_axis: real([2], [0, 500]), global_tf_data: cplx([2, 1], [0.5, 0, 0.5, 0]),
  }, [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);
  expect(get(m).muted).toEqual([false]);
});

test('modes carry each column\'s modal constant an and phase in degrees', () => {
  // Two columns: rows [fn, zn, an0, an1, pn0, pn1, rk0, rk1, rm0, rm1].
  const M = real([2, 10], [
    80, 0.02, -1368.6, 2.5, 0.1, -Math.PI / 2, 0, 0, 0, 0,
    220, 0.015, 0.6, 3, Math.PI, 0, 0, 0, 0, 0,
  ]);
  expect(constantsFromMatrix(M)).toEqual([
    { an: [-1368.6, 2.5], pnDeg: [0.1 * 180 / Math.PI, -90] },
    { an: [0.6, 3], pnDeg: [180, 0] },
  ]);
  const m = createModalStore();
  m.seedFromMatrix(M, [{ setId: 7, chIn: 0, nChannels: 3, nCols: 2 }], 'vel');
  expect(get(m).modes[0].an).toEqual([-1368.6, 2.5]);
  expect(get(m).modes[1].pnDeg).toEqual([180, 0]);
  m.applyResult(fitResult(), [{ setId: 3, chIn: 0, nChannels: 2, nCols: 1 }]);
  expect(get(m).modes.map((x) => x.an)).toEqual([[1], [0.6]]);
  expect(constantsFromMatrix(null)).toEqual([]);
});

test('fitColumnLabels names each column as the legend does', () => {
  const lab = (_id: number, ch: number) => `ch_${ch}`;
  const name = (id: number) => `set${id}`;
  // Full set, input ch_1 of 3: columns are ch_0 and ch_2.
  expect(fitColumnLabels([{ setId: 1, chIn: 1, nCols: 2, chans: null }], lab, name))
    .toEqual(['ch_0/ch_1', 'ch_2/ch_1']);
  // A subset fit and an orphan TF, together: set names prefix the lines.
  expect(fitColumnLabels([
    { setId: 1, chIn: 0, nCols: 1, chans: [2] },
    { setId: 4, chIn: null, nCols: 2, chans: null },
  ], lab, name)).toEqual(['set1 · ch_2/ch_0', 'set4 · ch_0', 'set4 · ch_1']);
});
