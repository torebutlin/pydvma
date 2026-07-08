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

/** Build a TimeData-only dataset with one set per entry of `channels`. */
function makeDatasetCh(channels: number[]): DvmaDataset {
  const items: DvmaItem[] = channels.map((nc, s) => ({
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: {
        shape: [3, nc], isComplex: false,
        data: Float64Array.from(Array.from({ length: 3 * nc }, (_, i) => i + 1)),
      },
    },
    meta: { test_name: `set_${s}`, timestring: `t${s}` },
    settings: { fs: 2 },
  }));
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
}

/**
 * An ORPHAN transfer-function item — a TF-only load (e.g. a JW-logger `.mat`
 * whose `yspec` is a bare TF matrix) with NO source TimeData and no matching
 * `id_link`. `loadDataset` gives it its own display set with `Nout` channels
 * (round-5 item 3) but it carries NO time series (round-6 item 2).
 */
function orphanTfItem(nOut = 3): DvmaItem {
  const nf = 2;
  return {
    kind: 'TfData',
    arrays: {
      freq_axis: { shape: [nf], isComplex: false, data: Float64Array.from([0, 1]) },
      tf_data: {
        shape: [nf, nOut], isComplex: true,
        data: Float64Array.from(Array.from({ length: nf * nOut * 2 }, (_, i) => i + 1)),
      },
    },
    meta: { test_name: 'orphan_tf', timestring: 'to' },   // no id_link ⇒ orphan
    settings: null,
  };
}

/** Dataset with one orphan TF item and nothing else (a TF-only tray). */
function makeOrphanOnlyDataset(nOut = 3): DvmaDataset {
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items: [orphanTfItem(nOut)] };
}

/** Dataset whose FIRST item is an orphan TF, followed by `nTime` TimeData sets. */
function makeOrphanFirstDataset(nTime = 1): DvmaDataset {
  const ds = makeDataset(nTime);
  ds.items.unshift(orphanTfItem(3));
  return ds;
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

// ---- Single-channel TF guard (round-2 bug: a 1-channel set has no output
// channel, so calculate_tf returns tf_data (Nf, 0) and the plot draws
// nothing — "TF crashed". Guard: skip it, surface a clear message.) ----

test('calcTf on a single-channel set issues NO worker call and surfaces a clear message', async () => {
  const { engine, calls } = fakeEngine(async () => tfResult());
  const { actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([1]));           // one 1-channel set
  await actions.calcTf('all');
  expect(calls.some((c) => c.op === 'calc_tf'), 'no meaningless worker call').toBe(false);
  expect(get(actions.computeErrors).tf).toMatch(/output channel/i);
  expect(get(actions.busy), 'must not hang').toBe(false);
});

test('calcTf mixed 1ch + 2ch: runs the 2ch set, skips the 1ch, warns which was skipped', async () => {
  const { engine, calls } = fakeEngine(async () => tfResult());
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([1, 2]));        // set 0 = 1ch, set 1 = 2ch
  const [a, b] = get(sel.sets).map((s) => s.id);
  await actions.calcTf('all');
  const tf = calls.filter((c) => c.op === 'calc_tf');
  expect(tf, 'only the multi-channel set ran').toHaveLength(1);
  expect(get(actions.derived)[b].tf, '2-channel set computed').toBeDefined();
  expect(get(actions.derived)[a]?.tf, '1-channel set skipped').toBeUndefined();
  expect(get(actions.computeErrors).tf).toMatch(/output channel/i);
  expect(get(actions.computeErrors).tf).toContain('set_0');   // names the skipped set
});

test("calcTf 'across' with single-channel sets surfaces the message, no crash", async () => {
  const { engine, calls } = fakeEngine(async () => tfResult());
  const { settings, actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([1, 1]));
  settings.patch('all', 'tf', { averaging: 'across', chIn: 0, window: 'hann', nFrames: 5 });
  await actions.calcTf('all');
  expect(calls.some((c) => c.op === 'calc_tf_averaged')).toBe(false);
  expect(get(actions.computeErrors).tf).toMatch(/output channel/i);
});

