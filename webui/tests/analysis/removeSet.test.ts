/**
 * The tray's × on a data set (`actions.removeSet`). 3C6 lab report
 * (2026-10-22): "log, save, delete, log again — the next save has the old
 * data too." The × used to call `selection.removeSet`, which took the CARD
 * out of the tray and nothing else: the set's item stayed in the document,
 * in `working` and in the derived map, so every later Save (and the session
 * journal, and a notebook's `session.data`) still carried every set ever
 * deleted — and Save even re-materialised the deleted set's FFT/TF. The lab's
 * coupled-beam prediction then read the wrong transfer function out of each
 * "one beam per file" save.
 *
 * A set lives in FOUR places (dataset items, `working`, `derived`, the tray);
 * removal has to clear all four, and the set's derived items with it.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createToasts } from '../../src/lib/stores/toast';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

/** An engine answering the two calcs materialisation reads. */
const calcStubEngine = () => ({
  status: writable('ready'),
  boot: async () => {},
  whenReady: async () => {},
  enqueue: async (op: string) => (op === 'calc_fft'
    ? {
      freq_axis: { shape: [2], data: Float64Array.from([0, 1]), complex: false },
      freq_data: { shape: [2, 2], data: Float64Array.from([1, 0, 2, 0, 3, 0, 4, 0]), complex: true },
    }
    : {
      freq_axis: { shape: [2], data: Float64Array.from([0, 1]), complex: false },
      tf_data: { shape: [2, 1], data: Float64Array.from([5, 0, 6, 0]), complex: true },
      coherence: { shape: [2, 1], data: Float64Array.from([0.9, 0.8]), complex: false },
    }),
  client: {} as unknown,
} as unknown as EngineStore);

/** A 2-channel capture (a TF needs an output channel besides the input). */
function capture(name: string, uid?: string): DvmaItem {
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: name, timestring: 'tr', ...(uid ? { unique_id: uid } : {}) },
    settings: { fs: 2, channels: 2 },
  };
}

/** A python-written spectrum linked to `uid`. */
function spectrum(uid: string, value: number): DvmaItem {
  return {
    kind: 'FreqData',
    arrays: {
      freq_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 1]) },
      freq_data: { shape: [2, 2], isComplex: true, data: Float64Array.from([value, 0, value, 0, value, 0, value, 0]) },
    },
    meta: { id_link: uid, test_name: 'fft' },
    settings: { fs: 2, channels: 2 },
  };
}

function setup() {
  const sel = createSelection();
  const toasts = createToasts();
  const actions = createActions(calcStubEngine(), sel, undefined, undefined, toasts);
  return { sel, toasts, actions };
}

/** Log a capture, compute its FFT and TF, and Save (materialise). */
async function logAndSave(actions: ReturnType<typeof createActions>, name: string): Promise<number> {
  const id = actions.addRecordedSet(capture(name));
  await actions.calcFft(id);
  await actions.calcTf(id);
  actions.materializeDerived();
  return id;
}

const items = (actions: ReturnType<typeof createActions>) => get(actions.dataset)!.items;
const namesOf = (list: DvmaItem[]) => list.map((i) => `${i.kind}:${i.meta.test_name}`);

test('log, save, delete, log again: the next save holds only the new set', async () => {
  const { sel, actions } = setup();
  const first = await logAndSave(actions, 'lower beam');
  expect(namesOf(items(actions))).toEqual(
    ['TimeData:lower beam', 'FreqData:lower beam', 'TfData:lower beam']);

  actions.removeSet(first);
  expect(items(actions)).toEqual([]);
  expect(get(sel.sets)).toEqual([]);
  expect(get(actions.derived)[first]).toBeUndefined();
  expect(actions.choosableSets()).toEqual([]);

  await logAndSave(actions, 'upper beam');
  // The whole-document save (no "Choose sets…" pick) is the live document.
  expect(namesOf(actions.subsetDataset().items)).toEqual(
    ['TimeData:upper beam', 'FreqData:upper beam', 'TfData:upper beam']);
});

test('removeSet leaves the other sets, and their saved results, alone', async () => {
  const { sel, actions } = setup();
  const a = await logAndSave(actions, 'a');
  const b = await logAndSave(actions, 'b');

  actions.removeSet(a);

  expect(get(sel.sets).map((s) => s.name)).toEqual(['b']);
  expect(namesOf(items(actions))).toEqual(['TimeData:b', 'FreqData:b', 'TfData:b']);
  expect(get(actions.derived)[b]?.tf).toBeDefined();
  // A re-save replaces b's items in place rather than adding to them.
  actions.materializeDerived();
  expect(items(actions)).toHaveLength(3);
});

test('a loaded file\'s EXTRA linked items go with their set', () => {
  const { actions } = setup();
  // Python can write several spectra of one measurement; the app adopts the
  // last for replace-by-lineage, but every one of them is that set's data.
  const ds: DvmaDataset = {
    formatVersion: 2, pydvmaVersion: '2.7.0',
    items: [capture('m', 'uid-m'), spectrum('uid-m', 1), spectrum('uid-m', 2), capture('n', 'uid-n')],
  };
  actions.loadDataset(ds);
  const [m] = actions.choosableSets();

  actions.removeSet(m.setId);

  expect(namesOf(items(actions))).toEqual(['TimeData:n']);
});

test('a set loaded twice keeps the linked items its twin still shows', () => {
  const { actions } = setup();
  const file = (): DvmaDataset => ({
    formatVersion: 2, pydvmaVersion: '2.7.0', items: [capture('m', 'uid-m'), spectrum('uid-m', 1)],
  });
  actions.loadDataset(file());
  actions.loadDataset(file(), { append: true });
  const [first] = actions.choosableSets();

  actions.removeSet(first.setId);

  // The twin's TimeData and the spectrum it shares the lineage of survive.
  expect(items(actions).map((i) => i.kind)).toEqual(['TimeData', 'FreqData']);
});

test('removeSet raises no toast and leaves the Nonlin undo slot alone', async () => {
  const { toasts, actions } = setup();
  const id = await logAndSave(actions, 'x');
  actions.removeSet(id);
  expect(get(toasts.toasts)).toEqual([]);
  expect(actions.undoRemoveBlaRun()).toBe(false);
});

test('removeSet on an unknown id changes nothing', async () => {
  const { actions } = setup();
  await logAndSave(actions, 'x');
  actions.removeSet(9999);
  expect(items(actions)).toHaveLength(3);
});

test('a Nonlin replace\'s Undo brings the swept linked items back too', () => {
  const { actions } = setup();
  const ds: DvmaDataset = {
    formatVersion: 2, pydvmaVersion: '2.7.0',
    items: [capture('m', 'uid-m'), spectrum('uid-m', 1), spectrum('uid-m', 2)],
  };
  actions.loadDataset(ds);
  const before = items(actions).slice();
  const [m] = actions.choosableSets();

  actions.removeBlaRun([m.setId], { label: 'set' });
  expect(items(actions)).toEqual([]);
  expect(actions.undoRemoveBlaRun()).toBe(true);

  expect(items(actions)).toEqual(before);
});
