/**
 * A Fit on a model that already has modes adds to it, over the model's own
 * lines, whatever is visible. 4C6 lab (2026-10-27): fit 120 Hz over four
 * grid points with "All sets (shared poles)", hide one set to compare the fit
 * with its measurement, then Fit 1 at 310 Hz — the fit started a new model on
 * the three visible lines and the 120 Hz mode was gone, with no warning and
 * no Undo ('fit' is not a destructive action, so nothing was stashed).
 *
 * The visible lines still choose the lines for a FIRST fit (round-7h), and a
 * fit that does start a new model over one with modes (another set picked in
 * the Fit card) keeps the old model in the undo slot and says so.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import type { ToastOptions, Toasts } from '../../src/lib/stores/toast';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

/** One 2-channel grid-point capture (its TF has one column). */
function point(name: string): DvmaItem {
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: name, timestring: 't', unique_id: `uid-${name}` },
    settings: { fs: 2 },
  };
}

const grid = (n: number): DvmaDataset => ({
  formatVersion: 2, pydvmaVersion: '2.8.1',
  items: Array.from({ length: n }, (_, i) => point(String(i))),
});

const tfResult = () => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, 1], [2, 0, 2, 0]),
  coherence: real([2, 1], [0.9, 0.8]),
});

/**
 * A shared-pole `calc_fit` answer for `nSets` one-column sets. Like the real
 * engine it is stateless: a fit sent the model's matrix `M` comes back with
 * that model's modes plus the new one (here 120 Hz, then 310 Hz).
 */
function fitAnswer(payload: Record<string, unknown>) {
  const sets = (payload.sets as unknown[] | undefined)?.length ?? 1;
  const prior = (payload.M as { shape: number[] } | undefined)?.shape[0] ?? 0;
  const fns = [120, 310].slice(0, prior + 1);
  const row = (fn: number) => [fn, 0.01, ...Array(sets).fill(1), ...Array(3 * sets).fill(0)];
  const slice = () => ({
    recon_freq_axis: real([2], [0, 1]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
    global_freq_axis: real([2], [0, 1]), global_tf_data: cplx([2, 1], [1, 0, 1, 0]), n_cols: 1,
  });
  return {
    M: real([fns.length, 2 + 4 * sets], fns.flatMap(row)),
    fn: real([fns.length], fns), zn: real([fns.length], fns.map(() => 0.01)),
    an: real([fns.length, sets], Array(fns.length * sets).fill(1)),
    pn: real([fns.length, sets], Array(fns.length * sets).fill(0)),
    message: '',
    ...slice(),
    slices: Array.from({ length: sets }, slice),
  };
}

interface Recorded { op: string; payload: Record<string, unknown>; }

function harness(nSets: number) {
  const calls: Recorded[] = [];
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      calls.push({ op, payload });
      return Promise.resolve(op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitAnswer(payload) : {});
    },
    client: {} as unknown,
  } as unknown as EngineStore;
  const sel = createSelection();
  const modal = createModalStore();
  const pushed: ({ message: string } & ToastOptions)[] = [];
  const toasts = {
    push: (message: string, opts: ToastOptions = {}) => pushed.push({ message, ...opts }),
    dismiss: () => {},
  } as unknown as Toasts;
  const actions = createActions(engine, sel, createAnalysisSettings(sel), modal, toasts);
  actions.loadDataset(grid(nSets));
  const ids = actions.workingSets().map((w) => w.setId);
  const fits = () => calls.filter((c) => c.op === 'calc_fit');
  const hide = (id: number) => { sel.cycleSet(id); sel.cycleSet(id); };   // on → fade → off
  return { actions, modal, sel, ids, fits, hide, pushed };
}

const fns = (modal: ReturnType<typeof createModalStore>) => get(modal).modes.map((m) => m.fn);