test('hasComputed: false before Calc, true for the computed view after', async () => {
  const { engine } = fakeEngine(async () => ({
    freq_axis: real([2], [0, 1]), freq_data: cplx([2, 2], [1, 0, 1, 0, 1, 0, 1, 0]),
  }));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));               // one 2-channel set
  const id = get(sel.sets)[0].id;
  expect(actions.hasComputed('all', 'freq')).toBe(false);
  expect(actions.hasComputed(id, 'freq')).toBe(false);
  await actions.calcFft('all');
  expect(actions.hasComputed('all', 'freq')).toBe(true);
  expect(actions.hasComputed(id, 'freq')).toBe(true);
  expect(actions.hasComputed('all', 'tf'), 'other views still uncomputed').toBe(false);
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

// ---- CSD pair (round-5 item 7): the pair is stamped on the csd slice at
// calc time and can be re-stamped live (no recompute) via setCsdPair. ----

test('calcPsd stamps the CSD pair (default 0,1) on the coherence slice', async () => {
  const { engine } = fakeEngine(async () => ({
    freq_axis: real([2], [0, 1]),
    psd: real([2, 2], [1, 2, 3, 4]),
    Cxy: real([2, 2, 2], [1, 1, 1, 1, 1, 1, 1, 1]),
  }));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;
  await actions.calcPsd(id);
  const csd = get(actions.derived)[id].csd!;
  expect(csd.i).toBe(0);
  expect(csd.j).toBe(1);
});

test('setCsdPair re-stamps the slice live from settings, with no recompute', async () => {
  const { engine, calls } = fakeEngine(async () => ({
    freq_axis: real([2], [0, 1]),
    psd: real([2, 2], [1, 2, 3, 4]),
    Cxy: real([2, 2, 2], [1, 1, 1, 1, 1, 1, 1, 1]),
  }));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([3]));           // a 3-channel set
  const id = get(sel.sets)[0].id;
  await actions.calcPsd(id);
  const before = calls.filter((c) => c.op === 'calc_psd').length;

  settings.patch(id, 'freq', { csdX: 1, csdY: 2 });
  actions.setCsdPair(id);

  const csd = get(actions.derived)[id].csd!;
  expect(csd.i).toBe(1);
  expect(csd.j).toBe(2);
  // Pure display change — no extra engine calls.
  expect(calls.filter((c) => c.op === 'calc_psd').length).toBe(before);
});

// ---- PSD partial failure (Round-3 item 1): a set the engine can't handle
// (e.g. glue.py rejects an oversized resolution) must not stop the others;
// the successful set renders and the failing one gets a NAMED message. ----

test('calcPsd all-sets: a set the engine rejects is named; the others still compute', async () => {
  const { engine, calls } = fakeEngine((op, payload) => {
    if (op !== 'calc_psd') return Promise.resolve({});
    // Reject the set whose n_channels==1 (stand-in for the oversized set);
    // succeed for the 2-channel set.
    if (payload.n_channels === 1) {
      return Promise.reject(new Error('PSD at this resolution needs too large an internal buffer for the browser engine.'));
    }
    return Promise.resolve({
      freq_axis: real([2], [0, 1]), psd: real([2, 2], [1, 2, 3, 4]), Cxy: real([2, 2], [1, 1, 1, 1]),
    });
  });
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([2, 1]));           // set_0 = 2ch (ok), set_1 = 1ch (rejected)
  const [a, b] = get(sel.sets).map((s) => s.id);

  await actions.calcPsd('all');
  expect(calls.filter((c) => c.op === 'calc_psd')).toHaveLength(2);   // BOTH attempted
  expect(get(actions.derived)[a]?.psd, '2-channel set rendered').toBeDefined();
  expect(get(actions.derived)[b]?.psd, 'rejected set has no psd').toBeUndefined();
  const err = get(actions.computeErrors).psd;
  expect(err).toContain('set_1');                       // names the failing set
  expect(err).toMatch(/internal buffer|too large/i);    // carries the engine reason
  expect(get(actions.busy), 'must not hang').toBe(false);
});

