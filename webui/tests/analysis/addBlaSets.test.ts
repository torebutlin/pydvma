/**
 * Integration test: addBlaSets lands `calc_bla` results as first-class TF
 * sets — a TfData item per excitation in the dataset (σ arrays + the `bla`
 * run-spec meta included, so `.dvma` round-trips them), a tray set with the
 * orphan-TF geometry (`chIn = null`, columns ARE the lines), and a derived
 * `tf` slice carrying the σ pair for the overlay.
 */
import { get } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createEngineStore } from '../../src/lib/stores/engine';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
import type { EngineClient } from '../../src/lib/worker/client';

const stubClient: EngineClient = {
  init: async () => {},
  call: async () => ({}) as any,
};

/** Two excitations x three frequencies x two response channels. */
function blaResults() {
  const mk = (q: number) => ({
    freq_axis: { shape: [3], data: Float64Array.from([100, 200, 300]), complex: false },
    // (3, 2) complex, interleaved re/im.
    tf_data: {
      shape: [3, 2],
      data: Float64Array.from([1, 0, 2, 0, 3, 0, 4, 0, 5, 0, 6, 0].map((v) => v + q)),
      complex: true,
    },
    coherence: null,
    bla_sigma_nl: { shape: [3, 2], data: Float64Array.from([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]), complex: false },
    bla_sigma_n: { shape: [3, 2], data: Float64Array.from([0.01, 0.02, 0.03, 0.04, 0.05, 0.06]), complex: false },
    bla: {
      multisine: { n_samples: 480, k1: 10, k2: 50, p_periods: 2, t_periods: 1, seed: 7, amp_rms: 0.05, n_exc: 2, M: 2 },
      x_mode: 'measured', x_channels: [0, 1], resp_channels: [2, 3], fs: 48000,
      excited_bins: [10, 11, 12], q,
    },
  });
  return [mk(0), mk(1)];
}

function makeActions() {
  const sel = createSelection();
  const eng = createEngineStore(stubClient);
  return { sel, actions: createActions(eng, sel) };
}

test('addBlaSets lands one tray set per excitation with the orphan-TF geometry', () => {
  const { sel, actions } = makeActions();
  const ids = actions.addBlaSets(blaResults(), {
    names: ['BLA q1 (via ch0)', 'BLA q2 (via ch1)'],
    channelLabels: ['ch_2', 'ch_3'],
    timestring: '2026-08-10 12:00:00',
  });

  expect(ids).toHaveLength(2);
  const sets = get(sel.setsView);
  expect(sets.map((s) => s.name)).toEqual(['BLA q1 (via ch0)', 'BLA q2 (via ch1)']);
  // Each response channel is its own line (n_resp = 2), and BLA sets are
  // ordinary DATA sets — selectable, exportable, fittable (not 'fit' pseudo-sets).
  expect(sets.every((s) => s.nChannels === 2 && s.role === 'data')).toBe(true);
  expect(sel.getLabelsForSet(ids[0])).toEqual({ 0: 'ch_2', 1: 'ch_3' });

  const d = get(actions.derived)[ids[0]];
  expect(d.tf!.chIn).toBeNull();                 // nothing was dropped: columns are the lines
  expect(d.tf!.nChannels).toBe(2);
  expect(d.tf!.axis).toEqual(Float64Array.from([100, 200, 300]));
  expect(Array.from(d.tf!.data.re)).toEqual([1, 2, 3, 4, 5, 6]);
  // σ pair rides the same slice as the curve it annotates.
  expect(Array.from(d.tf!.sigmaNl!.re)).toEqual([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]);
  expect(Array.from(d.tf!.sigmaN!.re)).toEqual([0.01, 0.02, 0.03, 0.04, 0.05, 0.06]);
  expect(d.tf!.coherence).toBeUndefined();       // BLA sets carry σ instead

  // The sets are targetable like any other (workingSets is the cards' list).
  const ws = actions.workingSets();
  expect(ws.map((w) => w.setId)).toEqual(ids);
  expect(ws.every((w) => w.hasTime === false)).toBe(true);
});

