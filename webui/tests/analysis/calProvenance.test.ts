/**
 * Calibration provenance: how each channel's engineering-unit calibration was
 * obtained is saved with the data (`channel_calibration`) and survives a
 * `.dvma` round trip. Unedited channels stay null.
 */
import { writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import { createToasts } from '../../src/lib/stores/toast';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
import { provenanceFromSet, type ChannelCalibration } from '../../src/lib/model/calibration';
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

function harness(ds: DvmaDataset = makeDataset()) {
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: () => Promise.resolve({}), client: {} as unknown,
  } as unknown as EngineStore;
  const sel = createSelection();
  const actions = createActions(engine, sel, createAnalysisSettings(sel), createModalStore(), createToasts());
  actions.loadDataset(ds);
  return { actions, ds };
}

const entry = (over: Partial<ChannelCalibration> = {}): ChannelCalibration => ({
  method: 'sensitivity', date: new Date().toISOString(), sensitivity: 0.05, unit: 'Pa',
  reference: null, gain_db: 30, input_mode: 'mic', pad: false, device: null,
  note: 'spec sheet', carried: false, ...over,
});

test('provenance is saved for the channel given, others stay null, and round-trips', () => {
  const { actions, ds } = harness();
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [20, 1], ['Pa', 'V'], { provenance: [entry(), undefined] });

  expect(ds).not.toBeNull();
  const td = ds!.items.find((i) => i.kind === 'TimeData')!;
  const cc = td.meta.channel_calibration as (ChannelCalibration | null)[];
  expect(cc).toHaveLength(2);
  expect(cc[0]!.method).toBe('sensitivity');
  expect(cc[0]!.unit).toBe('Pa');
  expect(cc[0]!.note).toBe('spec sheet');
  expect(Number.isNaN(Date.parse(cc[0]!.date))).toBe(false);
  expect(cc[1]).toBeNull();

  const back = readDvma(writeDvma(ds!));
  const td2 = back.items.find((i) => i.kind === 'TimeData')!;
  expect(td2.meta.channel_calibration).toEqual(cc);
});

test('a later write keeps the entries of channels it does not mention', () => {
  const { actions, ds } = harness();
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [20, 1], ['Pa', 'V'], { provenance: [entry(), undefined] });
  actions.setCalFactors(setId, [20, 5], ['Pa', 'N'], { provenance: [undefined, entry({ unit: 'N', note: 'b' })] });
  const td = ds.items.find((i) => i.kind === 'TimeData')!;
  const cc = td.meta.channel_calibration as ChannelCalibration[];
  expect(cc[0].note).toBe('spec sheet');
  expect(cc[1].note).toBe('b');
});

test('without provenance nothing is invented', () => {
  const { actions, ds } = harness();
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [2, 2], ['V', 'V']);
  const td = ds.items.find((i) => i.kind === 'TimeData')!;
  expect('channel_calibration' in td.meta).toBe(false);
});

test('provenanceFromSet reads scalars, lists and python array tags', () => {
  const s = {
    input_gain_db: { __array__: [10, 20] }, input_mode: ['mic', null], input_pad: [true, false],
    device_name: 'Audient iD44',
  };
  expect(provenanceFromSet(s, 1)).toEqual({ gain_db: 20, input_mode: null, pad: false, device: 'Audient iD44' });
  expect(provenanceFromSet({ input_gain_db: 12 }, 3))
    .toEqual({ gain_db: 12, input_mode: null, pad: null, device: null });
  expect(provenanceFromSet(s, 5).gain_db).toBeNull();
  expect(provenanceFromSet(null, 0)).toEqual({ gain_db: null, input_mode: null, pad: null, device: null });
});
