import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

/**
 * Modal-fit PSEUDO-SET + `.dvma` persistence (round-5 item 13).
 *
 * The modal model becomes a `role:'fit'` tray set whose global reconstruction
 * flows through the visible-line pipeline, and it persists as a `ModalData`
 * item inside the dataset. These tests exercise that lifecycle at the actions
 * layer with a fake engine (no pyodide): registration on fit, exclusion from
 * every measured-data consumer, the ModalData item, unregistration on clear,
 * the Global-toggle mapping, and load-restore of a saved model.
 */

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

/** A 1-set, 2-channel TimeData-only dataset (with a unique_id for id_link). */
function makeDataset(): DvmaDataset {
  const items: DvmaItem[] = [{
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: 'set_0', timestring: 't0', unique_id: 'UID1' },
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

const flush = () => new Promise((r) => setTimeout(r, 0));

test('a fit registers a role:fit pseudo-set with a recon tf slice, excluded from data consumers', async () => {
  const { actions, sel } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  expect(get(sel.setsView).filter((s) => s.role === 'fit')).toHaveLength(0);

  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);

  const fitSets = get(sel.setsView).filter((s) => s.role === 'fit');
  expect(fitSets).toHaveLength(1);
  const fit = fitSets[0];
  expect(fit.name).toContain('Modal fit');
  expect(fit.nChannels).toBe(2);                       // same geometry as the target
  // Colours mirror the target set (data set 0).
  expect(sel.lineColor(fit.id, 1)).toBe(sel.lineColor(0, 1));

  // The pseudo-set has a recon tf slice in `derived` (the global recon).
  const d = get(actions.derived);
  expect(d[fit.id]?.tf).toBeTruthy();
  expect(d[fit.id]!.tf!.chIn).toBe(0);
  expect(d[fit.id]!.tf!.nChannels).toBe(2);

  // EXCLUSIONS: not in dataSetsView, not in workingSets, not an export target.
  expect(get(sel.dataSetsView).some((s) => s.id === fit.id)).toBe(false);
  expect(actions.workingSets().some((w) => w.setId === fit.id)).toBe(false);
  expect(actions.exportArrays('tf')).toHaveLength(1);   // only the measured set
});

test('the fit adds a ModalData item to the dataset (M + id_link + measurement_type)', async () => {
  const { actions } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'vel', 'fit', 1);

  const ds = get(actions.dataset)!;
  const md = ds.items.filter((it) => it.kind === 'ModalData');
  expect(md).toHaveLength(1);
  const item = md[0];
  expect(item.arrays.M.shape).toEqual([1, 6]);
  expect(Array.from(item.arrays.M.data as Float64Array)).toEqual([80, 0.02, 1, 0, 0, 0]);
  expect(item.meta.id_link).toBe('UID1');              // links to the source TimeData
  expect(item.meta.channels).toBe(1);                  // (cols-2)/4
  expect(item.meta.measurement_type).toBe('vel');
  expect(item.meta.source_ch_in).toBe(0);
  expect(item.meta.source_n_channels).toBe(2);
  // metaRaw tags the timestamp so python decodes a datetime.
  expect((item.metaRaw!.timestamp as Record<string, unknown>).__datetime__).toBeTypeOf('string');
});

test('rejecting the model to empty removes the pseudo-set and the ModalData item', async () => {
  const empty = () => ({
    M: real([0, 0], []), fn: real([0], []), zn: real([0], []),
    an: real([0, 0], []), pn: real([0, 0], []), message: 'Mode fits deleted.',
    recon_freq_axis: real([0], []), recon_tf_data: cplx([0, 1], []),
    global_freq_axis: real([0], []), global_tf_data: cplx([0, 1], []),
  });
  const { actions, sel } = harness((op, p) =>
    op === 'calc_tf' ? tfResult()
      : op === 'calc_fit' ? (p.action === 'reject' ? empty() : fitResult()) : {});
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  expect(get(sel.setsView).some((s) => s.role === 'fit')).toBe(true);

  await actions.calcFit('all', [60, 110], 'acc', 'reject');
  expect(get(sel.setsView).some((s) => s.role === 'fit')).toBe(false);
  expect(get(actions.dataset)!.items.some((it) => it.kind === 'ModalData')).toBe(false);
});

test('setFitVisible / fitVisible drive the pseudo-set all-lines (the Global toggle mapping)', async () => {
  const { actions, sel } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  expect(get(actions.fitVisible)).toBe(true);            // shown on fit

  actions.setFitVisible(false);
  expect(get(actions.fitVisible)).toBe(false);
  const fit = get(sel.setsView).find((s) => s.role === 'fit')!;
  expect(get(sel.state)(fit.id, 1)).toBe('off');
  actions.setFitVisible(true);
  expect(get(actions.fitVisible)).toBe(true);
});

