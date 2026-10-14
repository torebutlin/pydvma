/**
 * Transfer-function calibration: a factor on the RATIO itself.
 *
 * 3C6's calibration step measures a free mass, whose accelerance is exactly
 * 1/m, and so calibrates the transfer function without ever knowing either
 * transducer's sensitivity. These tests pin how that factor lives in the
 * app: it replaces `cal[out]/cal[in]` for the TF and nothing else, it is
 * persisted both for the app (ui state) and for python (the saved TfData's
 * own `channel_cal_factors`, which is where python has always kept it), a
 * factor python set in a notebook is honoured on reload, and Best Match
 * writes into it rather than into the channel calibrations.
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
import type { NpyArray } from '../../src/lib/codec/npy';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });
const realArr = (shape: number[], data: number[]): NpyArray =>
  ({ shape, isComplex: false, data: Float64Array.from(data) });
const cplxArr = (shape: number[], interleaved: number[]): NpyArray =>
  ({ shape, isComplex: true, data: Float64Array.from(interleaved) });

function timeItem(name = 'set_0', uid?: string, extraMeta: Record<string, unknown> = {}): DvmaItem {
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: realArr([3], [0, 0.5, 1]),
      time_data: realArr([3, 2], [1, 2, 3, 4, 5, 6]),
    },
    meta: { test_name: name, timestring: 't0', ...(uid ? { unique_id: uid } : {}), ...extraMeta },
    settings: { fs: 2, device_driver: 'nidaq' },
  };
}

function tfItem(link: string | null, meta: Record<string, unknown> = {}): DvmaItem {
  return {
    kind: 'TfData',
    arrays: {
      freq_axis: realArr([2], [0, 1]),
      tf_data: cplxArr([2, 1], [2, 0, 2, 0]),
      tf_coherence: realArr([2, 1], [0.9, 0.8]),
    },
    meta: { test_name: 'tf', timestring: 't0', ...(link ? { id_link: link } : {}), ...meta },
    settings: { fs: 2, ch_in: 0 },
  };
}

const ds = (...items: DvmaItem[]): DvmaDataset => ({ formatVersion: 1, pydvmaVersion: '2.6.0', items });

const tfResult = () => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, 1], [2, 0, 2, 0]),
  coherence: real([2, 1], [0.9, 0.8]),
});

interface Recorded { op: string; payload: Record<string, unknown>; }

function harness(bestMatchFactors: number[][] = [[3]]) {
  const calls: Recorded[] = [];
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      calls.push({ op, payload });
      if (op === 'calc_tf') return Promise.resolve(tfResult());
      if (op === 'calc_best_match') {
        return Promise.resolve({ factors: bestMatchFactors.map((f) => real([f.length], f)) });
      }
      if (op === 'calc_fit') {
        return Promise.resolve({
          M: real([1, 6], [80, 0.02, 1, 0, 0, 0]),
          fn: real([1], [80]), zn: real([1], [0.02]), an: real([1, 1], [1]), pn: real([1, 1], [0]),
          message: 'fn=80', recon_freq_axis: real([2], [0, 1]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
          global_freq_axis: real([2], [0, 1]), global_tf_data: cplx([2, 1], [1, 0, 1, 0]),
        });
      }
      return Promise.resolve({});
    },
    client: {} as unknown,
  } as unknown as EngineStore;
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const toasts = createToasts();
  const actions = createActions(engine, sel, settings, createModalStore(), toasts);
  return { actions, toasts, calls };
}

const line = (factor: number, num = 'm/s', den = 'N') => ({ factor, num, den });

// ── get / set ─────────────────────────────────────────────────────────────── //

test('a set with no TF has no TF calibration to show', () => {
  const { actions } = harness();
  actions.loadDataset(ds(timeItem()));
  expect(actions.getTfCalibration(actions.workingSets()[0].setId)).toBeNull();
});

test('getTfCalibration reports the channel ratio until a TF factor is set', async () => {
  const { actions } = harness();
  actions.loadDataset(ds(timeItem()));
  await actions.calcTf('all');
  const id = actions.workingSets()[0].setId;
  actions.setCalFactors(id, [4, 10], ['N', 'm/s²']);

  const before = actions.getTfCalibration(id)!;
  expect(before.chIn).toBe(0);
  expect(before.orphan).toBe(false);
  expect(before.rows).toEqual([{ ch: 1, ratio: 2.5, override: null, num: 'm/s²', den: 'N' }]);

  actions.setTfCalibration(id, [null, line(7)]);
  const after = actions.getTfCalibration(id)!;
  expect(after.rows).toEqual([{ ch: 1, ratio: 2.5, override: line(7), num: 'm/s', den: 'N' }]);
});

test('a TF factor reaches the plot but leaves the channel calibration alone', async () => {
  const { actions } = harness();
  actions.loadDataset(ds(timeItem()));
  await actions.calcTf('all');
  const id = actions.workingSets()[0].setId;
  actions.setCalFactors(id, [4, 10], ['N', 'm/s²']);
  actions.setTfCalibration(id, [null, line(7)]);

  expect(get(actions.derived)[id].tfCal).toEqual({ chIn: 0, lines: [null, line(7)] });
  // The sensors are still what they were: only the ratio is calibrated.
  expect(actions.getCalibration(id).factors).toEqual([4, 10]);
  expect(get(actions.derived)[id].calFactors).toEqual([4, 10]);
});

test('clearing every line falls back to the channel ratio', async () => {
  const { actions } = harness();
  actions.loadDataset(ds(timeItem()));
  await actions.calcTf('all');
  const id = actions.workingSets()[0].setId;
  actions.setTfCalibration(id, [null, line(7)]);
  actions.setTfCalibration(id, [null, null]);
  expect(get(actions.derived)[id].tfCal).toBeUndefined();
  expect(actions.getTfCalibration(id)!.rows[0].override).toBeNull();
});

test('an orphan TF set calibrates its own stored factors, which python reads', () => {
  // A TF-only file: the item IS the TfData, so its channel_cal_factors are
  // the TF factors already — there is no channel calibration to override.
  const { actions } = harness();
  actions.loadDataset(ds(tfItem(null, { channel_cal_factors: [1], units: ['V/V'] })));
  const id = actions.workingSets()[0].setId;
  const info = actions.getTfCalibration(id)!;
  expect(info.orphan).toBe(true);
  expect(info.chIn).toBeNull();
  expect(info.rows).toEqual([{ ch: 0, ratio: 1, override: null, num: 'V', den: 'V' }]);

  actions.setTfCalibration(id, [line(0.5, 'm/s²', 'N')]);
  expect(actions.getCalibration(id).factors).toEqual([0.5]);
  expect(actions.getCalibration(id).units).toEqual(['(m/s²)/N']);
  expect(get(actions.derived)[id].tfCal).toBeUndefined();
  expect(actions.getTfCalibration(id)!.rows[0]).toEqual(
    { ch: 0, ratio: 0.5, override: null, num: 'm/s²', den: 'N' });
});

// ── fit ───────────────────────────────────────────────────────────────────── //

test('the modal fit reads the TF in its calibrated units', async () => {
  const { actions, calls } = harness();
  actions.loadDataset(ds(timeItem()));
  await actions.calcTf('all');
  const id = actions.workingSets()[0].setId;
  actions.setTfCalibration(id, [null, line(7)]);
  await actions.calcFit('all', [0, 1], 'vel', 'fit', 1);
  const fit = calls.find((c) => c.op === 'calc_fit')!;
  // |H| = 2 measured, × 7 calibrated.
  expect(Array.from(fit.payload.tf_data as Float64Array)).toEqual([14, 0, 14, 0]);
});

// ── persistence ───────────────────────────────────────────────────────────── //

test('the TF calibration rides the set ui state and comes back on load', async () => {
  const { actions } = harness();
  actions.loadDataset(ds(timeItem()));
  await actions.calcTf('all');
  const id = actions.workingSets()[0].setId;
  actions.setTfCalibration(id, [null, line(7)]);
  actions.stampUiState();
  const doc = get(actions.dataset)!;
  expect(doc.items[0].ui?.tf_cal).toEqual({ ch_in: 0, lines: [null, line(7)] });

  // A fresh app reading that document (no TfData in it yet — an autosave
  // before any Save) restores the calibration from the ui state.
  expect(doc.items.some((it) => it.kind === 'TfData')).toBe(false);
  const b = harness();
  b.actions.loadDataset({ ...doc, items: [doc.items[0]] });
  const id2 = b.actions.workingSets()[0].setId;
  expect(get(b.actions.derived)[id2].tfCal).toEqual({ chIn: 0, lines: [null, line(7)] });
});

test('Save writes the calibrated factor and unit into the TfData python reads', async () => {
  const { actions } = harness();
  actions.loadDataset(ds(timeItem()));
  await actions.calcTf('all');
  const id = actions.workingSets()[0].setId;
  actions.setTfCalibration(id, [null, line(7)]);
  actions.materializeDerived();
  const tf = get(actions.dataset)!.items.find((it) => it.kind === 'TfData')!;
  expect(tf.meta.channel_cal_factors).toEqual([7]);
  expect(tf.meta.units).toEqual(['(m/s)/N']);
});

test('without a TF factor the saved TfData carries the channel ratio, bracketed like python', async () => {
  const { actions } = harness();
  actions.loadDataset(ds(timeItem()));
  await actions.calcTf('all');
  const id = actions.workingSets()[0].setId;
  actions.setCalFactors(id, [4, 10], ['N', 'm/s²']);
  actions.materializeDerived();
  const tf = get(actions.dataset)!.items.find((it) => it.kind === 'TfData')!;
  expect(tf.meta.channel_cal_factors).toEqual([2.5]);
  // `analysis._tf_units_from_source` wraps compound units; so must we.
  expect(tf.meta.units).toEqual(['(m/s²)/N']);
});

test('a TfData that came off disk is kept in step with the TF calibration', () => {
  // A file saved earlier: its TF is adopted rather than recomputed, so
  // materialisation does not rewrite it — yet python must still see the
  // factor the user has since set, and the next load must not undo it.
  const { actions } = harness();
  actions.loadDataset(ds(timeItem('src', 'u1'), tfItem('u1', { channel_cal_factors: [1], units: ['V/V'] })));
  const id = actions.workingSets()[0].setId;
  actions.setTfCalibration(id, [null, line(7)]);
  actions.stampUiState();
  const tf = get(actions.dataset)!.items.find((it) => it.kind === 'TfData')!;
  expect(tf.meta.channel_cal_factors).toEqual([7]);
  expect(tf.meta.units).toEqual(['(m/s)/N']);
});

test('a factor python set on the saved TfData is honoured on load', () => {
  // The notebook flow: load the app's file, tf_data_list.set_calibration_factor(7,
  // units='(m/s)/N'), save — then reopen in the app for Best Match.
  const { actions } = harness();
  actions.loadDataset(ds(
    timeItem('src', 'u1'),
    tfItem('u1', { channel_cal_factors: [7], units: ['(m/s)/N'] }),
  ));
  const id = actions.workingSets()[0].setId;
  expect(get(actions.derived)[id].tfCal).toEqual({ chIn: 0, lines: [null, line(7)] });
});

test('a python factor set without units keeps the channel units', () => {
  const { actions } = harness();
  actions.loadDataset(ds(
    timeItem('src', 'u1', { channel_cal_factors: [1, 1], units: ['N', 'm/s'] }),
    tfItem('u1', { channel_cal_factors: [7] }),
  ));
  const id = actions.workingSets()[0].setId;
  expect(get(actions.derived)[id].tfCal).toEqual({ chIn: 0, lines: [null, line(7, 'm/s', 'N')] });
});

test('a stored TfData that merely carries the channel ratio is not a TF calibration', () => {
  const { actions } = harness();
  actions.loadDataset(ds(
    timeItem('src', 'u1', { channel_cal_factors: [4, 10] }),
    tfItem('u1', { channel_cal_factors: [2.5] }),
  ));
  expect(get(actions.derived)[actions.workingSets()[0].setId].tfCal).toBeUndefined();
});

test('the stored TfData outranks stale ui state', () => {
  // ui says 9, the TfData says 7: python changed it after the app last
  // saved (the app always writes both together), so the TfData is current.
  const { actions } = harness();
  const src = timeItem('src', 'u1');
  src.ui = { tf_cal: { ch_in: 0, lines: [null, line(9)] } };
  actions.loadDataset(ds(src, tfItem('u1', { channel_cal_factors: [7], units: ['(m/s)/N'] })));
  expect(get(actions.derived)[actions.workingSets()[0].setId].tfCal)
    .toEqual({ chIn: 0, lines: [null, line(7)] });

  // ...and a TfData back on the channel ratio means python cleared it.
  const b = harness();
  const src2 = timeItem('src', 'u1');
  src2.ui = { tf_cal: { ch_in: 0, lines: [null, line(9)] } };
  b.actions.loadDataset(ds(src2, tfItem('u1', { channel_cal_factors: [1] })));
  expect(get(b.actions.derived)[b.actions.workingSets()[0].setId].tfCal).toBeUndefined();
});

// ── Best Match ────────────────────────────────────────────────────────────── //

/** Two 2-channel sets with TFs: set A (reference) and set B. */
async function twoSets(factors: number[][] = [[1], [3]]) {
  const h = harness(factors);
  h.actions.loadDataset(ds(timeItem('A'), timeItem('B')));
  await h.actions.calcTf('all');
  const [a, b] = h.actions.workingSets().map((w) => w.setId);
  return { ...h, a, b };
}