test('calcPsd clears the psd error on a subsequent all-success run', async () => {
  let failNext = true;
  const { engine } = fakeEngine((op, payload) => {
    if (op !== 'calc_psd') return Promise.resolve({});
    if (failNext && payload.n_channels === 1) {
      return Promise.reject(new Error('too big'));
    }
    return Promise.resolve({
      freq_axis: real([2], [0, 1]), psd: real([2, 2], [1, 2, 3, 4]), Cxy: real([2, 2], [1, 1, 1, 1]),
    });
  });
  const { actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([1]));              // single set that first fails
  await actions.calcPsd('all');
  expect(get(actions.computeErrors).psd).not.toBe('');
  failNext = false;                                     // now it succeeds
  await actions.calcPsd('all');
  expect(get(actions.computeErrors).psd, 'a clean run clears the psd error').toBe('');
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

test('engine rejection sets the fft computeErrors slot and does not hang', async () => {
  const { engine } = fakeEngine(async () => { throw new Error('engine failed to boot: bang'); });
  const { actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  await actions.calcFft('all');
  expect(get(actions.computeErrors).fft).toContain('engine failed to boot');
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
  // Default method is STFT so today's behaviour is preserved.
  expect(sono.payload.method).toBe('stft');
});

test('calcSono passes CWT method + voices/octave + band through to the engine (round-5 item 12)', async () => {
  const { engine, calls } = fakeEngine(async () => ({
    time_axis: real([2], [0, 1]),
    freq_axis: real([2], [0, 1]),
    sono_data: real([2, 2], [1, 2, 3, 4]),
  }));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const a = get(sel.sets)[0].id;
  settings.patch(a, 'sono', { method: 'cwt', voicesPerOctave: 24, w0: 5, fMin: 20, fMax: 400 });
  await actions.calcSono(a, 0);
  const sono = calls.find(c => c.op === 'calc_sono')!;
  expect(sono.payload.method).toBe('cwt');
  expect(sono.payload.voices_per_octave).toBe(24);
  expect(sono.payload.w0).toBe(5);
  expect(sono.payload.f_min).toBe(20);
  expect(sono.payload.f_max).toBe(400);
});

test('calcDamping passes the sono method through (STFT default, CWT when set)', async () => {
  const { engine, calls } = fakeEngine(async () => ({ fn: real([1], [42]), Qn: real([1], [10]) }));
  const { sel, settings, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const a = get(sel.sets)[0].id;

  await actions.calcDamping(a, 0, 512);
  let damp = calls.filter(c => c.op === 'calc_damping').at(-1)!;
  expect(damp.payload.method).toBe('stft');
  expect(damp.payload.nperseg).toBe(512);

  settings.patch(a, 'sono', { method: 'cwt', voicesPerOctave: 16, w0: 6 });
  await actions.calcDamping(a, 0, 512);
  damp = calls.filter(c => c.op === 'calc_damping').at(-1)!;
  expect(damp.payload.method).toBe('cwt');
  expect(damp.payload.voices_per_octave).toBe(16);
  expect(damp.payload.w0).toBe(6);
});

test('a throwing calc_sono surfaces on the FIRST press via computeErrors.sono (round-5 bug 1)', async () => {
  // Round-5: on the 32-bit WASM engine a large-nFFT sonogram overflows scipy's
  // sliding_window_view ("array is too big"). Pressing Calc Sonogram must land
  // that failure in computeErrors.sono on the FIRST press (SonoCard + the
  // under-plot banner both read `$computeErrors.sono`), not stay silent until a
  // later slider drag. This pins the button path's error surface so a future
  // change can't re-swallow it.
  const { engine } = fakeEngine(async (op) => {
    if (op === 'calc_sono') throw new Error('array is too big; and cannot be safely reshaped');
    return {};
  });
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const a = get(sel.sets)[0].id;
  await actions.calcSono(a, 0);                       // the Calc Sonogram button path
  expect(get(actions.computeErrors).sono).toContain('too big');
  expect(get(actions.busy)).toBe(false);             // and it settles (never hangs)
  // The failure is isolated to the sono slot — no other kind is touched.
  expect(get(actions.computeErrors).tf).toBe('');
});

test('a successful calcSono clears a prior sono error (round-5 bug 1)', async () => {
  // After the pydvma low-memory fix a re-press (or a coarser nFFT) succeeds;
  // the stale error must clear so the card stops showing it.
  let fail = true;
  const { engine } = fakeEngine(async (op) => {
    if (op === 'calc_sono') {
      if (fail) throw new Error('array is too big');
      return { time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]),
               sono_data: real([2, 2], [1, 2, 3, 4]) };
    }
    return {};
  });
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const a = get(sel.sets)[0].id;
  await actions.calcSono(a, 0);
  expect(get(actions.computeErrors).sono).toContain('too big');
  fail = false;
  await actions.calcSono(a, 0);
  expect(get(actions.computeErrors).sono).toBe('');
  expect(get(actions.derived)[a].sono).toBeDefined();
});

test('calcSono clamps an out-of-range channel to the set range (round-4 bug 1)', async () => {
  // Regression: the sono channel select is card-local state that survives a
  // target switch, so a stale ch (e.g. ch_1 picked on a 2-channel set) can
  // exceed a MONO set's channel count. Sent as-is the engine raises IndexError
  // and the sonogram renders nothing while PSD still works. calcSono must
  // clamp the channel so the engine only ever sees a real channel index.
  const { engine, calls } = fakeEngine(async () => ({
    time_axis: real([2], [0, 1]),
    freq_axis: real([2], [0, 1]),
    sono_data: real([2, 2], [1, 2, 3, 4]),
  }));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([1]));         // one MONO set
  const a = get(sel.sets)[0].id;
  await actions.calcSono(a, 5);                     // stale, out-of-range channel
  const sono = calls.find(c => c.op === 'calc_sono')!;
  expect(sono.payload.ch).toBe(0);                  // clamped to the only channel
  // The result is committed (not dropped by the clamp), so a sono slice lands.
  expect(get(actions.derived)[a].sono).toBeDefined();
});

test('workingSets() flags time-bearing vs orphan-TF sets (round-6 items 2/3)', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { actions } = harness(engine);
  actions.loadDataset(makeOrphanFirstDataset(1));    // [orphan TF, 1 TimeData]
  const ws = actions.workingSets();
  expect(ws.length).toBe(2);
  // The orphan TF set carries NO time data; the TimeData set does. The Sono
  // card lists only the latter as a sonogram target.
  const orphan = ws.find((w) => w.hasTime === false);
  const timeSet = ws.find((w) => w.hasTime === true);
  expect(orphan).toBeDefined();
  expect(timeSet).toBeDefined();
});

