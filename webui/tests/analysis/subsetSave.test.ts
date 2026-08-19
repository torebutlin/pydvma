/**
 * Subset Save / Export (derived-data round, Task 5): the "Choose sets…"
 * picker's data side — `exportArrays` / `exportMat` filtered to a chosen
 * subset of measurements, `subsetDataset` building a FILTERED document for
 * `writeDvma`, and `choosableSets` feeding the picker's rows.
 *
 * The contract these pin: an ABSENT filter (and a filter naming every set)
 * means EVERYTHING, byte-for-byte what the app wrote before this landed —
 * including items it cannot attribute to any set. Only a PROPER subset
 * filters, and it never mutates the live document.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

interface Recorded { op: string; payload: Record<string, unknown>; }

function fakeEngine(
  responder: (op: string, payload: Record<string, unknown>) => unknown,
): { engine: EngineStore; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const engine = {
    status: writable('ready'),
    boot: async () => {},
    whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      calls.push({ op, payload });
      return Promise.resolve(responder(op, payload));
    },
    client: {} as unknown,
  } as unknown as EngineStore;
  return { engine, calls };
}

const fftResult = () => ({
  freq_axis: real([2], [0, 1]),
  freq_data: cplx([2, 2], [1, 0, 2, 0, 3, 0, 4, 0]),
});
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
  recon_freq_axis: real([2], [0, 1]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
  global_freq_axis: real([2], [0, 1]), global_tf_data: cplx([2, 1], [0.5, 0, 0.5, 0]),
});

/** An engine answering every calc this file drives. */
function calcEngine() {
  return fakeEngine((op) => {
    if (op === 'calc_fft') return fftResult();
    if (op === 'calc_tf' || op === 'calc_tf_averaged') return tfResult();
    if (op === 'calc_fit') return fitResult();
    if (op === 'export_mat') return { mat: new Uint8Array([1, 2, 3]) };
    return {};
  });
}

function harness() {
  const { engine, calls } = calcEngine();
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const modal = createModalStore();
  const actions = createActions(engine, sel, settings, modal);
  return { actions, sel, modal, calls };
}

/**
 * Two 2-channel measurements, each with a real `unique_id` (a python-written
 * file always carries one; the id_link lineage a subset filter walks is only
 * meaningful when it does). Distinct samples per set so a filtered export is
 * provably the RIGHT set's numbers.
 */
function twoSetDataset(): DvmaDataset {
  const mk = (s: number): DvmaItem => ({
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: {
        shape: [3, 2], isComplex: false,
        data: Float64Array.from([1, 2, 3, 4, 5, 6].map((v) => v + s * 100)),
      },
    },
    meta: { test_name: `set_${s}`, timestring: `t${s}`, unique_id: `uid-${s}` },
    settings: { fs: 2 },
  });
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items: [mk(0), mk(1)] };
}

/** An item nothing can attribute to a set: no id_link, no plottable slice. */
function unattributableSono(): DvmaItem {
  return {
    kind: 'SonoData',
    arrays: { sono_data: { shape: [2, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4]) } },
    meta: { test_name: 'orphan_sono' },      // no id_link ⇒ attaches to nothing
    settings: null,
  };
}

const kinds = (ds: DvmaDataset) => ds.items.map((i) => i.kind);
const names = (ds: DvmaDataset) => ds.items.map((i) => i.meta.test_name);

// ---------------------------------------------------------------- exports

test('exportArrays filtered to a subset returns only those sets; no filter is unchanged', async () => {
  const { actions, sel } = harness();
  actions.loadDataset(twoSetDataset());
  const [a, b] = get(sel.sets).map((s) => s.id);
  await actions.calcFft('all');

  // Full-export snapshot: what today's callers get, and what an all-sets
  // filter must reproduce exactly.
  const full = actions.exportArrays('time');
  expect(full.map((s) => s.setId)).toEqual([a, b]);
  expect(actions.exportArrays('time', [a, b])).toEqual(full);

  const justB = actions.exportArrays('time', [b]);
  expect(justB.map((s) => s.setId)).toEqual([b]);
  expect(Array.from(justB[0].columns[0] as Float64Array)).toEqual([101, 103, 105]);

  // The filter applies to every kind, not just time.
  expect(actions.exportArrays('freq', [a]).map((s) => s.setId)).toEqual([a]);
  // An empty pick exports nothing (it is not "no filter").
  expect(actions.exportArrays('time', [])).toEqual([]);
});

