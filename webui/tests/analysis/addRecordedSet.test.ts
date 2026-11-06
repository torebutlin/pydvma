/**
 * Integration test: addRecordedSet adds a recorded TimeData item into an
 * existing (or empty) dataset, populates the selection tray, and seeds
 * the derived store with time arrays for immediate plotting.
 */
import { get } from 'svelte/store';
import { afterEach, expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createEngineStore } from '../../src/lib/stores/engine';
import { recordingToItem } from '../../src/lib/stores/acquire';
import type { Recording } from '../../src/lib/audio/source';
import type { EngineClient } from '../../src/lib/worker/client';
import { captureDeviceLabel, carriedCal } from '../../src/lib/stores/carriedCal';
import type { BridgeCaps } from '../../src/lib/audio/provider';
import { createToasts } from '../../src/lib/stores/toast';
import type { ChannelCalibration } from '../../src/lib/model/calibration';

/** Stub engine client — no real Worker, no pyodide. Sufficient for
 *  addRecordedSet (which never calls the engine). */
const stubClient: EngineClient = {
  init: async () => {},
  call: async () => ({}) as any,
};

function fakeRecording(nCh = 2, nSamples = 200, fs = 44100): Recording {
  const timeAxis = new Float64Array(nSamples);
  const data = new Float64Array(nSamples * nCh);
  for (let i = 0; i < nSamples; i++) {
    timeAxis[i] = i / fs;
    for (let c = 0; c < nCh; c++) {
      data[i * nCh + c] = Math.sin(2 * Math.PI * 440 * i / fs + c);
    }
  }
  return { data, timeAxis, fs, nChannels: nCh, nSamples };
}

test('addRecordedSet creates a dataset when none exists', () => {
  const sel = createSelection();
  const eng = createEngineStore(stubClient);
  const actions = createActions(eng, sel);

  expect(get(actions.dataset)).toBeNull();

  const rec = fakeRecording();
  const item = recordingToItem(rec, 'capture_1');
  const setId = actions.addRecordedSet(item);

  // Dataset is now populated.
  const ds = get(actions.dataset);
  expect(ds).not.toBeNull();
  expect(ds!.items).toHaveLength(1);
  expect(ds!.items[0].kind).toBe('TimeData');

  // Selection tray has one set.
  const sets = get(sel.setsView);
  expect(sets).toHaveLength(1);
  expect(sets[0].id).toBe(setId);
  expect(sets[0].nChannels).toBe(2);

  // Derived store is seeded with time arrays.
  const derived = get(actions.derived);
  expect(derived[setId]).toBeDefined();
  expect(derived[setId].time).toBeDefined();
  expect(derived[setId].time!.axis.length).toBe(200);
});

test('addRecordedSet appends to an existing dataset', () => {
  const sel = createSelection();
  const eng = createEngineStore(stubClient);
  const actions = createActions(eng, sel);

  // Add first set.
  const item1 = recordingToItem(fakeRecording(1, 100), 'first');
  actions.addRecordedSet(item1);

  // Add second set.
  const item2 = recordingToItem(fakeRecording(2, 300), 'second');
  const setId2 = actions.addRecordedSet(item2);

  const ds = get(actions.dataset);
  expect(ds!.items).toHaveLength(2);

  const sets = get(sel.setsView);
  expect(sets).toHaveLength(2);

  // Both have time data in derived.
  const derived = get(actions.derived);
  expect(Object.keys(derived)).toHaveLength(2);
  expect(derived[setId2].time!.axis.length).toBe(300);
});

