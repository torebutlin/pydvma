import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';

/** Build the (selection, settings, actions) trio bound to a fake engine. */
function harness(engine: EngineStore) {
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const actions = createActions(engine, sel, settings);
  return { sel, settings, actions };
}

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
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
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
  const { engine, calls } = fakeEngine(async (op) => {
    if (op === 'clean_impulse') return {
      time_axis: real([3], [0, 0.5, 1]),
      time_data: real([3, 2], [0, 0, 3, 4, 0, 0]),   // zeroed outside the impulse
    };
    return {};
  });
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));

  // Subscribe AFTER load; discount the synchronous initial callback.
  let emissions = 0;
  const unsub = actions.dataset.subscribe(() => { emissions++; });
  emissions = 0;

  await actions.cleanImpulse(0, 0);           // setId 0
  unsub();

  expect(calls.some(c => c.op === 'clean_impulse')).toBe(true);
  expect(emissions, 'cleanImpulse must re-emit dataset so autosave fires').toBeGreaterThan(0);
  const ds = get(actions.dataset)!;
  expect(Array.from(ds.items[0].arrays.time_data.data)).toEqual([0, 0, 3, 4, 0, 0]);
});

test("calcTf 'within' issues one calc_tf per set with n_frames from settings", async () => {
  const { engine, calls } = fakeEngine(async () => tfResult());
  const { settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(2));
  settings.patch('all', 'tf', { averaging: 'within', nFrames: 7, window: 'hann' });
  await actions.calcTf('all');
  const tf = calls.filter(c => c.op === 'calc_tf');
  expect(tf).toHaveLength(2);
  expect(tf[0].payload.n_frames).toBe(7);
  expect(calls.some(c => c.op === 'calc_tf_averaged')).toBe(false);
});

test('calcTf carries chIn + nChannels onto the tf slice (R4 out/in remap)', async () => {
  const { engine } = fakeEngine(async () => tfResult());
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));           // one 2-channel set
  const a = get(sel.sets)[0].id;
  settings.patch(a, 'tf', { averaging: 'within', chIn: 1, window: 'hann', nFrames: 4 });
  await actions.calcTf(a);
  const tf = get(actions.derived)[a].tf!;
  expect(tf.chIn).toBe(1);                        // the input channel it ran with
  expect(tf.nChannels).toBe(2);                   // source channel count (for the remap)
});

test('calcTf across carries the ensemble chIn onto the first set slice (R4)', async () => {
  const { engine } = fakeEngine(async () => tfResult());
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(3));
  settings.patch('all', 'tf', { averaging: 'across', chIn: 1, window: 'hann', nFrames: 5 });
  await actions.calcTf('all');
  const first = get(sel.sets)[0].id;
  const tf = get(actions.derived)[first].tf!;
  expect(tf.chIn).toBe(1);                        // ensemble ran with chIn=1
  expect(tf.nChannels).toBe(2);                   // first set's channel count
});

test("calcTf 'none' issues calc_tf per set with n_frames = 1", async () => {
  const { engine, calls } = fakeEngine(async () => tfResult());
  const { settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(2));
  settings.patch('all', 'tf', { averaging: 'none', nFrames: 20, window: 'none' });
  await actions.calcTf('all');
  const tf = calls.filter(c => c.op === 'calc_tf');
  expect(tf).toHaveLength(2);
  expect(tf.every(c => c.payload.n_frames === 1)).toBe(true);
  expect(tf.every(c => c.payload.window === null)).toBe(true);   // 'none' → null
});

test("calcTf 'across' issues one calc_tf_averaged over all sets", async () => {
  const { engine, calls } = fakeEngine(async () => tfResult());
  const { settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(3));
  settings.patch('all', 'tf', { averaging: 'across', chIn: 1, window: 'hann', nFrames: 5 });
  await actions.calcTf('all');
  const avg = calls.filter(c => c.op === 'calc_tf_averaged');
  expect(avg).toHaveLength(1);
  expect((avg[0].payload.sets as unknown[]).length).toBe(3);
  expect(avg[0].payload.ch_in).toBe(1);
});

test('calcTf targets ONE set with ITS OWN window; other sets untouched', async () => {
  const { engine, calls } = fakeEngine(async () => tfResult());
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(2));       // setIds 0 and 1
  const [a, b] = get(sel.sets).map(s => s.id);
  settings.patch(a, 'tf', { window: 'hann', averaging: 'within', nFrames: 4 });
  settings.patch(b, 'tf', { window: 'flattop', averaging: 'within', nFrames: 9 });

  await actions.calcTf(b);                    // target just set b
  const tf = calls.filter(c => c.op === 'calc_tf');
  expect(tf).toHaveLength(1);                 // ran ONLY the targeted set
  expect(tf[0].payload.window).toBe('flattop');
  expect(tf[0].payload.n_frames).toBe(9);
});

