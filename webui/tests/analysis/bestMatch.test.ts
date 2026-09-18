/**
 * Best Match's calibration guard rails (F1).
 *
 * Best Match stores relative scaling factors in `channel_cal_factors` — the
 * same slot a transducer calibration lives in — and leaves the engineering
 * `units` alone, so running it over a calibrated set replaces a physical
 * calibration with a relative one while the axis keeps saying `m/s²`. These
 * tests pin the two things that make that survivable: it ASKS first (and the
 * prompt is told which sets actually have a calibration to lose), and the
 * result toast carries an Undo that restores the previous factors AND units.
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

test('confirming applies the factors; Undo restores the previous cal AND units', async () => {
  const { actions, toasts } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [10, 4], ['m/s²', 'N']);

  await actions.calcBestMatch(setId, 1, null, () => true);

  // refCal (ch1 = 4) × the engine's factor (3) lands on the output channel.
  const after = actions.getCalibration(setId);
  expect(after.factors[1]).toBeCloseTo(12, 12);
  // Units are deliberately left alone by Best Match — the reason it needs a
  // prompt at all. Pinned so the behaviour cannot drift unnoticed.
  expect(after.units).toEqual(['m/s²', 'N']);

  clickUndo(toasts);
  expect(actions.getCalibration(setId).factors).toEqual([10, 4]);
  expect(actions.getCalibration(setId).units).toEqual(['m/s²', 'N']);
});

test('omitting the confirm callback keeps the old headless behaviour', async () => {
  const { actions } = harness();
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  const setId = actions.workingSets()[0].setId;

  await actions.calcBestMatch(setId, 1, null);
  expect(actions.getCalibration(setId).factors[1]).toBeCloseTo(3, 12);
});
