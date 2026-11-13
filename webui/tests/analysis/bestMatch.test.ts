/**
 * Best Match's reference and guard rails.
 *
 * Best Match rescales every TF line onto ONE reference line, picked by card
 * (`bestMatchRefs`), and stores each result as the rescaled line's
 * TRANSFER-FUNCTION calibration; the channel (transducer) calibrations are
 * never touched. These tests pin what the user is told and what is left
 * alone: the reference line is never written, the prompt appears only when a
 * rescaled line has a calibrated level to lose and names the reference, the
 * toast names the reference and leaves its ×1 out, and Undo restores what was
 * there. The TF-calibration semantics themselves (aiming at the reference as
 * displayed, orphans, persistence) are in `tfCalibration.test.ts`.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import { createToasts } from '../../src/lib/stores/toast';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { BestMatchInfo } from '../../src/lib/analysis/actions';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

/** One TimeData set named `name` with `nCh` channels (input ch_0). */
function timeItem(name: string, nCh = 2): DvmaItem {
  const data = Array.from({ length: 3 * nCh }, (_, i) => i + 1);
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, nCh], isComplex: false, data: Float64Array.from(data) },
    },
    meta: { test_name: name, timestring: 't0' },
    settings: { fs: 2 },
  };
}

const ds = (...items: DvmaItem[]): DvmaDataset => ({ formatVersion: 1, pydvmaVersion: '1.5.0', items });

/** A TF with one output column per non-input channel, like `calc_tf`. */
const tfResult = (nCh: number) => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, nCh - 1], new Array(4 * (nCh - 1)).fill(2)),
  coherence: real([2, nCh - 1], new Array(2 * (nCh - 1)).fill(0.9)),
});

/**
 * `factors` is what the fake `calc_best_match` returns: one array per set,
 * one entry per TF column, the reference's own entry 1 as the engine gives it.
 */
function harness(factors: number[][] = [[1], [3]]) {
  const ops: string[] = [];
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      ops.push(op);
      if (op === 'calc_tf') return Promise.resolve(tfResult(Number(payload.n_channels)));
      if (op === 'calc_best_match') {
        return Promise.resolve({ factors: factors.map((f) => real([f.length], f)) });
      }
      return Promise.resolve({});
    },
    client: {} as unknown,
  } as unknown as EngineStore;
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const toasts = createToasts();
  const actions = createActions(engine, sel, settings, createModalStore(), toasts);
  return { actions, toasts, ops };
}

/** Sets A (the reference) and B, both 2-channel, with their TFs computed. */
async function twoSets(factors?: number[][], nChA = 2) {
  const h = harness(factors);
  h.actions.loadDataset(ds(timeItem('A', nChA), timeItem('B')));
  await h.actions.calcTf('all');
  const [a, b] = h.actions.workingSets().map((w) => w.setId);
  return { ...h, a, b };
}

const lastToast = (toasts: ReturnType<typeof createToasts>) => get(toasts.toasts).at(-1);

/** Run the last toast's first action (the Undo button). */
function clickUndo(toasts: ReturnType<typeof createToasts>): void {
  const act = lastToast(toasts)?.actions?.[0];
  expect(act, 'expected an actionable toast').toBeTruthy();
  act!.run();
}

test('the reference line is never written, even when only its channels are calibrated', async () => {
  const { actions, a, b } = await twoSets();
  // A displays cal[1]/cal[0] = 0.4 from its channels and has no TF factor.
  actions.setCalFactors(a, [10, 4], ['m/s²', 'N']);
  await actions.calcBestMatch(a, 1, null, () => true);
  // A keeps following its channels: no TF factor was made out of its ratio.
  expect(get(actions.derived)[a].tfCal).toBeUndefined();
  expect(actions.getCalibration(a).factors).toEqual([10, 4]);
  // B lands on A's displayed level: 0.4 × 3, in A's unit.
  const line = actions.getTfCalibration(b)!.rows[0];
  expect(line.override?.factor).toBeCloseTo(1.2, 12);
  expect([line.num, line.den]).toEqual(['N', 'm/s²']);
});

