/**
 * Round-11 P6 — `removeBlaRun` / `undoRemoveBlaRun`, the "replace previous
 * run" half of the Nonlin run semantics (Tore: "what happens if you run it,
 * change settings, and go again — will it add a huge new dataset or replace?
 * That all needs options and clarity").
 *
 * A set lives in FOUR places — the dataset items, the actions layer's
 * `working` list, the decoded `derived` map, and the selection tray — and the
 * whole point of these tests is that removal and restore touch all four
 * consistently. A removal that left a stale `working` entry would keep
 * exporting a set the user cannot see; one that left a derived slice would
 * keep drawing it.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createToasts } from '../../src/lib/stores/toast';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaItem } from '../../src/lib/model/dataset';

/** A recorded capture, as `recordingToItem` builds one. */
function recordedItem(name: string): DvmaItem {
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 1], isComplex: false, data: Float64Array.from([1, 2, 3]) },
    },
    meta: { test_name: name, timestring: 'tr' },
    settings: { fs: 2 },
  };
}

/** A `calc_bla`-shaped result payload (one excitation, one response). */
function blaResult() {
  return [{
    freq_axis: { shape: [2], data: Float64Array.from([0, 1]), complex: false },
    tf_data: { shape: [2, 1], data: Float64Array.from([1, 0, 1, 0]), complex: true },
    bla_sigma_nl: { shape: [2, 1], data: Float64Array.from([0.1, 0.2]), complex: false },
    bla_sigma_n: { shape: [2, 1], data: Float64Array.from([0.01, 0.02]), complex: false },
    bla: { M: 2, n_exc: 1 },
  }];
}

const stubEngine = () => ({
  status: writable('ready'),
  boot: async () => {},
  whenReady: async () => {},
  enqueue: async () => ({}),
  client: {} as unknown,
} as unknown as EngineStore);

/** Actions + tray + toasts, with one finished BLA run already landed. */
function withRun() {
  const sel = createSelection();
  const toasts = createToasts();
  const actions = createActions(stubEngine(), sel, undefined, undefined, toasts);
  const rawIds = [
    actions.addRecordedSet(recordedItem('bla r1e1'), { hidden: true }),
    actions.addRecordedSet(recordedItem('bla r2e1'), { hidden: true }),
  ];
  const resultIds = actions.addBlaSets(blaResult(), {
    names: ['bla BLA q1 (via ch0)'], channelLabels: ['resp ch 1'],
  });
  return { sel, toasts, actions, rawIds, resultIds, ids: [...rawIds, ...resultIds] };
}

const names = (sel: ReturnType<typeof createSelection>) => get(sel.sets).map((s) => s.name);

test('removeBlaRun clears the run from the dataset, the tray and the derived map', () => {
  const { sel, actions, ids } = withRun();
  expect(get(actions.dataset)!.items).toHaveLength(3);
  expect(names(sel)).toHaveLength(3);

  expect(actions.removeBlaRun(ids)).toBe(3);

  expect(get(actions.dataset)!.items).toEqual([]);
  expect(names(sel)).toEqual([]);
  for (const id of ids) expect(get(actions.derived)[id]).toBeUndefined();
});

test('removeBlaRun leaves every OTHER set untouched', () => {
  const { sel, actions, ids } = withRun();
  const keeper = actions.addRecordedSet(recordedItem('hammer test'));
  actions.removeBlaRun(ids);

  expect(names(sel)).toEqual(['hammer test']);
  expect(get(actions.dataset)!.items).toHaveLength(1);
  expect(get(actions.derived)[keeper]?.time).toBeDefined();
});

test('removeBlaRun raises ONE toast carrying the count and an Undo', () => {
  const { toasts, actions, ids } = withRun();
  actions.removeBlaRun(ids);
  const list = get(toasts.toasts);
  expect(list).toHaveLength(1);
  expect(list[0].message).toMatch(/3 sets removed/);
  expect(list[0].actions?.[0].label).toMatch(/Undo/);
  // Actionable toasts pin open until acted on — a replace the user did not
  // mean must not scroll away before they can take it back.
  expect(list[0].actions).toHaveLength(1);
});

test('Undo restores the dataset items, in their original order', () => {
  const { actions, ids } = withRun();
  const before = get(actions.dataset)!.items.map((i) => i.meta.test_name);
  // A set that stays put, so the restore has to slot AROUND it rather than
  // just appending: the removed items sat at indices 0..2, this one at 3.
  actions.addRecordedSet(recordedItem('hammer test'));

  actions.removeBlaRun(ids);
  expect(actions.undoRemoveBlaRun()).toBe(true);

  const after = get(actions.dataset)!.items.map((i) => i.meta.test_name);
  expect(after).toEqual([...before, 'hammer test']);
});

