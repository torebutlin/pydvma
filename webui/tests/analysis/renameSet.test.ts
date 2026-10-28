/**
 * Renaming a set in the tray (`actions.renameSet`). 4C6 lab workflow: each
 * grid-point measurement is renamed to its point label, the modal amplitudes
 * are later printed from the saved `.dvma` labelled by the TfData's
 * `test_name` (through `id_link`), and a session is restored or reloaded
 * between steps.
 *
 * The rename used to call `selection.rename`, which changed only the tray
 * card. The TimeData item kept its capture name (`set_<timestring>`), and
 * `loadDataset` names tray sets from that `test_name` — so restoring the
 * session (or Load Data of the saved file) put the capture names back. The
 * set's derived FreqData/TfData items carried the new name only because
 * `materializeDerived` reads the tray name at Save time, and only for results
 * computed this session: a TF that came off disk kept whatever name it had.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
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

/** A 2-channel capture named as the logger names one. */
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

/** A saved TF linked to `uid`, named as its source was when it was saved. */
function savedTf(uid: string, name: string): DvmaItem {
  return {
    kind: 'TfData',
    arrays: {
      freq_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 1]) },
      tf_data: { shape: [2, 1], isComplex: true, data: Float64Array.from([5, 0, 6, 0]) },
    },
    meta: { id_link: uid, test_name: name },
    settings: { fs: 2, channels: 2 },
  };
}

function setup() {
  const sel = createSelection();
  const actions = createActions(calcStubEngine(), sel);
  return { sel, actions };
}

const items = (actions: ReturnType<typeof createActions>) => get(actions.dataset)!.items;
const namesOf = (list: DvmaItem[]) => list.map((i) => `${i.kind}:${i.meta.test_name}`);
const trayNames = (sel: ReturnType<typeof createSelection>) => get(sel.sets).map((s) => s.name);

/** Save → reopen: the bytes a Save writes, loaded into a FRESH app. */
function reopen(ds: DvmaDataset) {
  const fresh = setup();
  fresh.actions.loadDataset(readDvma(writeDvma(ds)));
  return fresh;
}

test('a renamed set keeps its new name through Save and reload', async () => {
  const { actions } = setup();
  const ids = ['set_2026_a', 'set_2026_b', 'set_2026_c', 'set_2026_d']
    .map((n) => actions.addRecordedSet(capture(n)));
  for (const id of ids) await actions.calcTf(id);
  ['0', '2', '1', '3'].forEach((label, i) => actions.renameSet(ids[i], label));

  actions.materializeDerived();
  const after = reopen(actions.subsetDataset());

  expect(trayNames(after.sel)).toEqual(['0', '2', '1', '3']);
});

test('a rename reaches the set\'s TimeData item without waiting for a Save', () => {
  const { actions } = setup();
  const id = actions.addRecordedSet(capture('set_2026_a'));
  let emissions = 0;
  const unsub = actions.dataset.subscribe(() => { emissions += 1; });
  emissions = 0;

  actions.renameSet(id, '7');

  // In the document now, so autosave, the session journal and a restore see it.
  expect(namesOf(items(actions))).toEqual(['TimeData:7']);
  // ...and the document re-emits, which is what schedules the autosave.
  expect(emissions).toBe(1);
  unsub();
});

test('a file\'s tagged meta keeps its tags; the renamed key is written plain', () => {
  const { actions } = setup();
  const ds = readDvma(writeDvma({
    formatVersion: 2, pydvmaVersion: '2.8.1', items: [capture('set_2026_a', 'uid-a')],
  }));
  actions.loadDataset(ds);
  const [set] = actions.choosableSets();

  actions.renameSet(set.setId, '4');

  const time = items(actions)[0];
  expect(time.meta.test_name).toBe('4');
  expect(time.metaRaw?.test_name).toBe('4');
});

test('renaming a reopened set renames the TF it was saved with', () => {
  // The lab's restore: the TF came off disk, so a Save does not rewrite it
  // (nothing recomputed it this session) — the rename has to.
  const { actions } = setup();
  actions.loadDataset({
    formatVersion: 2, pydvmaVersion: '2.8.1',
    items: [capture('set_2026_a', 'uid-a'), savedTf('uid-a', 'set_2026_a')],
  });
  const [set] = actions.choosableSets();

  actions.renameSet(set.setId, '5');
  actions.materializeDerived();

  expect(namesOf(actions.subsetDataset().items)).toEqual(['TimeData:5', 'TfData:5']);
});

test('a set loaded twice: renaming one leaves its twin\'s items alone', () => {
  const { sel, actions } = setup();
  const file = (): DvmaDataset => ({
    formatVersion: 2, pydvmaVersion: '2.8.1',
    items: [capture('m', 'uid-m'), savedTf('uid-m', 'm')],
  });
  actions.loadDataset(file());
  actions.loadDataset(file(), { append: true });
  const [first] = actions.choosableSets();

  actions.renameSet(first.setId, 'renamed');

  expect(trayNames(sel)).toEqual(['renamed', 'm']);
  expect(namesOf(items(actions))).toEqual(
    ['TimeData:renamed', 'TfData:renamed', 'TimeData:m', 'TfData:m']);
});

test('a blank or unchanged name is ignored', () => {
  const { sel, actions } = setup();
  const id = actions.addRecordedSet(capture('a'));
  let emissions = 0;
  const unsub = actions.dataset.subscribe(() => { emissions += 1; });
  emissions = 0;

  actions.renameSet(id, '   ');
  actions.renameSet(id, 'a');

  expect(trayNames(sel)).toEqual(['a']);
  expect(emissions).toBe(0);
  unsub();
});

test('a channel relabel re-emits the document, so the autosave and journal see it', () => {
  const { actions } = setup();
  const id = actions.addRecordedSet(capture('a'));
  let emissions = 0;
  const unsub = actions.dataset.subscribe(() => { emissions += 1; });
  emissions = 0;

  actions.renameChannel(id, 1, 'accel');
  actions.renameChannel(id, 1, 'accel');           // unchanged: nothing to persist

  expect(emissions).toBe(1);
  actions.stampUiState();
  expect(items(actions)[0].ui?.channel_labels).toEqual({ 1: 'accel' });
  unsub();
});