test('Best Match writes the TF calibration, never the channel calibrations', async () => {
  const { actions, a, b } = await twoSets();
  actions.setCalFactors(b, [2, 5], ['N', 'm/s²']);
  await actions.calcBestMatch(a, 1, null, () => true);
  // B's sensors are untouched; its TF line now reads ×3 on A's (unit) level.
  expect(actions.getCalibration(b).factors).toEqual([2, 5]);
  expect(get(actions.derived)[b].tfCal?.lines[1]?.factor).toBeCloseTo(3, 12);
});

test('Best Match aims at the reference as DISPLAYED, TF calibration included', async () => {
  // The 3C6 comparison: the hammer set carries the free-mass TF factor, and
  // the noise set must land on the hammer's calibrated level, not its raw one.
  const { actions, a, b } = await twoSets();
  actions.setTfCalibration(a, [null, line(7)]);
  await actions.calcBestMatch(a, 1, null, () => true);
  expect(get(actions.derived)[b].tfCal).toEqual({ chIn: 0, lines: [null, line(21)] });
  // The reference keeps its own level (7 × its self-match factor 1).
  expect(get(actions.derived)[a].tfCal).toEqual({ chIn: 0, lines: [null, line(7)] });
});

test('Best Match aims at a channel-calibrated reference correctly', async () => {
  // Reference displays cal[out]/cal[in] = 10/4 = 2.5 — not its output
  // channel's 10, which the old channel-factor write used.
  const { actions, a, b } = await twoSets();
  actions.setCalFactors(a, [4, 10], ['N', 'm/s²']);
  await actions.calcBestMatch(a, 1, null, () => true);
  expect(get(actions.derived)[b].tfCal).toEqual(
    { chIn: 0, lines: [null, { factor: 7.5, num: 'm/s²', den: 'N' }] });
});

test('the Best Match prompt names the sets whose TF calibration is replaced', async () => {
  const { actions, a, b } = await twoSets();
  let info: { names: string[]; calibrated: string[] } | null = null;
  await actions.calcBestMatch(a, 1, null, (i) => { info = i; return false; });
  expect(info!.calibrated).toEqual([]);

  actions.setTfCalibration(b, [null, line(7)]);
  await actions.calcBestMatch(a, 1, null, (i) => { info = i; return false; });
  expect(info!.calibrated).toEqual(['B']);
  // A refusal changes nothing.
  expect(get(actions.derived)[b].tfCal).toEqual({ chIn: 0, lines: [null, line(7)] });
});

test('Best Match Undo restores every TF calibration it replaced', async () => {
  const { actions, toasts, a, b } = await twoSets();
  actions.setTfCalibration(a, [null, line(7)]);
  await actions.calcBestMatch(a, 1, null, () => true);
  get(toasts.toasts).at(-1)!.actions![0].run();
  expect(get(actions.derived)[a].tfCal).toEqual({ chIn: 0, lines: [null, line(7)] });
  expect(get(actions.derived)[b].tfCal).toBeUndefined();
});