test('calcSono on a time-less orphan set fails with a CLEAR message, no deref crash (round-6 item 2)', async () => {
  // The bug Tore hit: a sonogram on an orphan TF (no time series) dereferenced
  // a missing `time_axis` → opaque "Cannot read properties of undefined
  // (reading 'data')" and a WHITE plot. It must instead land a clear,
  // actionable message in computeErrors.sono and never crash the module.
  const { engine, calls } = fakeEngine(async () => ({
    time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]),
    sono_data: real([2, 2], [1, 2, 3, 4]),
  }));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeOrphanOnlyDataset(3));
  const orphanId = get(sel.sets)[0].id;
  await actions.calcSono(orphanId, 0);
  const msg = get(actions.computeErrors).sono;
  expect(msg).toContain('no time data');
  expect(msg).not.toContain('undefined');            // not the raw deref TypeError
  expect(get(actions.busy)).toBe(false);             // settles, never hangs
  // No calc_sono worker call was issued for a set that can't produce one.
  expect(calls.some((c) => c.op === 'calc_sono')).toBe(false);
});

test('calcSono("all") skips a leading orphan set and computes the first TIME-BEARING set (round-6 item 2)', async () => {
  // 'all' is not a real sonogram target, but if one is passed it must resolve
  // to a time-bearing set — never the leading orphan (which would blank the
  // plot). Regression for `working[0]` blindly picking the orphan.
  const { engine, calls } = fakeEngine(async () => ({
    time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]),
    sono_data: real([2, 2], [1, 2, 3, 4]),
  }));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeOrphanFirstDataset(1));    // [orphan TF, 1 TimeData]
  await actions.calcSono('all', 0);
  expect(get(actions.computeErrors).sono).toBe('');  // computed, no error
  const sonoCall = calls.find((c) => c.op === 'calc_sono');
  expect(sonoCall).toBeDefined();
  // The sono slice landed on the TIME-BEARING set, not the orphan.
  const timeSetId = actions.workingSets().find((w) => w.hasTime)!.setId;
  expect(get(actions.derived)[timeSetId].sono).toBeDefined();
});