test('addRecordedSet works alongside loadDataset sets', () => {
  const sel = createSelection();
  const eng = createEngineStore(stubClient);
  const actions = createActions(eng, sel);

  // Simulate loading a dataset first.
  const preItem = recordingToItem(fakeRecording(1, 50), 'loaded');
  actions.loadDataset({
    formatVersion: 2,
    pydvmaVersion: 'test',
    items: [preItem],
  });

  expect(get(sel.setsView)).toHaveLength(1);

  // Now add a recorded set on top.
  const item = recordingToItem(fakeRecording(2, 100), 'recorded');
  const newId = actions.addRecordedSet(item);

  expect(get(sel.setsView)).toHaveLength(2);
  const ds = get(actions.dataset);
  expect(ds!.items).toHaveLength(2);
  expect(get(actions.derived)[newId].time).toBeDefined();
});

// ---- round-13: a bridged capture keeps its FULL acquisition settings ----

test('recordingToItem merges the container settings under the capture-derived keys', () => {
  const rec = fakeRecording(1, 100);
  const item = recordingToItem(rec, 'bridged', {
    deviceDriver: 'nidaq',
    settings: {
      fs: 12500,               // the REQUESTED rate — the capture's own wins
      channels: 1, stored_time: 60, device_driver: 'nidaq',
      device_index: 0, NI_mode: 'DAQmx_Val_PseudoDiff', VmaxNI: 5,
      iepe_excit_current_A: { __array__: { dtype: '<f8', shape: [1], data: [0.002] } },
      output_fs: 12500, pretrig_samples: null,
    },
  });
  expect(item.settings).toMatchObject({
    device_index: 0, NI_mode: 'DAQmx_Val_PseudoDiff', VmaxNI: 5,
    output_fs: 12500, pretrig_samples: null,
    iepe_excit_current_A: { __array__: { dtype: '<f8', shape: [1], data: [0.002] } },
  });
  // The four keys the app has always written describe the samples kept.
  expect(item.settings).toMatchObject({
    fs: rec.fs, channels: rec.nChannels,
    stored_time: rec.nSamples / rec.fs, device_driver: 'nidaq',
  });
});

test('recordingToItem without bridge meta still writes the four classic keys', () => {
  const rec = fakeRecording(1, 100);
  const item = recordingToItem(rec, 'web');
  expect(item.settings).toEqual({
    fs: rec.fs, channels: rec.nChannels,
    stored_time: rec.nSamples / rec.fs, device_driver: 'web_audio',
  });
});

test('a capture, or a loaded set with no recorded settings, gets the window / TF averaging set from Python', async () => {
  const { createAnalysisSettings } = await import('../../src/lib/stores/analysisSettings');
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const actions = createActions(createEngineStore(stubClient), sel, settings);
  settings.setCaptureDefaults({ window: 'none', tfAveraging: 'across' });

  const captured = actions.addRecordedSet(recordingToItem(fakeRecording(), 'hit_1'));
  expect(settings.get(captured, 'freq').window).toBe('none');
  expect(settings.get(captured, 'tf')).toMatchObject({ window: 'none', averaging: 'across' });

  // A loaded set that recorded its settings keeps them; one that recorded
  // none (a Python-written file) takes the defaults like a capture.
  const saved = recordingToItem(fakeRecording(), 'saved_by_app');
  saved.ui = { analysis: { freq: { window: 'hann', mode: 'fft', nFrames: 10, csdX: 0, csdY: 1 },
    tf: { chIn: 0, window: 'hann', averaging: 'within', nFrames: 10 } } };
  actions.loadDataset({ formatVersion: 2, pydvmaVersion: 'test', items: [
    saved, recordingToItem(fakeRecording(), 'from_python'),
  ] }, { append: true });
  const byName = (n: string) => get(sel.sets).find((s) => s.name === n)!.id;
  expect(settings.get(byName('saved_by_app'), 'freq').window).toBe('hann');
  expect(settings.get(byName('saved_by_app'), 'tf').averaging).toBe('within');
  expect(settings.get(byName('from_python'), 'freq').window).toBe('none');
  expect(settings.get(byName('from_python'), 'tf').averaging).toBe('across');

  // A Nonlin run's hidden raw capture never takes them.
  const raw = actions.addRecordedSet(recordingToItem(fakeRecording(), 'bla_raw'), { hidden: true });
  expect(settings.get(raw, 'tf').averaging).toBe('within');
});