test('nothing rescaled is calibrated → no prompt, and it runs', async () => {
  const { actions, a, b } = await twoSets();
  // The reference's own calibration is not at stake, so it does not count.
  actions.setTfCalibration(a, [null, { factor: 7, num: 'm/s', den: 'N' }]);
  let asked = false;
  await actions.calcBestMatch(a, 1, null, () => { asked = true; return false; });
  expect(asked).toBe(false);
  expect(get(actions.derived)[b].tfCal?.lines[1]?.factor).toBeCloseTo(21, 12);
});

test('a calibrated line to be rescaled → the prompt names the reference and what changes', async () => {
  const { actions, a, b } = await twoSets();
  actions.setTfCalibration(b, [null, { factor: 5, num: 'm/s', den: 'N' }]);
  let info: BestMatchInfo | null = null;
  await actions.calcBestMatch(a, 1, null, (i) => { info = i; return false; });
  expect(info).toEqual({ reference: 'A', names: ['B'], calibrated: ['B'] });
  // A refusal changes nothing.
  expect(get(actions.derived)[b].tfCal?.lines[1]?.factor).toBe(5);
});

test('a reference card with several TF lines rescales its other lines only', async () => {
  // A has ch_1/ch_0 and ch_2/ch_0; ch_1/ch_0 is the reference.
  const { actions, a, b } = await twoSets([[1, 2], [3]], 3);
  actions.setTfCalibration(a, [null, null, { factor: 5, num: 'm/s', den: 'N' }]);
  let info: BestMatchInfo | null = null;
  await actions.calcBestMatch(a, 1, null, (i) => { info = i; return true; });
  expect(info).toEqual({
    reference: 'A · ch_1/ch_0', names: ['A (other lines)', 'B'], calibrated: ['A (other lines)'],
  });
  const aCal = get(actions.derived)[a].tfCal!;
  expect(aCal.lines[1]).toBeNull();                 // the reference: untouched
  expect(aCal.lines[2]?.factor).toBeCloseTo(2, 12);
  expect(get(actions.derived)[b].tfCal?.lines[1]?.factor).toBeCloseTo(3, 12);
});

test('the toast names the reference and leaves out its own ×1', async () => {
  const { actions, toasts, a } = await twoSets();
  await actions.calcBestMatch(a, 1, null, () => true);
  expect(lastToast(toasts)?.message).toBe('Best match onto A: B ×3.00');
});

test('a reference card with several lines lists each rescaled line in the toast', async () => {
  const { actions, toasts, a } = await twoSets([[1, 2], [3]], 3);
  await actions.calcBestMatch(a, 1, null, () => true);
  expect(lastToast(toasts)?.message).toBe('Best match onto A · ch_1/ch_0: A (ch_2/ch_0 ×2.00), B ×3.00');
});

test('with only the reference to rescale it says so and does not run', async () => {
  const h = harness([[1]]);
  h.actions.loadDataset(ds(timeItem('A')));
  await h.actions.calcTf('all');
  const a = h.actions.workingSets()[0].setId;
  await h.actions.calcBestMatch(a, 1, null, () => true);
  expect(h.ops).not.toContain('calc_best_match');
  expect(lastToast(h.toasts)?.message).toMatch(/nothing to rescale onto A/);
  expect(get(h.actions.derived)[a].tfCal).toBeUndefined();
});

test('Undo restores what was there; channel calibrations are never touched', async () => {
  const { actions, toasts, a, b } = await twoSets();
  actions.setCalFactors(b, [2, 5], ['N', 'm/s²']);
  actions.setTfCalibration(b, [null, { factor: 9, num: 'm/s²', den: 'N' }]);
  await actions.calcBestMatch(a, 1, null, () => true);
  expect(get(actions.derived)[b].tfCal?.lines[1]?.factor).toBeCloseTo(3, 12);
  expect(actions.getCalibration(b).factors).toEqual([2, 5]);

  clickUndo(toasts);
  expect(get(actions.derived)[b].tfCal?.lines[1]?.factor).toBe(9);
  expect(actions.getCalibration(b).factors).toEqual([2, 5]);
});

test('omitting the confirm callback keeps the old headless behaviour', async () => {
  const { actions, a, b } = await twoSets();
  actions.setTfCalibration(b, [null, { factor: 9, num: 'm/s²', den: 'N' }]);
  await actions.calcBestMatch(a, 1, null);
  expect(get(actions.derived)[b].tfCal?.lines[1]?.factor).toBeCloseTo(3, 12);
});