test('calcDamping on a time-less orphan set rejects with a CLEAR message (round-6 item 2)', async () => {
  const { engine, calls } = fakeEngine(async () => ({ fn: real([1], [42]), Qn: real([1], [10]) }));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeOrphanOnlyDataset(3));
  const orphanId = get(sel.sets)[0].id;
  await expect(actions.calcDamping(orphanId, 0, 512)).rejects.toThrow(/no time data/);
  expect(calls.some((c) => c.op === 'calc_damping')).toBe(false);
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
  expect(get(actions.computeErrors).fft).toContain('engine failed to boot');
  await actions.calcSono(0, 0);                         // different kind, succeeds
  expect(get(actions.computeErrors).fft, 'FFT error must survive a later sonogram success').toContain('engine failed to boot');
  expect(get(actions.computeErrors).sono, 'sono kind stays clear on success').toBe('');
});

// ---- Per-kind error scoping (Round-3 item 2): a failed TF must NOT poison
// the Sonogram. A single global error store showed the TF message on the
// sono card and made sono look dead; per-kind slots keep each card's error
// isolated and let sono compute normally. ----

test('a failed TF does not block or poison a later Sonogram', async () => {
  const { engine, calls } = fakeEngine((op) => {
    if (op === 'calc_sono') return Promise.resolve({
      time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]), sono_data: real([2, 2], [1, 2, 3, 4]),
    });
    return Promise.resolve({});
  });
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDatasetCh([1]));              // single-channel → TF has no output
  const setId = get(sel.sets)[0].id;

  await actions.calcTf('all');                          // fails gracefully (tf slot)
  expect(get(actions.computeErrors).tf).toMatch(/output channel/i);

  await actions.calcSono('all', 0);                     // must still compute
  expect(calls.some((c) => c.op === 'calc_sono'), 'sono actually ran').toBe(true);
  expect(get(actions.derived)[setId]?.sono, 'sono produced output').toBeDefined();
  expect(get(actions.computeErrors).sono, 'sono has NO error of its own').toBe('');
  expect(get(actions.computeErrors).tf, 'the TF error stays on the TF kind only').toMatch(/output channel/i);
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
  // The CSD pair (round-5 item 7) rides along in the persisted freq settings.
  expect(item.ui!.analysis!.freq).toEqual({ window: 'flattop', mode: 'psd', nFrames: 25, csdX: 0, csdY: 1 });
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

// ---- Calibration (Wave-A Task A2): loadDataset seeds derived.calFactors from
// item meta; getCalibration reads it back; setCalFactors writes meta + derived
// + re-emits; a codec round-trip preserves the edited factors. ----

test('loadDataset seeds derived.calFactors from item.meta.channel_cal_factors', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  const ds = makeDataset(1);                       // one 2-channel set
  ds.items[0].meta.channel_cal_factors = [10, 1];
  ds.items[0].meta.units = ['g', 'V'];
  actions.loadDataset(ds);
  const id = get(sel.sets)[0].id;
  expect(get(actions.derived)[id].calFactors).toEqual([10, 1]);
});

