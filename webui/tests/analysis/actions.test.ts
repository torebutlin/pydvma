import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

/** A marshalled complex array (interleaved [re,im,…]) as glue.py returns. */
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });
const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });

/** Build a 2-set, 2-channel TimeData-only dataset (matches the fixture shape). */
function makeDataset(nSets = 2): DvmaDataset {
  const items: DvmaItem[] = [];
  for (let s = 0; s < nSets; s++) {
    items.push({
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
        time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
      },
      meta: { test_name: `set_${s}`, timestring: `t${s}` },
      settings: { fs: 2 },
    });
  }
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
}

interface Recorded { op: string; payload: Record<string, unknown>; }

/**
 * Fake engine store recording every enqueue and returning a canned
 * result. `responder` lets a test control the resolution (value or a
 * deferred promise) to exercise out-of-order settling.
 */
function fakeEngine(
  responder: (op: string, payload: Record<string, unknown>) => Promise<unknown>,
): { engine: EngineStore; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const engine = {
    status: writable('ready'),
    boot: async () => {},
    whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      calls.push({ op, payload });
      return responder(op, payload);
    },
    client: {} as any,
  } as unknown as EngineStore;
  return { engine, calls };
}

const tfResult = () => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, 1], [1, 0, 1, 0]),
  coherence: real([2, 1], [0.9, 0.8]),
});

test('loadDataset registers one selection set per TimeData item and seeds time arrays', () => {
  const sel = createSelection();
  const { engine } = fakeEngine(async () => ({}));
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(2));
  expect(get(sel.sets)).toHaveLength(2);
  const d = get(actions.derived);
  expect(Object.keys(d)).toHaveLength(2);
  // channel-1 column of the first set is [2,4,6]
  expect(Array.from(d[0].time!.data.re)).toEqual([1, 2, 3, 4, 5, 6]);
});

test('cleanImpulse re-emits the dataset store so autosave captures the cleaned data', async () => {
  // Regression: cleanImpulse mutates the source item's arrays IN PLACE (the
  // item is shared by reference with the `dataset` store). The plot updates
  // via setDerived, but autosave is driven by a `dataset` subscription — so
  // without an explicit re-emit the cleaned impulse is never autosaved and a
  // tab-close loses it. This asserts the store re-emits (and the mutation is
  // visible for the explicit-Save path too).
  const sel = createSelection();
  const { engine, calls } = fakeEngine(async (op) => {
    if (op === 'clean_impulse') return {
      time_axis: real([3], [0, 0.5, 1]),
      time_data: real([3, 2], [0, 0, 3, 4, 0, 0]),   // zeroed outside the impulse
    };
    return {};
  });
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(1));

  // Subscribe AFTER load; discount the synchronous initial callback.
  let emissions = 0;
  const unsub = actions.dataset.subscribe(() => { emissions++; });
  emissions = 0;

  await actions.cleanImpulse(0, 0);
  unsub();

  expect(calls.some(c => c.op === 'clean_impulse')).toBe(true);
  expect(emissions, 'cleanImpulse must re-emit dataset so autosave fires').toBeGreaterThan(0);
  const ds = get(actions.dataset)!;
  expect(Array.from(ds.items[0].arrays.time_data.data)).toEqual([0, 0, 3, 4, 0, 0]);
});

test("calcTf 'within' issues one calc_tf per set with n_frames from resolution", async () => {
  const sel = createSelection();
  const { engine, calls } = fakeEngine(async () => tfResult());
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(2));
  await actions.calcTf(0, 'hann', 'within', 7);
  const tf = calls.filter(c => c.op === 'calc_tf');
  expect(tf).toHaveLength(2);
  expect(tf[0].payload.n_frames).toBe(7);
  expect(calls.some(c => c.op === 'calc_tf_averaged')).toBe(false);
});

test("calcTf 'none' issues calc_tf per set with n_frames = 1", async () => {
  const sel = createSelection();
  const { engine, calls } = fakeEngine(async () => tfResult());
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(2));
  await actions.calcTf(0, null, 'none', 20);
  const tf = calls.filter(c => c.op === 'calc_tf');
  expect(tf).toHaveLength(2);
  expect(tf.every(c => c.payload.n_frames === 1)).toBe(true);
});

test("calcTf 'across' issues one calc_tf_averaged over all sets", async () => {
  const sel = createSelection();
  const { engine, calls } = fakeEngine(async () => tfResult());
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(3));
  await actions.calcTf(1, 'hann', 'across', 5);
  const avg = calls.filter(c => c.op === 'calc_tf_averaged');
  expect(avg).toHaveLength(1);
  expect((avg[0].payload.sets as unknown[]).length).toBe(3);
  expect(avg[0].payload.ch_in).toBe(1);
});