test('the dataset carries a TfData item per excitation that .dvma round-trips', () => {
  const { actions } = makeActions();
  actions.addBlaSets(blaResults(), { names: ['q1', 'q2'], timestring: '2026-08-10 12:00:00' });

  const ds = get(actions.dataset)!;
  expect(ds.items.map((i) => i.kind)).toEqual(['TfData', 'TfData']);
  const item = ds.items[0];
  expect(Object.keys(item.arrays).sort())
    .toEqual(['bla_sigma_n', 'bla_sigma_nl', 'freq_axis', 'tf_data']);
  expect(item.arrays.tf_data.isComplex).toBe(true);
  expect(item.arrays.tf_data.shape).toEqual([3, 2]);
  expect((item.meta.bla as { q: number }).q).toBe(0);

  // Save + reload: the σ arrays and the run spec survive, so a saved BLA can
  // be re-read (here and in python — container.py registers both fields).
  const back = readDvma(writeDvma(ds));
  const tf = back.items[1];
  expect(tf.kind).toBe('TfData');
  expect(tf.arrays.bla_sigma_nl.shape).toEqual([3, 2]);
  expect(Array.from(tf.arrays.bla_sigma_n.data as Float64Array))
    .toEqual([0.01, 0.02, 0.03, 0.04, 0.05, 0.06]);
  expect((tf.meta.bla as { multisine: { seed: number } }).multisine.seed).toBe(7);
  expect((tf.meta.bla as { q: number }).q).toBe(1);
  expect(tf.meta.test_name).toBe('q2');
});

test('a saved-then-reloaded BLA item restores its σ overlay arrays into the derived tf slice (Task 9 reload gap)', () => {
  // A BLA set IS a plain orphan TfData (`id_link: null`, no source TimeData
  // in the file) — on reopen it goes through `sliceForLoadedItem`'s ORPHAN
  // branch. Before the Task 9 fix that branch restored axis/data/coherence/
  // chIn/nChannels but not sigmaNl/sigmaN, so a saved-then-reopened BLA set
  // silently lost its σ overlay. Simulate a real reopen: write → read → load
  // into a FRESH actions/selection pair (a new session opening the file).
  const { actions } = makeActions();
  actions.addBlaSets(blaResults(), { names: ['q1', 'q2'], timestring: '2026-08-10 12:00:00' });
  const reloaded = readDvma(writeDvma(get(actions.dataset)!));

  const { sel: sel2, actions: actions2 } = makeActions();
  actions2.loadDataset(reloaded);

  const sets = get(sel2.setsView);
  expect(sets).toHaveLength(2);
  const d0 = get(actions2.derived)[sets[0].id];
  expect(d0.tf).toBeDefined();
  expect(d0.tf!.chIn).toBeNull();                 // orphan geometry preserved too
  expect(Array.from(d0.tf!.sigmaNl!.re)).toEqual([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]);
  expect(Array.from(d0.tf!.sigmaN!.re)).toEqual([0.01, 0.02, 0.03, 0.04, 0.05, 0.06]);
});

test('addBlaSets appends to an existing dataset and keeps earlier sets', () => {
  const { sel, actions } = makeActions();
  actions.loadDataset({
    formatVersion: 2,
    pydvmaVersion: 'test',
    items: [{
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [4], data: Float64Array.from([0, 1, 2, 3]), isComplex: false },
        time_data: { shape: [4, 1], data: Float64Array.from([0, 1, 0, -1]), isComplex: false },
      },
      meta: { test_name: 'raw' },
      settings: { fs: 4, channels: 1 },
    }],
  });
  expect(get(sel.setsView)).toHaveLength(1);

  const ids = actions.addBlaSets(blaResults().slice(0, 1), { names: ['bla'] });
  expect(get(sel.setsView).map((s) => s.name)).toEqual(['raw', 'bla']);
  expect(get(actions.dataset)!.items).toHaveLength(2);
  expect(get(actions.derived)[ids[0]].tf).toBeDefined();
});
