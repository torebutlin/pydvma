/**
 * Calibrate dialog reference-tone step: `actions.measureReferenceTone` sends the
 * set's time payload and the calibrator's rms to the engine op and decodes the
 * answer; the dialog converts dB SPL to rms and follows the row's unit.
 */
import { writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import { createToasts } from '../../src/lib/stores/toast';
import { P_REF } from '../../src/lib/analysis/acoustics';
import { channelRail, gainAtRangeEnd, referenceBasis, referenceDefaults, referenceRms } from '../../src/lib/model/calibration';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset } from '../../src/lib/model/dataset';

function makeDataset(settings: Record<string, unknown> = { fs: 2 }): DvmaDataset {
  return {
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [{
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
        time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
      },
      meta: { test_name: 'set_0', timestring: 't0', unique_id: 'UID0' },
      settings,
    }],
  };
}

function harness(settings?: Record<string, unknown>) {
  const calls: { op: string; payload: Record<string, unknown> }[] = [];
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      calls.push({ op, payload });
      return Promise.resolve({
        sensitivity: 0.0335, measured_rms: 0.0336, peak_freq: 1000,
        tone_to_total_db: -0.1, clipped: false, warnings: ['careful'],
      });
    },
    client: {} as unknown,
  } as unknown as EngineStore;
  const sel = createSelection();
  const actions = createActions(engine, sel, createAnalysisSettings(sel), createModalStore(), createToasts());
  actions.loadDataset(makeDataset(settings));
  return { actions, calls, setId: actions.workingSets()[0].setId };
}

test('measureReferenceTone resolves with the engine sensitivity and warnings', async () => {
  const { actions, calls, setId } = harness();
  const r = await actions.measureReferenceTone(setId, 1, 1.0, 1000);
  expect(r.sensitivity).toBe(0.0335);
  expect(r.measuredRms).toBe(0.0336);
  expect(r.peakFreq).toBe(1000);
  expect(r.clipped).toBe(false);
  expect(r.warnings).toEqual(['careful']);
  expect(calls[0].op).toBe('reference_tone_calibration');
  expect(calls[0].payload.channel).toBe(1);
  expect(calls[0].payload.n_channels).toBe(2);
  expect(calls[0].payload.time_data).toBeInstanceOf(Float64Array);
});

test('94 dB SPL sends ref_rms 1.0024 and the stored rail as vmax', async () => {
  const { actions, calls, setId } = harness({ fs: 2, VmaxSC: [2, 4] });
  await actions.measureReferenceTone(setId, 1, P_REF * 10 ** (94 / 20), 1000);
  expect(Math.abs((calls[0].payload.ref_rms as number) - 1.0024)).toBeLessThan(1e-4);
  expect(calls[0].payload.vmax).toBe(4);
});

test('no stored rail sends no vmax; nidaq uses VmaxNI', () => {
  expect(channelRail({ fs: 2 }, 0)).toBeUndefined();
  expect(channelRail({ device_driver: 'nidaq', VmaxNI: 5, VmaxSC: 1 }, 0)).toBe(5);
  expect(channelRail({ VmaxSC: { __array__: [2, 3] } }, 1)).toBe(3);
  expect(channelRail({ VmaxSC: [2, 3] }, 5)).toBe(1);
});

test('gainAtRangeEnd needs a stated gain at an end of a known range', () => {
  const ranges = { mic: [10, 65] as [number, number] };
  expect(gainAtRangeEnd({ gain_db: 10, input_mode: 'mic' }, ranges)).toBe(true);
  expect(gainAtRangeEnd({ gain_db: 65, input_mode: 'mic' }, ranges)).toBe(true);
  expect(gainAtRangeEnd({ gain_db: 30, input_mode: 'mic' }, ranges)).toBe(false);
  expect(gainAtRangeEnd({ gain_db: null, input_mode: 'mic' }, ranges)).toBe(false);
  expect(gainAtRangeEnd({ gain_db: 10, input_mode: 'line' }, ranges)).toBe(false);
  expect(gainAtRangeEnd({ gain_db: 10, input_mode: 'mic' }, null)).toBe(false);
});

test('the level unit and defaults follow the row unit', () => {
  expect(referenceDefaults('Pa')).toEqual({ levelUnit: 'dB SPL', level: 94, freq: 1000 });
  expect(referenceDefaults('m/s²')).toEqual({ levelUnit: 'm/s²', level: 10, freq: 159.2 });
  expect(referenceDefaults('N')).toEqual({ levelUnit: 'N', level: 1, freq: 1000 });
});

test('94 dB SPL is 1.0024 Pa rms; other units pass through', () => {
  expect(Math.abs(referenceRms(94, 'Pa', 1000) - 1.0024)).toBeLessThan(1e-4);
  expect(referenceRms(10, 'm/s²', 159.2)).toBe(10);
});

test('a non-positive or non-finite level or frequency gives NaN', () => {
  for (const [l, f] of [[0, 1000], [-1, 1000], [NaN, 1000], [94, 0], [94, -3], [94, Infinity]]) {
    expect(Number.isNaN(referenceRms(l, 'Pa', f))).toBe(true);
  }
});

test('referenceBasis: refuse a basis mismatch, warn FS across recordings, else ok', () => {
  expect(referenceBasis('V', 'V', false)).toBe('ok');
  expect(referenceBasis('V', 'V', true)).toBe('ok');
  expect(referenceBasis('FS', 'FS', true)).toBe('ok');
  expect(referenceBasis('FS', 'FS', false)).toBe('warn');
  expect(referenceBasis('V', 'FS', false)).toBe('refuse');
  expect(referenceBasis('FS', 'V', false)).toBe('refuse');
  expect(referenceBasis('FS', 'V', true)).toBe('refuse');
});