// ---- Task 10: an opt-in calibration carried forward to new recordings ----

afterEach(() => carriedCal.clear());

function carriedEntry(over: Partial<ChannelCalibration> = {}, basis: 'V' | 'FS' | null = 'V') {
  const provenance: ChannelCalibration = {
    method: 'sensitivity', date: '2026-11-06T10:00:00.000Z', sensitivity: 0.0335, unit: 'Pa',
    reference: null, gain_db: 60, input_mode: 'mic', pad: false, device: 'Audient iD44',
    note: 'spec sheet', carried: false, ...over,
  };
  return { sensitivity: provenance.sensitivity, unit: provenance.unit, basis, provenance };
}

/**
 * A 2-channel bridge capture from the iD44, as the server writes it: its own
 * `device_name`, the stated gain/mode/pad, and a per-channel full scale (volts)
 * unless `vmax` says otherwise (1.0 = full-scale units).
 */
function id44Item(gain: number | null = 60, name = 'mic_1', vmax: number[] = [0.0087, 0.0087]) {
  return recordingToItem(fakeRecording(2, 100), name, {
    deviceDriver: 'soundcard',
    settings: {
      device_driver: 'soundcard', device_name: 'Audient iD44', device_index: 3, VmaxSC: vmax,
      input_gain_db: gain, input_mode: 'mic', input_pad: false,
    },
  });
}

function carryHarness() {
  const sel = createSelection();
  const toasts = createToasts();
  const actions = createActions(createEngineStore(stubClient), sel, undefined, undefined, toasts);
  return { actions, toasts };
}

const NI_CAPS = {
  backends: ['soundcard', 'nidaq'],
  devices: { soundcard: ['Built-in Microphone'], nidaq: [{ name: 'cDAQ1Mod1', ai_channel_count: 4 }] },
  device_caps: {
    'soundcard:0': { name: 'Built-in Microphone' },
    'nidaq:0': { name: 'cDAQ1Mod1' },
  },
  default_input: { driver: 'soundcard', index: 0, name: 'Built-in Microphone' },
} as unknown as BridgeCaps;

test('recordingToItem never writes device_name: the server name stays verbatim', () => {
  // The server named the device it opened: kept exactly, no label added.
  const kept = recordingToItem(fakeRecording(1, 10), 'n', {
    deviceDriver: 'soundcard',
    settings: { device_name: 'Analogue 1 + 2 (Focusrite USB Audio)', device_index: 3, device_hostapi: 'Windows WDM-KS' },
  }, captureDeviceLabel(NI_CAPS, [], 'soundcard:0'));
  expect(kept.settings!.device_name).toBe('Analogue 1 + 2 (Focusrite USB Audio)');
  expect(kept.settings!.device_hostapi).toBe('Windows WDM-KS');
  expect(kept.settings).not.toHaveProperty('capture_device_label');

  // An explicit NI device the server did not name: the web app's own label only.
  const ni = recordingToItem(fakeRecording(1, 10), 'n', {
    deviceDriver: 'nidaq', settings: { device_driver: 'nidaq', device_index: 0, device_name: null },
  }, captureDeviceLabel(NI_CAPS, [], 'nidaq:0'));
  expect(ni.settings!.capture_device_label).toBe('cDAQ1Mod1');
  expect(ni.settings!.device_name).toBeNull();

  // The Default row: neither, whatever default_input says.
  const def = recordingToItem(fakeRecording(1, 10), 'n', {
    deviceDriver: 'mock', settings: { device_driver: 'mock' },
  }, captureDeviceLabel(NI_CAPS, [], ''));
  expect(def.settings).not.toHaveProperty('capture_device_label');
  expect(def.settings).not.toHaveProperty('device_name');

  // A browser capture from a chosen device records its label.
  const web = recordingToItem(fakeRecording(1, 10), 'n', null, 'USB Mic');
  expect(web.settings).toMatchObject({ device_driver: 'web_audio', capture_device_label: 'USB Mic' });
  expect(web.settings).not.toHaveProperty('device_name');
});

