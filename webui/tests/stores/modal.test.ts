import { expect, test } from 'vitest';
import { get } from 'svelte/store';
import { createModalStore } from '../../src/lib/stores/modal';

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
  m.applyResult(fitResult(), { setId: 3, chIn: 0, nChannels: 2 });
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
  m.applyResult(fitResult(), { setId: 3, chIn: 0, nChannels: 2 });
  // A reject that empties the model: zero-row M, empty summaries + recon.
  m.applyResult({
    M: real([0, 0], []), fn: real([0], []), zn: real([0], []),
    an: real([0, 0], []), pn: real([0, 0], []), message: 'Mode fits deleted.',
    recon_freq_axis: real([0], []), recon_tf_data: cplx([0, 1], []),
    global_freq_axis: real([0], []), global_tf_data: cplx([0, 1], []),
  }, { setId: 3, chIn: 0, nChannels: 2 });
  const s = get(m);
  expect(s.matrix).toBeNull();
  expect(s.setId).toBeNull();
  expect(s.modes).toEqual([]);
  expect(s.local).toBeNull();
  expect(s.global).toBeNull();
});

test('showGlobal toggles independently and survives a fresh fit', () => {
  const m = createModalStore();
  expect(get(m).showGlobal).toBe(false);
  m.toggleGlobal();
  expect(get(m).showGlobal).toBe(true);
  m.applyResult(fitResult(), { setId: 1, chIn: 0, nChannels: 2 });
  // A new fit must NOT silently flip the overlay toggle off.
  expect(get(m).showGlobal).toBe(true);
  m.setShowGlobal(false);
  expect(get(m).showGlobal).toBe(false);
});

test('reset returns to the empty state', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), { setId: 1, chIn: 0, nChannels: 2 });
  m.toggleGlobal();
  m.reset();
  const s = get(m);
  expect(s.setId).toBeNull();
  expect(s.modes).toEqual([]);
  expect(s.matrix).toBeNull();
  expect(s.showGlobal).toBe(false);
  expect(s.muted).toEqual([]);
  expect(s.showLocal).toBe(true);
  expect(s.undo).toBeNull();
});

test('showLocal toggles independently (default on) and mt mirrors the card', () => {
  const m = createModalStore();
  expect(get(m).showLocal).toBe(true);   // local overlay shown by default
  m.toggleLocal();
  expect(get(m).showLocal).toBe(false);
  m.setShowLocal(true);
  expect(get(m).showLocal).toBe(true);
  expect(get(m).mt).toBe('acc');
  m.setMt('vel');
  expect(get(m).mt).toBe('vel');
});

test('undo slot: pushUndo snapshots, undo restores, one level only', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), { setId: 3, chIn: 0, nChannels: 2 });  // 2 modes
  expect(get(m).undo).toBeNull();

  m.pushUndo();                                   // snapshot the 2-mode model
  expect(get(m).undo).not.toBeNull();

  // A destructive change: reject down to nothing.
  m.applyResult({
    M: real([0, 0], []), fn: real([0], []), zn: real([0], []),
    an: real([0, 0], []), pn: real([0, 0], []), message: 'Mode fits deleted.',
    recon_freq_axis: real([0], []), recon_tf_data: cplx([0, 1], []),
    global_freq_axis: real([0], []), global_tf_data: cplx([0, 1], []),
  }, { setId: 3, chIn: 0, nChannels: 2 });
  expect(get(m).modes).toEqual([]);

  m.undo();                                        // restore the 2-mode model
  const s = get(m);
  expect(s.modes.map((x) => x.fn)).toEqual([80, 220]);
  expect(s.setId).toBe(3);
  expect(s.undo).toBeNull();                       // slot cleared after undo
});

test('mute: toggleMute flips flags, mutedIndices reports them, preserved across same-count applyResult', () => {
  const m = createModalStore();
  m.applyResult(fitResult(), { setId: 3, chIn: 0, nChannels: 2 });  // 2 modes
  expect(get(m).muted).toEqual([false, false]);

  m.toggleMute(1);
  expect(get(m).muted).toEqual([false, true]);
  expect(m.mutedIndices()).toEqual([1]);

  // A recon recompute (same mode count) must PRESERVE the mute flags…
  m.applyResult(fitResult(), { setId: 3, chIn: 0, nChannels: 2 });
  expect(get(m).muted).toEqual([false, true]);

  // …but a structural change (different count) resets them.
  m.applyResult({
    M: real([1, 6], [80, 0.02, 1, 0, 0, 0]),
    fn: real([1], [80]), zn: real([1], [0.02]),
    an: real([1, 1], [1]), pn: real([1, 1], [0]), message: '',
    recon_freq_axis: real([2], [60, 110]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
    global_freq_axis: real([2], [0, 500]), global_tf_data: cplx([2, 1], [0.5, 0, 0.5, 0]),
  }, { setId: 3, chIn: 0, nChannels: 2 });
  expect(get(m).muted).toEqual([false]);
});