test('exportMat filtered to a subset sends only those sets to the engine', async () => {
  const { actions, sel, calls } = harness();
  actions.loadDataset(twoSetDataset());
  const [, b] = get(sel.sets).map((s) => s.id);
  await actions.calcFft('all');

  await actions.exportMat([b]);
  const payload = calls.find((c) => c.op === 'export_mat')!.payload;
  expect((payload.time_sets as unknown[]).length).toBe(1);
  expect((payload.freq_sets as unknown[]).length).toBe(1);
  expect(Array.from((payload.time_sets as { data: Float64Array }[])[0].data))
    .toEqual([101, 102, 103, 104, 105, 106]);

  await actions.exportMat();
  const all = calls.filter((c) => c.op === 'export_mat')[1].payload;
  expect((all.time_sets as unknown[]).length).toBe(2);
});

// ------------------------------------------------------- choosable rows

test('choosableSets lists one row per measurement with the kinds it carries', async () => {
  const { actions, sel } = harness();
  actions.loadDataset(twoSetDataset());
  const [a, b] = get(sel.sets).map((s) => s.id);
  await actions.calcFft(a);
  await actions.calcTf(b);
  await actions.calcFit(b, [0, 1], 'acc', 'fit', 1);

  const rows = actions.choosableSets();
  expect(rows.map((r) => r.setId)).toEqual([a, b]);
  expect(rows.map((r) => r.name)).toEqual(['set_0', 'set_1']);
  expect(rows[0].kinds).toEqual(['time', 'fft']);
  expect(rows[1].kinds).toEqual(['time', 'tf', 'fit']);
});

// ------------------------------------------------------ subset document

/** Load two sets, compute + materialise FFT/TF on both, fit set B's TF. */
async function twoSetsMaterialised() {
  const h = harness();
  h.actions.loadDataset(twoSetDataset());
  const [a, b] = get(h.sel.sets).map((s) => s.id);
  await h.actions.calcFft('all');
  await h.actions.calcTf('all');
  await h.actions.calcFit(b, [0, 1], 'acc', 'fit', 1);   // ModalData on set B
  h.actions.materializeDerived();
  return { ...h, a, b };
}

test('a subset document carries the chosen measurement, its derived items and its fit', async () => {
  const { actions, b } = await twoSetsMaterialised();
  const ds = get(actions.dataset)!;
  expect(kinds(ds)).toContain('ModalData');

  // Item order is the DOCUMENT's own (the fit was upserted before the FFT/TF
  // were materialised), not a re-grouping — a subset re-orders nothing.
  const sub = actions.subsetDataset([b]);
  expect(kinds(sub)).toEqual(['TimeData', 'ModalData', 'FreqData', 'TfData']);
  expect(names(sub)).toEqual(['set_1', 'modal_set_1', 'set_1', 'set_1']);
  // Every derived item points at the chosen set's lineage id, nothing else.
  for (const it of sub.items.filter((i) => i.kind !== 'ModalData').slice(1)) {
    expect(it.meta.id_link).toBe('uid-1');
  }
  expect(sub.formatVersion).toBe(ds.formatVersion);
  expect(sub.pydvmaVersion).toBe(ds.pydvmaVersion);

  // It is a real, loadable document: round-trip it and the set comes back.
  const back = readDvma(writeDvma(sub));
  expect(back.items.map((i) => i.kind))
    .toEqual(['TimeData', 'ModalData', 'FreqData', 'TfData']);
});

test('a subset that does not span the fit excludes the ModalData', async () => {
  const { actions, a } = await twoSetsMaterialised();
  const sub = actions.subsetDataset([a]);
  expect(kinds(sub)).toEqual(['TimeData', 'FreqData', 'TfData']);
  expect(names(sub).every((n) => n === 'set_0')).toBe(true);
  expect(kinds(sub)).not.toContain('ModalData');
});

test('every set ticked is the WHOLE document, unattributable items included', async () => {
  const { actions, a, b } = await twoSetsMaterialised();
  const ds = get(actions.dataset)!;
  ds.items.push(unattributableSono());

  const full = actions.subsetDataset([a, b]);
  expect(full.items).toEqual(ds.items);
  expect(actions.subsetDataset()).toEqual(ds);
  // …and identical on the wire to what today's unfiltered save writes.
  expect(readDvma(writeDvma(full))).toEqual(readDvma(writeDvma(ds)));

  // A PROPER subset drops the item nothing links to.
  expect(kinds(actions.subsetDataset([b]))).not.toContain('SonoData');
});

test('building a subset document never mutates the live one', async () => {
  const { actions, b } = await twoSetsMaterialised();
  const ds = get(actions.dataset)!;
  const itemsBefore = ds.items;
  const snapshot = [...ds.items];

  const sub = actions.subsetDataset([b]);
  expect(ds.items).toBe(itemsBefore);          // same array object
  expect(ds.items).toEqual(snapshot);          // same members, same order
  expect(sub.items).not.toBe(ds.items);        // the subset owns a NEW array
  expect(sub.items[0]).toBe(snapshot.find((i) => i.meta.test_name === 'set_1'));
});