test('calcFft targets per-set: two sets, different windows, one calc_fft each', async () => {
  const { engine, calls } = fakeEngine(async () => ({
    freq_axis: real([2], [0, 1]), freq_data: cplx([2, 2], [1, 0, 1, 0, 1, 0, 1, 0]),
  }));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(2));
  const [a, b] = get(sel.sets).map(s => s.id);
  settings.patch(a, 'freq', { window: 'hann' });
  settings.patch(b, 'freq', { window: 'flattop' });

  await actions.calcFft('all');
  const fft = calls.filter(c => c.op === 'calc_fft');
  expect(fft).toHaveLength(2);
  expect(fft.map(c => c.payload.window).sort()).toEqual(['flattop', 'hann']);
});

test("calcPsd reads each set's window + n_frames from settings", async () => {
  const { engine, calls } = fakeEngine(async () => ({
    freq_axis: real([2], [0, 1]),
    psd: real([2, 2], [1, 2, 3, 4]),
    Cxy: real([2, 2], [1, 1, 1, 1]),
  }));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const a = get(sel.sets)[0].id;
  settings.patch(a, 'freq', { window: 'flattop', nFrames: 12 });
  await actions.calcPsd(a);
  const psd = calls.find(c => c.op === 'calc_psd')!;
  expect(psd.payload.window).toBe('flattop');
  expect(psd.payload.n_frames).toBe(12);
});

test('stale calcTf resolves out of order: only the latest result is kept', async () => {
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
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));

  const p1 = actions.calcTf('all');   // stale (resolves last)
  const p2 = actions.calcTf('all');   // latest
  await p2;
  releaseFirst(tfResult());                          // now let the first settle
  await p1;

  const d = get(actions.derived);
  // The kept tf must be the LATEST (3 freq bins), not the stale 2-bin one.
  expect(d[0].tf!.axis.length).toBe(3);
});

test('engine rejection sets computeError and does not hang', async () => {
  const { engine } = fakeEngine(async () => { throw new Error('engine failed to boot: bang'); });
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  await actions.calcFft('all');
  expect(get(actions.computeError)).toContain('engine failed to boot');
  expect(get(actions.busy)).toBe(false);
});

test('calcSono issues calc_sono with nperseg=nFft (from settings), noverlap=nFft/2', async () => {
  const { engine, calls } = fakeEngine(async () => ({
    time_axis: real([2], [0, 1]),
    freq_axis: real([2], [0, 1]),
    sono_data: real([2, 2], [1, 2, 3, 4]),
  }));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const a = get(sel.sets)[0].id;
  settings.patch(a, 'sono', { nFft: 64 });
  await actions.calcSono(a, 0);
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
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));

  const pTf = actions.calcTf('all');                   // in flight (deferred)
  await actions.calcSono(0, 0);                         // completes first, bumps 'sono'
  releaseTf(tfResult());                               // now let TF settle
  await pTf;

  const d = get(actions.derived);
  // BOTH results must be present — the sonogram did not cross-drop the TF.
  expect(d[0].tf, 'TF result must survive a concurrent sonogram').toBeDefined();
  expect(d[0].sono, 'sonogram result must be present').toBeDefined();
});

test('concurrent actions: busy is ref-counted (stays true until the last settles)', async () => {
  let releaseTf!: (v: unknown) => void;
  const { engine } = fakeEngine((op) => {
    if (op === 'calc_tf') return new Promise(res => { releaseTf = res; });
    if (op === 'calc_sono') return Promise.resolve({
      time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]), sono_data: real([2, 2], [1, 2, 3, 4]),
    });
    return Promise.resolve({});
  });
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));

  const pTf = actions.calcTf('all');                   // still in flight
  await actions.calcSono(0, 0);                         // one action settled...
  expect(get(actions.busy), 'busy must stay true while TF is still running').toBe(true);
  releaseTf(tfResult());
  await pTf;
  expect(get(actions.busy), 'busy clears only after the last action settles').toBe(false);
});

test('a concurrent action does not erase another kind\'s error unseen', async () => {
  // calcFft fails (sets error); a later successful calcSono of a DIFFERENT
  // kind must not wipe the FFT error before the user sees it.
  const { engine } = fakeEngine((op) => {
    if (op === 'calc_fft') return Promise.reject(new Error('engine failed to boot: boom'));
    if (op === 'calc_sono') return Promise.resolve({
      time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]), sono_data: real([2, 2], [1, 2, 3, 4]),
    });
    return Promise.resolve({});
  });
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));

  await actions.calcFft('all');
  expect(get(actions.computeError)).toContain('engine failed to boot');
  await actions.calcSono(0, 0);                         // different kind, succeeds
  expect(get(actions.computeError), 'FFT error must survive a later sonogram success').toContain('engine failed to boot');
});