test('a capture from a device with a carried calibration arrives calibrated', () => {
  const { actions, toasts } = carryHarness();
  carriedCal.set('Audient iD44', 0, carriedEntry());
  const item = id44Item();
  const setId = actions.addRecordedSet(item);

  expect((item.meta.channel_cal_factors as number[])[0]).toBe(1 / 0.0335);
  expect((item.meta.channel_cal_factors as number[])[1]).toBe(1);
  expect((item.meta.units as string[])[0]).toBe('Pa');
  const cc = item.meta.channel_calibration as (ChannelCalibration | null)[];
  expect(cc[0]!.carried).toBe(true);
  expect(cc[0]!.gain_db).toBe(60);
  expect(cc[0]!.note).toBe('spec sheet');
  expect(cc[1]).toBeNull();
  expect(get(actions.derived)[setId].calFactors![0]).toBe(1 / 0.0335);
  // The same stated gain, mode and pad: nothing to warn about.
  expect(get(toasts.toasts)).toHaveLength(0);
});

test('a carried calibration on a recording that states a different gain raises one info toast', () => {
  const { actions, toasts } = carryHarness();
  carriedCal.set('Audient iD44', 0, carriedEntry());
  carriedCal.set('Audient iD44', 1, carriedEntry({ sensitivity: 0.05 }));
  actions.addRecordedSet(id44Item(50));
  const list = get(toasts.toasts);
  expect(list).toHaveLength(1);
  expect(list[0].level).toBe('info');
  expect(list[0].message).toContain('calibrated at gain');
  expect(list[0].message).toContain('channel 1');
  expect(list[0].message).toContain('channel 2');
});

test('a hidden capture, another device, or channels beyond the capture are left alone', () => {
  const { actions, toasts } = carryHarness();
  carriedCal.set('Audient iD44', 0, carriedEntry());
  carriedCal.set('Audient iD44', 3, carriedEntry({ gain_db: 10 }));

  const hidden = id44Item(50, 'bla_raw');
  actions.addRecordedSet(hidden, { hidden: true });
  expect(hidden.meta.channel_cal_factors).toBeUndefined();
  expect(hidden.meta.channel_calibration).toBeUndefined();

  const other = recordingToItem(fakeRecording(2, 100), 'other', null, 'Scarlett 2i2');
  actions.addRecordedSet(other);
  expect(other.meta.channel_cal_factors).toBeUndefined();

  // Channel 3 is beyond a 2-channel capture: ignored, and no warning for it.
  const item = id44Item();
  actions.addRecordedSet(item);
  expect(item.meta.channel_cal_factors).toEqual([1 / 0.0335, 1]);
  expect((item.meta.channel_calibration as unknown[])).toHaveLength(2);
  expect(get(toasts.toasts)).toHaveLength(0);
});

test('a volts calibration is not applied to a full-scale recording, and says why', () => {
  const { actions, toasts } = carryHarness();
  carriedCal.set('Audient iD44', 0, carriedEntry({}, 'V'));
  // Channel 0 stated no gain this time, so it is in full-scale units.
  const item = id44Item(null, 'mic_2', [1, 0.0087]);
  actions.addRecordedSet(item);
  expect(item.meta.channel_cal_factors).toBeUndefined();
  expect(item.meta.channel_calibration).toBeUndefined();
  const list = get(toasts.toasts);
  expect(list).toHaveLength(1);
  expect(list[0].message).toContain(
    'channel 1: calibrated in volts, this recording is in full-scale units — not applied');
});

