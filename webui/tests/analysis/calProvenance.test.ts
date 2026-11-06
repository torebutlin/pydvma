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
import { changedProvenance, provenanceFromSet, type ChannelCalibration } from '../../src/lib/model/calibration';
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

test('provenanceFromSet names the device by the server name, else the capture label', () => {
  expect(provenanceFromSet({ device_name: 'Audient iD44', capture_device_label: 'x' }, 0).device)
    .toBe('Audient iD44');
  expect(provenanceFromSet({ device_name: null, capture_device_label: 'cDAQ1Mod1' }, 0).device)
    .toBe('cDAQ1Mod1');
  expect(provenanceFromSet({ device_name: '', device_driver: 'nidaq' }, 0).device).toBeNull();
});

const prov = (actions: ReturnType<typeof harness>['actions'], ds: DvmaDataset) => {
  void actions;
  return ds.items.find((i) => i.kind === 'TimeData')!.meta.channel_calibration;
};

test('a factor change without provenance clears that channel only', () => {
  const { actions, ds } = harness();
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [20, 1], ['Pa', 'V'], { provenance: [entry(), entry({ note: 'b' })] });
  // (a) ch 0's factor moves (Best Match style) -> its entry is cleared;
  // (b) ch 1 unchanged -> kept.
  actions.setCalFactors(setId, [30, 1], ['Pa', 'V'], { warnFit: false });
  const cc = prov(actions, ds) as (ChannelCalibration | null)[];
  expect(cc[0]).toBeNull();
  expect(cc[1]!.note).toBe('b');
});

test('a unit change alone clears; an untouched channel keeps its entry', () => {
  const { actions, ds } = harness();
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [20, 1], ['Pa', 'V'], { provenance: [entry(), undefined] });
  actions.setCalFactors(setId, [20, 2], ['Pa', 'N']);
  const cc = prov(actions, ds) as (ChannelCalibration | null)[];
  expect(cc[0]!.note).toBe('spec sheet');
  expect(cc[1]).toBeNull();
});

test('no provenance anywhere: no channel_calibration key is created', () => {
  const { actions, ds } = harness();
  const setId = actions.workingSets()[0].setId;
  actions.setCalFactors(setId, [5, 5], ['Pa', 'Pa']);
  actions.setCalFactors(setId, [6, 5], ['Pa', 'Pa']);
  expect('channel_calibration' in ds.items[0].meta).toBe(false);
});

test('changedProvenance marks only changed channels, with note and settings', () => {
  const rows = [
    { ch: 0, label: 'a', sensitivity: 1, unit: 'V' },
    { ch: 1, label: 'b', sensitivity: 1, unit: 'V' },
  ];
  const settings = { input_gain_db: [30, 40], input_mode: ['mic', 'line'], input_pad: [false, true] };
  const d = '2026-11-06T10:00:00.000Z';
  const out = changedProvenance(rows, [{ sensitivity: 0.05, unit: 'Pa' }, { sensitivity: 1, unit: 'V' }], settings, 'n', d);
  expect(out[1]).toBeUndefined();
  expect(out[0]).toEqual({
    method: 'sensitivity', date: d, sensitivity: 0.05, unit: 'Pa', reference: null,
    gain_db: 30, input_mode: 'mic', pad: false, device: null, note: 'n', carried: false,
  });
  // unit-only change counts; no change at all -> all undefined
  expect(changedProvenance(rows, [{ sensitivity: 1, unit: 'V' }, { sensitivity: 1, unit: 'g' }], null, '', d)[1]).toBeDefined();
  expect(changedProvenance(rows, [{ sensitivity: 1, unit: 'V' }, { sensitivity: 1, unit: 'V' }], null, '', d))
    .toEqual([undefined, undefined]);
});

test('changedProvenance records a reference-tone calibration with its reference', () => {
  const rows = [{ ch: 0, label: 'a', sensitivity: 1, unit: 'Pa' }];
  const d = '2026-11-06T10:00:00.000Z';
  const reference = { level: 94, level_unit: 'dB SPL', freq: 1000 };
  const out = changedProvenance(rows, [{ sensitivity: 0.0335, unit: 'Pa', reference }], null, 'cal', d);
  expect(out[0]!.method).toBe('reference_tone');
  expect(out[0]!.reference).toEqual(reference);
  const plain = changedProvenance(rows, [{ sensitivity: 0.0335, unit: 'Pa' }], null, 'cal', d);
  expect(plain[0]!.method).toBe('sensitivity');
  expect(plain[0]!.reference).toBeNull();
});

test('a factor that differs only by rounding (1/(1/f)) keeps the provenance', () => {
  const { actions, ds } = harness();
  const setId = actions.workingSets()[0].setId;
  const f = 0.123;
  actions.setCalFactors(setId, [f, 1], ['Pa', 'V'], { provenance: [entry(), undefined] });
  // Whatever 1/(1/f) is, it must count as unchanged.
  const roundTrip = 1 / (1 / f);
  actions.setCalFactors(setId, [roundTrip, 1], ['Pa', 'V']);
  const cc = ds.items.find((i) => i.kind === 'TimeData')!.meta.channel_calibration as ChannelCalibration[];
  expect(cc[0]).not.toBeNull();
  expect(cc[0].note).toBe('spec sheet');
  // A genuine change (beyond 1e-12 relative) still clears it.
  actions.setCalFactors(setId, [f * (1 + 1e-9), 1], ['Pa', 'V'], { warnFit: false });
  expect((ds.items.find((i) => i.kind === 'TimeData')!.meta.channel_calibration as unknown[])[0]).toBeNull();
});