test('loadDataset defaults calFactors to all-ones when meta has none', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));             // no channel_cal_factors in meta
  const id = get(sel.sets)[0].id;
  expect(get(actions.derived)[id].calFactors).toEqual([1, 1]);   // identity
});

test('getCalibration returns normalized factors + units (defaults V, length == channels)', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  const ds = makeDataset(1);
  ds.items[0].meta.channel_cal_factors = [5];      // short: pad to 2
  ds.items[0].meta.units = ['N'];                  // short: pad with 'V'
  actions.loadDataset(ds);
  const id = get(sel.sets)[0].id;
  expect(actions.getCalibration(id)).toEqual({ factors: [5, 1], units: ['N', 'V'] });
});

test('setCalFactors writes item meta (channel_cal_factors + units) AND the derived slice', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;

  actions.setCalFactors(id, [10, 2], ['g', 'm/s²']);

  // Derived slice (drives the plot) updated.
  expect(get(actions.derived)[id].calFactors).toEqual([10, 2]);
  // Source item meta persisted (the .dvma field, not the ui blob).
  const item = get(actions.dataset)!.items[0];
  expect(item.meta.channel_cal_factors).toEqual([10, 2]);
  expect(item.meta.units).toEqual(['g', 'm/s²']);
});

test('setCalFactors guards length: pads/truncates factors to the channel count', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));             // 2 channels
  const id = get(sel.sets)[0].id;

  actions.setCalFactors(id, [7]);                  // too short → pad with 1
  expect(get(actions.derived)[id].calFactors).toEqual([7, 1]);

  actions.setCalFactors(id, [3, 4, 5, 6]);         // too long → truncate
  expect(get(actions.derived)[id].calFactors).toEqual([3, 4]);
});

test('setCalFactors re-emits the dataset store so autosave captures the calibration', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;

  let emissions = 0;
  const unsub = actions.dataset.subscribe(() => { emissions++; });
  emissions = 0;                                   // discount the initial sync callback
  actions.setCalFactors(id, [10, 1]);
  unsub();
  expect(emissions, 'setCalFactors must re-emit dataset for autosave').toBeGreaterThan(0);
});

test('setCalFactors keeps meta + metaRaw consistent on a codec-loaded item', () => {
  // A .dvma-loaded item carries metaRaw (tagged). setItemMeta must update BOTH
  // views so writeDvma (which serializes metaRaw) sees the new factors.
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  const ds = makeDataset(1);
  ds.items[0].metaRaw = { ...ds.items[0].meta };   // simulate a codec-loaded item
  actions.loadDataset(ds);
  const id = get(sel.sets)[0].id;

  actions.setCalFactors(id, [4, 8], ['g', 'g']);
  const item = get(actions.dataset)!.items[0];
  expect(item.meta.channel_cal_factors).toEqual([4, 8]);
  expect(item.metaRaw!.channel_cal_factors).toEqual([4, 8]);
  expect(item.metaRaw!.units).toEqual(['g', 'g']);
});

test('codec round-trip: setCalFactors → writeDvma → readDvma → loadDataset preserves factors + units', () => {
  const { engine } = fakeEngine(async () => ({}));
  const { sel, actions } = harness(engine);
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;

  actions.setCalFactors(id, [10, 1], ['g', 'V']);
  const bytes = writeDvma(get(actions.dataset)!);

  // Fresh harness — load the round-tripped dataset.
  const { sel: sel2, actions: a2 } = harness(engine);
  a2.loadDataset(readDvma(bytes));
  const id2 = get(sel2.sets)[0].id;

  expect(get(a2.derived)[id2].calFactors).toEqual([10, 1]);     // seeded on load
  expect(a2.getCalibration(id2)).toEqual({ factors: [10, 1], units: ['g', 'V'] });
});