test('stale calcTf resolves out of order: only the latest result is kept', async () => {
  const sel = createSelection();
  // First call resolves LATE (deferred), second resolves immediately.
  let releaseFirst!: (v: unknown) => void;
  let n = 0;
  const { engine } = fakeEngine((op) => {
    if (op !== 'calc_tf') return Promise.resolve({});
    n++;
    if (n === 1) return new Promise(res => { releaseFirst = res; });
    // Second batch: a distinctly-shaped tf_data (3 freq bins) so we can tell them apart.
    return Promise.resolve({
      freq_axis: real([3], [0, 1, 2]),
      tf_data: cplx([3, 1], [2, 0, 2, 0, 2, 0]),
      coherence: real([3, 1], [1, 1, 1]),
    });
  });
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(1));

  const p1 = actions.calcTf(0, null, 'within', 4);   // stale (resolves last)
  const p2 = actions.calcTf(0, null, 'within', 8);   // latest
  await p2;
  releaseFirst(tfResult());                          // now let the first settle
  await p1;

  const d = get(actions.derived);
  // The kept tf must be the LATEST (3 freq bins), not the stale 2-bin one.
  expect(d[0].tf!.axis.length).toBe(3);
});

test('engine rejection sets computeError and does not hang', async () => {
  const sel = createSelection();
  const { engine } = fakeEngine(async () => { throw new Error('engine failed to boot: bang'); });
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(1));
  await actions.calcFft(null);
  expect(get(actions.computeError)).toContain('engine failed to boot');
  expect(get(actions.busy)).toBe(false);
});

test('calcSono issues calc_sono with nperseg=nFft, noverlap=nFft/2', async () => {
  const sel = createSelection();
  const { engine, calls } = fakeEngine(async () => ({
    time_axis: real([2], [0, 1]),
    freq_axis: real([2], [0, 1]),
    sono_data: real([2, 2], [1, 2, 3, 4]),
  }));
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(1));
  await actions.calcSono(0, 0, 64);
  const sono = calls.find(c => c.op === 'calc_sono')!;
  expect(sono.payload.nperseg).toBe(64);
  expect(sono.payload.noverlap).toBe(32);
});

test('two DIFFERENT action kinds racing: neither cross-drops the other', async () => {
  // Regression for the CRITICAL global-seq bug: a calcSono issued while a
  // calcTf is in flight must NOT drop the TF result when TF resolves later.
  // With a single global counter, calcSono's bump makes calcTf's guard read
  // stale → TF silently dropped (this test FAILS on that code). With a
  // PER-KIND guard, 'sono' and 'tf' counters are independent → both commit.
  const sel = createSelection();
  let releaseTf!: (v: unknown) => void;
  const { engine } = fakeEngine((op) => {
    if (op === 'calc_tf') return new Promise(res => { releaseTf = res; });   // TF resolves LAST
    if (op === 'calc_sono') return Promise.resolve({
      time_axis: real([2], [0, 1]),
      freq_axis: real([2], [0, 1]),
      sono_data: real([2, 2], [1, 2, 3, 4]),
    });
    return Promise.resolve({});
  });
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(1));

  const pTf = actions.calcTf(0, null, 'within', 4);   // in flight (deferred)
  await actions.calcSono(0, 0, 64);                    // completes first, bumps 'sono'
  releaseTf(tfResult());                               // now let TF settle
  await pTf;

  const d = get(actions.derived);
  // BOTH results must be present — the sonogram did not cross-drop the TF.
  expect(d[0].tf, 'TF result must survive a concurrent sonogram').toBeDefined();
  expect(d[0].sono, 'sonogram result must be present').toBeDefined();
});

test('concurrent actions: busy is ref-counted (stays true until the last settles)', async () => {
  const sel = createSelection();
  let releaseTf!: (v: unknown) => void;
  const { engine } = fakeEngine((op) => {
    if (op === 'calc_tf') return new Promise(res => { releaseTf = res; });
    if (op === 'calc_sono') return Promise.resolve({
      time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]), sono_data: real([2, 2], [1, 2, 3, 4]),
    });
    return Promise.resolve({});
  });
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(1));

  const pTf = actions.calcTf(0, null, 'within', 4);   // still in flight
  await actions.calcSono(0, 0, 64);                    // one action settled...
  expect(get(actions.busy), 'busy must stay true while TF is still running').toBe(true);
  releaseTf(tfResult());
  await pTf;
  expect(get(actions.busy), 'busy clears only after the last action settles').toBe(false);
});

test('a concurrent action does not erase another kind\'s error unseen', async () => {
  // calcFft fails (sets error); a later successful calcSono of a DIFFERENT
  // kind must not wipe the FFT error before the user sees it.
  const sel = createSelection();
  const { engine } = fakeEngine((op) => {
    if (op === 'calc_fft') return Promise.reject(new Error('engine failed to boot: boom'));
    if (op === 'calc_sono') return Promise.resolve({
      time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]), sono_data: real([2, 2], [1, 2, 3, 4]),
    });
    return Promise.resolve({});
  });
  const actions = createActions(engine, sel);
  actions.loadDataset(makeDataset(1));

  await actions.calcFft(null);
  expect(get(actions.computeError)).toContain('engine failed to boot');
  await actions.calcSono(0, 0, 64);                    // different kind, succeeds
  expect(get(actions.computeError), 'FFT error must survive a later sonogram success').toContain('engine failed to boot');
});