test('the 4C6 sequence: a set hidden to compare the fit keeps the 120 Hz mode', async () => {
  const { actions, modal, ids, fits, hide } = harness(4);
  await actions.calcTf('all');
  await actions.calcFit('shared', [100, 140], 'acc', 'fit', 1);
  expect(fns(modal)).toEqual([120]);

  hide(ids[3]);
  await actions.calcFit('shared', [290, 330], 'acc', 'fit', 1);

  // Fitted over the model's four lines, the hidden one included, with its matrix.
  const second = fits()[1].payload;
  expect((second.sets as unknown[]).length).toBe(4);
  expect('M' in second).toBe(true);
  expect(fns(modal)).toEqual([120, 310]);
  expect(get(modal).targets.map((t) => t.setId)).toEqual(ids);
});

test('a single set: a channel hidden after the first fit stays in the model', async () => {
  const { actions, modal, sel, ids, fits } = harness(1);
  await actions.calcTf('all');
  await actions.calcFit(ids[0], [100, 140], 'acc', 'fit', 1);
  sel.cycleLine(ids[0], 1); sel.cycleLine(ids[0], 1);      // the TF's line → off

  await actions.calcFit(ids[0], [290, 330], 'acc', 'fit', 1);

  expect(fits()).toHaveLength(2);                          // not "nothing to fit"
  expect('M' in fits()[1].payload).toBe(true);
  expect(fns(modal)).toEqual([120, 310]);
});

test('the visible lines still choose the lines for a first fit, and after ×', async () => {
  const { actions, modal, ids, fits, hide } = harness(3);
  await actions.calcTf('all');
  hide(ids[2]);
  await actions.calcFit('shared', [100, 140], 'acc', 'fit', 1);
  expect(get(modal).targets.map((t) => t.setId)).toEqual([ids[0], ids[1]]);

  actions.clearFit();                                      // × on the Modal fit card
  hide(ids[1]);
  await actions.calcFit('shared', [100, 140], 'acc', 'fit', 1);
  expect(get(modal).targets.map((t) => t.setId)).toEqual([ids[0]]);
  expect('M' in fits()[1].payload).toBe(false);
});

test('the Fit card says when a Fit adds to the model, and over which lines', async () => {
  const { actions, ids, hide } = harness(4);
  await actions.calcTf('all');
  hide(ids[3]);
  expect(actions.fitLineSummary('shared')).toEqual({ fitted: 3, total: 4, model: false });

  await actions.calcFit('shared', [100, 140], 'acc', 'fit', 1);   // a 3-line model
  hide(ids[2]);
  expect(actions.fitLineSummary('shared')).toEqual({ fitted: 3, total: 4, model: true });
});

test('a fit that replaces a model with modes offers Undo', async () => {
  const { actions, modal, ids, pushed } = harness(2);
  await actions.calcTf('all');
  await actions.calcFit(ids[0], [100, 140], 'acc', 'fit', 1);
  await actions.calcFit(ids[0], [290, 330], 'acc', 'fit', 1);
  expect(fns(modal)).toEqual([120, 310]);

  await actions.calcFit(ids[1], [100, 140], 'acc', 'fit', 1);   // another set: a new model

  expect(get(modal).targets.map((t) => t.setId)).toEqual([ids[1]]);
  const toast = pushed.find((t) => /replaced the 2 modes/.test(t.message));
  expect(toast?.actions?.map((a) => a.label)).toEqual(['Undo']);
  toast!.actions![0].run();
  expect(fns(modal)).toEqual([120, 310]);
  expect(get(modal).targets.map((t) => t.setId)).toEqual([ids[0]]);
});

test('adding to the model raises no replace notice', async () => {
  const { actions, ids, pushed, hide } = harness(2);
  await actions.calcTf('all');
  await actions.calcFit('shared', [100, 140], 'acc', 'fit', 1);
  hide(ids[1]);
  await actions.calcFit('shared', [290, 330], 'acc', 'fit', 1);
  expect(pushed.some((t) => /replaced/.test(t.message))).toBe(false);
});