test('a full-scale calibration is not applied to a volts recording; an unrecorded basis never is', () => {
  const { actions, toasts } = carryHarness();
  carriedCal.set('Audient iD44', 0, carriedEntry({}, 'FS'));
  carriedCal.set('Audient iD44', 1, carriedEntry({}, null));
  const item = id44Item();
  actions.addRecordedSet(item);
  expect(item.meta.channel_cal_factors).toBeUndefined();
  const msg = get(toasts.toasts)[0].message;
  expect(msg).toContain('channel 1: calibrated in full-scale units, this recording is in volts — not applied');
  expect(msg).toContain('channel 2: calibrated in units it did not record, this recording is in volts — not applied');
});

test('no "gain not stated" toast for an NI channel (volts, no knob); one for a full-scale browser channel', () => {
  const { actions, toasts } = carryHarness();
  carriedCal.set('cDAQ1Mod1', 0, carriedEntry({ gain_db: null, input_mode: null, pad: null, unit: 'm/s²' }, 'V'));
  const ni = recordingToItem(fakeRecording(1, 10), 'acc', {
    deviceDriver: 'nidaq', settings: { device_driver: 'nidaq', device_name: null },
  }, 'cDAQ1Mod1');
  actions.addRecordedSet(ni);
  expect((ni.meta.units as string[])[0]).toBe('m/s²');
  expect(get(toasts.toasts)).toHaveLength(0);

  carriedCal.set('USB Mic', 0, carriedEntry({ gain_db: null, input_mode: null, pad: null }, 'FS'));
  const web = recordingToItem(fakeRecording(1, 10), 'mic', null, 'USB Mic');
  actions.addRecordedSet(web);
  expect((web.meta.units as string[])[0]).toBe('Pa');
  expect(get(toasts.toasts)).toHaveLength(1);
  expect(get(toasts.toasts)[0].message).toContain('channel 1: gain not stated');
});

// ---- carryCalibration: what "use for new recordings too" keeps ----

test('carryCalibration keeps every calibrated channel, edited now or before', () => {
  const { actions, toasts } = carryHarness();
  const setId = actions.addRecordedSet(id44Item());
  // Channel 1 was calibrated earlier (its provenance is in the file); now
  // only channel 2's unit is changed. Both are carried.
  actions.setCalFactors(setId, [1 / 0.0335, 1], ['Pa', 'V'], { provenance: [
    { ...carriedEntry().provenance }, undefined,
  ] });
  actions.setCalFactors(setId, [1 / 0.0335, 1], ['Pa', 'N']);
  expect(actions.carryCalibration(setId, 'today')).toBe(2);

  const kept = carriedCal.forDevice('Audient iD44');
  expect(kept[0]).toMatchObject({ sensitivity: 0.0335, unit: 'Pa', basis: 'V' });
  expect(kept[0].provenance.note).toBe('spec sheet');           // the stored provenance
  expect(kept[1]).toMatchObject({ sensitivity: 1, unit: 'N', basis: 'V' });
  expect(kept[1].provenance).toMatchObject({                     // none stored: a fresh one
    method: 'sensitivity', gain_db: 60, input_mode: 'mic', pad: false,
    device: 'Audient iD44', note: 'today', carried: false,
  });
  expect(get(toasts.toasts)).toHaveLength(0);
});

test('carryCalibration with no calibrated channel stores nothing and says so', () => {
  const { actions, toasts } = carryHarness();
  const setId = actions.addRecordedSet(id44Item());
  expect(actions.carryCalibration(setId)).toBe(0);
  expect(get(carriedCal)).toEqual({});
  const list = get(toasts.toasts);
  expect(list).toHaveLength(1);
  expect(list[0].level).toBe('info');
  expect(list[0].message).toBe('nothing to carry: no channel is calibrated');
});

test('carryCalibration stores nothing for a set no capture could be filed with', () => {
  const { actions } = carryHarness();
  const item = recordingToItem(fakeRecording(1, 10), 'old', { deviceDriver: 'soundcard', settings: {} });
  const setId = actions.addRecordedSet(item);
  actions.setCalFactors(setId, [20], ['Pa']);
  expect(actions.carryCalibration(setId)).toBe(0);
  expect(get(carriedCal)).toEqual({});
});
