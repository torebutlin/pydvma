import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

/** A 1-set, 2-channel TimeData-only dataset. */
function makeDataset(): DvmaDataset {
  const items: DvmaItem[] = [{
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: 'set_0', timestring: 't0' },
    settings: { fs: 2 },
  }];
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
}

interface Recorded { op: string; payload: Record<string, unknown>; }
function fakeEngine(responder: (op: string, payload: Record<string, unknown>) => unknown): { engine: EngineStore; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      calls.push({ op, payload });
      return Promise.resolve(responder(op, payload));
    },
    client: {} as unknown,
  } as unknown as EngineStore;
  return { engine, calls };
}

const tfResult = () => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, 1], [2, 0, 2, 0]),
  coherence: real([2, 1], [0.9, 0.8]),
});
const fitResult = () => ({
  M: real([1, 6], [80, 0.02, 1, 0, 0, 0]),
  fn: real([1], [80]), zn: real([1], [0.02]),
  an: real([1, 1], [1]), pn: real([1, 1], [0]),
  message: 'fn=80.00 (Hz)',
  recon_freq_axis: real([2], [60, 110]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
  global_freq_axis: real([2], [0, 1]), global_tf_data: cplx([2, 1], [0.5, 0, 0.5, 0]),
});

function harness(responder: (op: string, payload: Record<string, unknown>) => unknown) {
  const { engine, calls } = fakeEngine(responder);
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const modal = createModalStore();
  const actions = createActions(engine, sel, settings, modal);
  return { actions, modal, sel, calls };
}

test('calcFit sends calc_fit with the TF slice + freq range and updates the modal store', async () => {
  const { actions, modal, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);

  const fit = calls.find((c) => c.op === 'calc_fit');
  expect(fit).toBeTruthy();
  expect(fit!.payload.freq_range).toEqual([60, 110]);
  expect(fit!.payload.measurement_type).toBe('acc');
  expect(fit!.payload.action).toBe('fit');
  expect(fit!.payload.n_modes).toBe(1);
  expect(fit!.payload.n_tf).toBe(1);          // one output column
  expect(fit!.payload.ch_in).toBe(0);
  expect(fit!.payload.n_channels).toBe(2);
  // First fit re-sends no prior matrix — the key is OMITTED (not sent as JS
  // null, which pyodide would surface as a falsy JsNull, not Python None).
  expect('M' in fit!.payload).toBe(false);
  // interleaved complex tf_data: [re,im,…] of the |H|=2 column → length 2·Nf.
  expect((fit!.payload.tf_data as Float64Array).length).toBe(4);

  const s = get(modal);
  expect(s.modes.map((m) => m.fn)).toEqual([80]);
  expect(s.local?.axis.length).toBe(2);
});

test('a second fit for the same set re-sends the accumulated matrix', async () => {
  const { actions, modal, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  await actions.calcFit('all', [190, 250], 'acc', 'fit', 1);
  const fits = calls.filter((c) => c.op === 'calc_fit');
  expect(fits).toHaveLength(2);
  expect('M' in fits[1].payload).toBe(true);   // accumulate against the stored model
  expect((fits[1].payload.M as { shape: number[] }).shape).toEqual([1, 6]);
  // Modal store still targets the same set → matrix carried, not reset.
  expect(get(modal).setId).not.toBeNull();
});

test('reject action forwards action=reject', async () => {
  const { actions, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'reject');
  const fit = calls.find((c) => c.op === 'calc_fit');
  expect(fit!.payload.action).toBe('reject');
});

test('calcFit no-ops (no engine call) before any TF exists', async () => {
  const { actions, calls } = harness(() => ({}));
  actions.loadDataset(makeDataset());
  await actions.calcFit('all', [60, 110]);
  expect(calls.some((c) => c.op === 'calc_fit')).toBe(false);
});

test('calcDamping returns decoded fn/Qn', async () => {
  const { actions, calls } = harness((op) => (op === 'calc_damping' ? { fn: real([2], [80, 220]), Qn: real([2], [25, 33]) } : {}));
  actions.loadDataset(makeDataset());
  const { fn, Qn } = await actions.calcDamping('all', 1, 512);
  expect(Array.from(fn)).toEqual([80, 220]);
  expect(Array.from(Qn)).toEqual([25, 33]);
  const call = calls.find((c) => c.op === 'calc_damping');
  expect(call!.payload.ch).toBe(1);
  expect(call!.payload.nperseg).toBe(512);
});

test('exportArrays returns raw per-set columns (real for time, complex for tf)', async () => {
  const { actions } = harness((op) => (op === 'calc_tf' ? tfResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');

  const time = actions.exportArrays('time');
  expect(time).toHaveLength(1);
  expect(time[0].columns).toHaveLength(2);                  // 2 channels
  expect(Array.from(time[0].columns[0] as Float64Array)).toEqual([1, 3, 5]);   // ch0 column

  const tf = actions.exportArrays('tf');
  expect(tf).toHaveLength(1);
  const col0 = (tf[0].columns as { re: Float64Array; im: Float64Array }[])[0];
  expect(Array.from(col0.re)).toEqual([2, 2]);             // |H| real parts
});

test('exportMat builds a payload of the computed kinds and returns the bytes', async () => {
  const bytes = new Uint8Array([1, 2, 3, 4]);
  const { actions, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'export_mat' ? { mat: bytes } : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');

  const out = await actions.exportMat();
  expect(out).toEqual(bytes);
  const call = calls.find((c) => c.op === 'export_mat');
  expect((call!.payload.time_sets as unknown[]).length).toBe(1);   // time seeded
  expect((call!.payload.tf_sets as unknown[]).length).toBe(1);     // tf computed
  expect((call!.payload.freq_sets as unknown[]).length).toBe(0);   // no FFT
});