test('clearFit empties the model (pseudo-set + item gone); undo restores it', async () => {
  const { actions, modal, sel } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);

  actions.clearFit();
  expect(get(modal).modes).toEqual([]);
  expect(get(sel.setsView).some((s) => s.role === 'fit')).toBe(false);
  expect(get(actions.dataset)!.items.some((it) => it.kind === 'ModalData')).toBe(false);

  modal.undo();                                          // toast Undo path
  expect(get(modal).modes.map((m) => m.fn)).toEqual([80]);
  expect(get(sel.setsView).some((s) => s.role === 'fit')).toBe(true);
  expect(get(actions.dataset)!.items.some((it) => it.kind === 'ModalData')).toBe(true);
});

test('retargeting the fit to a different set rebuilds the pseudo-set (name follows)', async () => {
  // Two 2-channel TimeData sets; fit set 0, then fit set 1.
  const ds: DvmaDataset = {
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [
      { ...makeDataset().items[0], meta: { test_name: 'A', timestring: 't0', unique_id: 'A' } },
      {
        kind: 'TimeData',
        arrays: {
          time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
          time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 1, 1, 1, 1, 1]) },
        },
        meta: { test_name: 'B', timestring: 't1', unique_id: 'B' }, settings: { fs: 2 },
      },
    ],
  };
  const { actions, sel } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(ds);
  await actions.calcTf('all');
  const [idA, idB] = actions.workingSets().map((w) => w.setId);

  await actions.calcFit(idA, [60, 110], 'acc', 'fit', 1);
  let fit = get(sel.setsView).find((s) => s.role === 'fit')!;
  expect(fit.name).toContain('A');

  // Fit set B: the pseudo-set must rebuild to follow the new target.
  await actions.calcFit(idB, [60, 110], 'acc', 'fit', 1);
  const fitSets = get(sel.setsView).filter((s) => s.role === 'fit');
  expect(fitSets).toHaveLength(1);                     // exactly one, rebuilt
  expect(fitSets[0].name).toContain('B');
  // The ModalData item now links to set B's source.
  const md = get(actions.dataset)!.items.find((it) => it.kind === 'ModalData')!;
  expect(md.meta.id_link).toBe('B');
});

test('load-restore: a dataset carrying a ModalData item restores the modes + pseudo-set', async () => {
  // TimeData + a linked TfData + a linked ModalData (as a saved .dvma would carry).
  const ds: DvmaDataset = {
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [
      makeDataset().items[0],
      {
        kind: 'TfData',
        arrays: {
          freq_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 1]) },
          tf_data: { shape: [2, 1], isComplex: true, data: Float64Array.from([2, 0, 2, 0]) },
        },
        meta: { test_name: 'set_0', id_link: 'UID1' }, settings: null,
      },
      {
        kind: 'ModalData',
        arrays: { M: { shape: [1, 6], isComplex: false, data: Float64Array.from([80, 0.02, 1, 0, 0, 0]) } },
        meta: {
          id_link: 'UID1', channels: 1, measurement_type: 'acc',
          source_ch_in: 0, source_n_channels: 2, test_name: 'modal_set_0',
        },
        settings: null,
      },
    ],
  };
  const { actions, modal, sel } = harness((op) => (op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(ds);

  // The mode chip is seeded immediately from M (no engine needed).
  expect(get(modal).modes.map((m) => m.fn)).toEqual([80]);
  expect(get(modal).setId).not.toBeNull();
  expect(get(modal).mt).toBe('acc');

  // The recon fires async (target TF is present) → the pseudo-set appears.
  await flush();
  expect(get(sel.setsView).some((s) => s.role === 'fit')).toBe(true);
  const fit = get(sel.setsView).find((s) => s.role === 'fit')!;
  expect(get(actions.derived)[fit.id]?.tf).toBeTruthy();
});

test('load-restore is DEFERRED when the target TF is absent, then fires on Calc TF', async () => {
  // TimeData + ModalData but NO TfData in the file — the recon must wait.
  const ds: DvmaDataset = {
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [
      makeDataset().items[0],
      {
        kind: 'ModalData',
        arrays: { M: { shape: [1, 6], isComplex: false, data: Float64Array.from([80, 0.02, 1, 0, 0, 0]) } },
        meta: {
          id_link: 'UID1', channels: 1, measurement_type: 'acc',
          source_ch_in: 0, source_n_channels: 2, test_name: 'modal_set_0',
        },
        settings: null,
      },
    ],
  };
  const { actions, modal, sel } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(ds);
  await flush();
  // Modes seeded, but no recon lines yet (TF not computed).
  expect(get(modal).modes.map((m) => m.fn)).toEqual([80]);
  expect(get(sel.setsView).some((s) => s.role === 'fit')).toBe(false);

  // Computing the TF now triggers the deferred recon → the pseudo-set appears.
  await actions.calcTf('all');
  await flush();
  expect(get(sel.setsView).some((s) => s.role === 'fit')).toBe(true);
});