// ---- Plan 2 persistence: loadDataset restore + stampUiState ----

test('loadDataset restores channel labels from item.ui', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  const ds = makeDataset(1);
  ds.items[0].ui = { channel_labels: { '0': 'hammer', '1': 'accel' } };
  actions.loadDataset(ds);
  const ids = get(sel.sets);
  expect(get(sel.channelLabel)(ids[0].id, 0)).toBe('hammer');
  expect(get(sel.channelLabel)(ids[0].id, 1)).toBe('accel');
});

test('loadDataset restores analysis settings from item.ui', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, settings, actions } = harness(engine);
  const ds = makeDataset(1);
  ds.items[0].ui = {
    analysis: {
      freq: { window: 'flattop', mode: 'psd', nFrames: 20 },
      tf: { chIn: 1, window: 'blackman', averaging: 'across', nFrames: 7 },
      sono: { nFft: 2048, dynRangeDb: 40 },
    },
  };
  actions.loadDataset(ds);
  const setId = get(sel.sets)[0].id;
  const f = settings.get(setId, 'freq');
  expect(f.window).toBe('flattop');
  expect(f.mode).toBe('psd');
  expect(f.nFrames).toBe(20);
  const t = settings.get(setId, 'tf');
  expect(t.chIn).toBe(1);
  expect(t.window).toBe('blackman');
  expect(t.averaging).toBe('across');
  expect(t.nFrames).toBe(7);
  const s = settings.get(setId, 'sono');
  expect(s.nFft).toBe(2048);
  expect(s.dynRangeDb).toBe(40);
});

test('loadDataset with no ui field uses default settings and labels', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, settings, actions } = harness(engine);
  const ds = makeDataset(1);
  // No ui field at all — should not crash.
  actions.loadDataset(ds);
  const setId = get(sel.sets)[0].id;
  expect(get(sel.channelLabel)(setId, 0)).toBe('ch_0');   // default label
  const f = settings.get(setId, 'freq');
  expect(f.window).toBe('hann');                           // default
  expect(f.mode).toBe('fft');
});

test('stampUiState writes labels and settings onto DvmaItems', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const setId = get(sel.sets)[0].id;

  // Set custom labels and non-default settings.
  sel.renameChannel(setId, 0, 'impact');
  settings.patch(setId, 'freq', { window: 'flattop', mode: 'psd', nFrames: 25 });

  actions.stampUiState();

  const ds = get(actions.dataset)!;
  const item = ds.items.find(i => i.kind === 'TimeData')!;
  expect(item.ui).toBeDefined();
  expect(item.ui!.channel_labels).toEqual({ '0': 'impact' });
  expect(item.ui!.analysis!.freq).toEqual({ window: 'flattop', mode: 'psd', nFrames: 25 });
});

test('stampUiState omits ui when labels and settings are all defaults', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));

  // No custom labels, all default settings — stamp should clear ui.
  actions.stampUiState();

  const ds = get(actions.dataset)!;
  const item = ds.items.find(i => i.kind === 'TimeData')!;
  expect(item.ui).toBeUndefined();
});

test('full round-trip: stamp → writeDvma → readDvma → loadDataset restores labels + settings', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(2));
  const [a, b] = get(sel.sets).map(s => s.id);

  // Customise set A labels and settings; leave set B at defaults.
  sel.renameChannel(a, 1, 'response');
  settings.patch(a, 'tf', { chIn: 1, averaging: 'across', nFrames: 3 });

  // Stamp + serialise.
  actions.stampUiState();
  const bytes = writeDvma(get(actions.dataset)!);

  // Fresh harness — load the round-tripped dataset.
  const { sel: sel2, settings: s2, actions: a2 } = harness(engine);
  a2.loadDataset(readDvma(bytes));

  const ids2 = get(sel2.sets).map(s => s.id);
  // Set A (now first) should have the custom label + tf settings.
  expect(get(sel2.channelLabel)(ids2[0], 1)).toBe('response');
  expect(get(sel2.channelLabel)(ids2[0], 0)).toBe('ch_0');    // default
  const tf = s2.get(ids2[0], 'tf');
  expect(tf.chIn).toBe(1);
  expect(tf.averaging).toBe('across');
  expect(tf.nFrames).toBe(3);

  // Set B should still have defaults.
  expect(get(sel2.channelLabel)(ids2[1], 0)).toBe('ch_0');
  expect(s2.get(ids2[1], 'tf').averaging).toBe('within');     // default
});