test('Undo marks the batch when the names it restores are taken again', () => {
  const { sel, actions, ids } = withRun();
  actions.removeBlaRun(ids);
  // The replacement run lands under the SAME names — which is the whole
  // reason the first one was removed.
  actions.addRecordedSet(recordedItem('bla r1e1'), { hidden: true });
  actions.addRecordedSet(recordedItem('bla r2e1'), { hidden: true });
  actions.addBlaSets(blaResult(), { names: ['bla BLA q1 (via ch0)'] });

  actions.undoRemoveBlaRun();
  // Restoring verbatim would give two indistinguishable groups of cards, so
  // the restored batch is marked — all of it, not the colliding half.
  expect(names(sel).slice(3)).toEqual([
    'bla r1e1 (restored)', 'bla r2e1 (restored)', 'bla BLA q1 (via ch0) (restored)',
  ]);
  // …and the mark reaches the ITEM, so it survives a save/reload rather than
  // being a tray-only fiction.
  const restored = get(actions.dataset)!.items.map((i) => i.meta.test_name);
  expect(restored).toContain('bla r1e1 (restored)');
});

test('Undo restores tray identity: names, channel labels and VISIBILITY', () => {
  const { sel, actions, ids, rawIds } = withRun();
  // Fade one line of the result set, so the restore is proved to carry a
  // MIXED state and not just "all on".
  sel.cycleLine(ids[2], 0);
  const stateBefore = get(sel.state)(ids[2], 0);
  expect(stateBefore).toBe('fade');

  actions.removeBlaRun(ids);
  expect(actions.undoRemoveBlaRun()).toBe(true);

  expect(names(sel)).toEqual(['bla r1e1', 'bla r2e1', 'bla BLA q1 (via ch0)']);
  const restored = get(sel.sets);
  // Ids are monotonic and never reused, so the restored sets are NEW ids —
  // the BLA store stops tracking them and they become ordinary tray cards.
  expect(restored.map((s) => s.id)).not.toEqual(expect.arrayContaining(ids));
  // The raw captures come back HIDDEN, which is how they landed…
  const view = get(sel.setsView);
  expect(view.slice(0, rawIds.length).every((s) => s.allOff)).toBe(true);
  // …and the faded result line comes back faded, not flattened to 'on'.
  expect(get(sel.state)(restored[2].id, 0)).toBe('fade');
  expect(get(sel.channelLabel)(restored[2].id, 0)).toBe('resp ch 1');
});

test('Undo restores the derived slices, so the restored lines draw again', () => {
  const { sel, actions, ids } = withRun();
  actions.removeBlaRun(ids);
  actions.undoRemoveBlaRun();

  const restored = get(sel.sets);
  const d = get(actions.derived);
  expect(d[restored[0].id]?.time).toBeDefined();
  const tf = d[restored[2].id]?.tf;
  expect(tf).toBeDefined();
  // Including the σ pair — the whole reason the Nonlin stage exists.
  expect(tf!.sigmaNl).toBeDefined();
  expect(tf!.sigmaN).toBeDefined();
});

test('Undo is ONE level: a second call is a no-op, and a second remove re-arms it', () => {
  const { sel, actions, ids } = withRun();
  actions.removeBlaRun(ids);
  expect(actions.undoRemoveBlaRun()).toBe(true);
  expect(actions.undoRemoveBlaRun()).toBe(false);
  expect(names(sel)).toHaveLength(3);

  actions.removeBlaRun(get(sel.sets).map((s) => s.id));
  expect(names(sel)).toEqual([]);
  expect(actions.undoRemoveBlaRun()).toBe(true);
  expect(names(sel)).toHaveLength(3);
});

test('removeBlaRun with nothing to remove changes nothing and stays silent', () => {
  const { sel, toasts, actions } = withRun();
  expect(actions.removeBlaRun([])).toBe(0);
  expect(actions.removeBlaRun([9999])).toBe(0);        // stale id from a cleared session
  expect(get(toasts.toasts)).toEqual([]);
  expect(names(sel)).toHaveLength(3);
  // A no-op must not arm the undo slot either, or the next Undo would restore
  // the WRONG batch.
  expect(actions.undoRemoveBlaRun()).toBe(false);
});
