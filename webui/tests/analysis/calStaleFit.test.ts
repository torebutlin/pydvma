/**
 * Q4: a calibration that moves under an existing modal fit gets a warning,
 * not a silent re-fit.
 *
 * The fit reads the TF through the same `cal[out]/cal[in]` ratio the plot uses
 * (`fitCalRatios`), so its stored modal CONSTANTS are in whatever engineering
 * units were in force when it ran. Re-calibrate afterwards and they are quietly
 * in the old ones — while fn, zeta and Q, being scale-invariant, are still
 * right. An automatic re-fit would move a model the user may have curated
 * (rejected modes, refinements) without being asked, so this warns instead.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import { createToasts } from '../../src/lib/stores/toast';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

function makeDataset(nSets = 1): DvmaDataset {
  const items: DvmaItem[] = Array.from({ length: nSets }, (_, k) => ({
    kind: 'TimeData' as const,
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: `set_${k}`, timestring: `t${k}`, unique_id: `UID${k}` },
    settings: { fs: 2 },
  }));
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
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
/** `calc_best_match` returns one factor array per set, one entry per column. */
const bestMatchResult = () => ({ factors: [real([1], [3])] });

function harness() {
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string) => Promise.resolve(
      op === 'calc_tf' ? tfResult()
        : op === 'calc_fit' ? fitResult()
          : op === 'calc_best_match' ? bestMatchResult()
            : {},
    ),
    client: {} as unknown,
  } as unknown as EngineStore;
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const toasts = createToasts();
  const actions = createActions(engine, sel, settings, createModalStore(), toasts);
  return { actions, toasts };
}

/** Messages of every live toast. */
const messages = (toasts: ReturnType<typeof createToasts>) =>
  get(toasts.toasts).map((t) => t.message);
const staleWarnings = (toasts: ReturnType<typeof createToasts>) =>
  messages(toasts).filter((m) => m.includes('modal fit'));

test('re-calibrating a fitted set warns that the mode constants are stale', async () => {
  const { actions, toasts } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;

  // Before any fit there is nothing to go stale.
  actions.setCalFactors(setId, [2, 2], ['V', 'V']);
  expect(staleWarnings(toasts)).toHaveLength(0);

  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  actions.setCalFactors(setId, [10, 4], ['m/s²', 'N']);

  const warn = staleWarnings(toasts);
  expect(warn).toHaveLength(1);
  // It says what IS still right, so the fit is not thrown away needlessly.
  expect(warn[0]).toContain('set_0');
  expect(warn[0]).toMatch(/frequencies, damping and Q are unaffected/);
});

test('a no-op re-apply of the same factors does not warn', async () => {
  const { actions, toasts } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [10, 4], ['m/s²', 'N']);
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);

  // Same numbers again — the dialog's Apply with nothing edited.
  actions.setCalFactors(setId, [10, 4], ['m/s²', 'N']);
  expect(staleWarnings(toasts)).toHaveLength(0);
});

test('a calibration on an UNFITTED set is silent', async () => {
  const { actions, toasts } = harness();
  actions.loadDataset(makeDataset(2));
  await actions.calcTf('all');
  const [a, b] = actions.workingSets().map((w) => w.setId);
  await actions.calcFit(a, [60, 110], 'acc', 'fit', 1);

  actions.setCalFactors(b, [7, 7], ['N', 'N']);
  expect(staleWarnings(toasts)).toHaveLength(0);

  actions.setCalFactors(a, [7, 7], ['N', 'N']);
  expect(staleWarnings(toasts)).toHaveLength(1);
});

test('best match raises ONE warning for the whole run, and its Undo raises none', async () => {
  const { actions, toasts } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);

  await actions.calcBestMatch(setId, 1, null, () => true);
  expect(staleWarnings(toasts)).toHaveLength(1);

  // Undo puts the fit back in the units it was made in — nothing to warn about.
  const undo = get(toasts.toasts).find((t) => t.actions?.length)?.actions?.[0];
  expect(undo, 'expected the best-match toast to carry an Undo').toBeTruthy();
  undo!.run();
  expect(staleWarnings(toasts)).toHaveLength(1);
});
