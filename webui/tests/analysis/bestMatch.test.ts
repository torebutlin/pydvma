/**
 * Best Match's calibration guard rails (F1).
 *
 * Best Match stores its relative scaling as each set's TRANSFER-FUNCTION
 * calibration, replacing whatever TF factor the set displayed before; the
 * channel (transducer) calibrations are never touched. These tests pin the
 * guard rails: it ASKS first (and the prompt is told which sets actually
 * display a calibrated TF), and the result toast carries an Undo that
 * restores what was there. The TF-calibration semantics themselves (aiming at
 * the reference as displayed, orphans, persistence) are in
 * `tfCalibration.test.ts`.
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

/** One 2-channel TimeData set — enough for a TF with a single output column. */
function makeDataset(): DvmaDataset {
  const items: DvmaItem[] = [{
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: 'set_0', timestring: 't0' },
    settings: { fs: 2 },
  }];
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
}

const tfResult = () => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, 1], [2, 0, 2, 0]),
  coherence: real([2, 1], [0.9, 0.8]),
});
/** `calc_best_match` returns one factor array per set, one entry per column. */
const bestMatchResult = () => ({ factors: [real([1], [3])] });

function harness() {
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string) => Promise.resolve(
      op === 'calc_tf' ? tfResult() : op === 'calc_best_match' ? bestMatchResult() : {},
    ),
    client: {} as unknown,
  } as unknown as EngineStore;
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const toasts = createToasts();
  const actions = createActions(engine, sel, settings, createModalStore(), toasts);
  return { actions, toasts };
}

/** Run the last toast's first action (the Undo button). */
function clickUndo(toasts: ReturnType<typeof createToasts>): void {
  const live = get(toasts.toasts);
  const act = live.at(-1)?.actions?.[0];
  expect(act, 'expected an actionable toast').toBeTruthy();
  act!.run();
}

test('best match asks before it runs, and a refusal changes nothing', async () => {
  const { actions } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [10, 4], ['m/s²', 'N']);

  let asked: BestMatchInfo | null = null;
  await actions.calcBestMatch(setId, 1, null, (info) => { asked = info; return false; });

  expect(asked).toBeTruthy();
  // Unchanged: a cancelled Best Match must not touch the calibration.
  expect(actions.getCalibration(setId).factors).toEqual([10, 4]);
  expect(actions.getCalibration(setId).units).toEqual(['m/s²', 'N']);
});

test('the prompt names the sets whose calibration is at risk', async () => {
  const { actions } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;

  // Uncalibrated: nothing to lose, so `calibrated` is empty.
  let info: BestMatchInfo | null = null;
  await actions.calcBestMatch(setId, 1, null, (i) => { info = i; return false; });
  expect(info!.names).toHaveLength(1);
  expect(info!.calibrated).toEqual([]);

  // Calibrated: the set is named as at risk.
  actions.setCalFactors(setId, [10, 4], ['m/s²', 'N']);
  await actions.calcBestMatch(setId, 1, null, (i) => { info = i; return false; });
  expect(info!.calibrated).toEqual(info!.names);
});

test('confirming applies the factors as TF calibration; Undo restores what was there', async () => {
  const { actions, toasts } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [10, 4], ['m/s²', 'N']);

  await actions.calcBestMatch(setId, 1, null, () => true);

  // The reference line displayed cal[1]/cal[0] = 0.4; × the engine's 3.
  const line = actions.getTfCalibration(setId)!.rows[0];
  expect(line.override?.factor).toBeCloseTo(1.2, 12);
  expect([line.num, line.den]).toEqual(['N', 'm/s²']);
  // The transducer calibration is not Best Match's to change.
  expect(actions.getCalibration(setId).factors).toEqual([10, 4]);
  expect(actions.getCalibration(setId).units).toEqual(['m/s²', 'N']);

  clickUndo(toasts);
  expect(actions.getTfCalibration(setId)!.rows[0].override).toBeNull();
  expect(actions.getCalibration(setId).factors).toEqual([10, 4]);
});

test('omitting the confirm callback keeps the old headless behaviour', async () => {
  const { actions } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;

  await actions.calcBestMatch(setId, 1, null);
  expect(actions.getTfCalibration(setId)!.rows[0].override?.factor).toBeCloseTo(3, 12);
});
