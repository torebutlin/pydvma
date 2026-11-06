/**
 * Opt-in calibration carry-forward (Task 10): the store of calibrations a user
 * asked to keep for new recordings, its localStorage round trip (and survival
 * without storage), the device key a capture is filed under, and the
 * gain/mode/pad change warnings.
 */
import { get } from 'svelte/store';
import { expect, test } from 'vitest';
import {
  CARRIED_CAL_KEY, captureDeviceLabel, carriedNote, carryBasisMessage, carryKeyFor, carryWarnings,
  createCarriedCal, deviceKeyFor, selectedDeviceKey, type CarriedChannelCal,
} from '../../src/lib/stores/carriedCal';
import type { ChannelCalibration } from '../../src/lib/model/calibration';
import type { BridgeCaps } from '../../src/lib/audio/provider';

function fakeStorage(seed: Record<string, string> = {}) {
  const map = new Map<string, string>(Object.entries(seed));
  return {
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    _map: map,
  };
}

const throwing = {
  getItem: () => { throw new Error('SecurityError'); },
  setItem: () => { throw new Error('QuotaExceededError'); },
  removeItem: () => { throw new Error('SecurityError'); },
};

function prov(over: Partial<ChannelCalibration> = {}): ChannelCalibration {
  return {
    method: 'sensitivity', date: '2026-11-06T10:00:00.000Z', sensitivity: 0.0335, unit: 'Pa',
    reference: null, gain_db: 60, input_mode: 'mic', pad: false, device: 'Audient iD44',
    note: 'spec sheet', carried: false, ...over,
  };
}

function entry(over: Partial<ChannelCalibration> = {}, basis: 'V' | 'FS' | null = 'V'): CarriedChannelCal {
  const p = prov(over);
  return { sensitivity: p.sensitivity, unit: p.unit, basis, provenance: p };
}

test('the store round-trips through localStorage', () => {
  const storage = fakeStorage();
  const a = createCarriedCal(() => storage);
  a.set('Audient iD44', 0, entry());
  a.set('Audient iD44', 1, entry({ sensitivity: 0.05, gain_db: 50 }));
  expect(storage._map.has(CARRIED_CAL_KEY)).toBe(true);

  const b = createCarriedCal(() => storage);
  const got = b.forDevice('Audient iD44');
  expect(got[0]).toEqual(entry());
  expect(got[1].sensitivity).toBe(0.05);
  expect(got[1].provenance.gain_db).toBe(50);
  expect(get(b)['Audient iD44'][0].unit).toBe('Pa');
  expect(b.forDevice('Scarlett 2i2')).toEqual({});
});

test('clear forgets one device, or every device', () => {
  const storage = fakeStorage();
  const s = createCarriedCal(() => storage);
  s.set('Audient iD44', 0, entry());
  s.set('ESI U24 XL', 0, entry({ unit: 'm/s²', sensitivity: 0.01 }));
  s.clear('Audient iD44');
  expect(s.forDevice('Audient iD44')).toEqual({});
  expect(s.forDevice('ESI U24 XL')[0].unit).toBe('m/s²');
  expect(createCarriedCal(() => storage).forDevice('Audient iD44')).toEqual({});
  s.clear();
  expect(get(s)).toEqual({});
  expect(createCarriedCal(() => storage).forDevice('ESI U24 XL')).toEqual({});
});

test('a throwing storage, or none at all, still works in memory', () => {
  for (const accessor of [
    () => throwing,
    () => { throw new Error('SecurityError: localStorage is blocked'); },
    () => null,
  ]) {
    const s = createCarriedCal(accessor as () => Storage | null);
    expect(get(s)).toEqual({});
    s.set('Audient iD44', 0, entry());
    expect(s.forDevice('Audient iD44')[0].sensitivity).toBe(0.0335);
    s.clear('Audient iD44');
    expect(s.forDevice('Audient iD44')).toEqual({});
  }
});

test('a corrupt or tampered stored value is ignored, entry by entry', () => {
  expect(get(createCarriedCal(() => fakeStorage({ [CARRIED_CAL_KEY]: '{not json' })))).toEqual({});
  const storage = fakeStorage({
    [CARRIED_CAL_KEY]: JSON.stringify({
      'Audient iD44': {
        0: entry(),
        1: { sensitivity: -1, unit: 'Pa', provenance: prov() },
        2: { sensitivity: 0.1, unit: 'Pa' },
        x: entry(),
      },
      junk: 7,
    }),
  });
  const s = createCarriedCal(() => storage);
  expect(Object.keys(s.forDevice('Audient iD44'))).toEqual(['0']);
  expect(s.forDevice('junk')).toEqual({});
});

test('an entry stored before the basis was kept loads with an unknown basis', () => {
  const { basis: _drop, ...old } = entry();
  const s = createCarriedCal(() => fakeStorage({
    [CARRIED_CAL_KEY]: JSON.stringify({ 'Audient iD44': { 0: old } }),
  }));
  expect(s.forDevice('Audient iD44')[0].basis).toBeNull();
  expect(s.forDevice('Audient iD44')[0].sensitivity).toBe(0.0335);
});

test('set refuses an unusable entry instead of storing it', () => {
  const s = createCarriedCal(() => null);
  s.set('', 0, entry());
  s.set('Audient iD44', -1, entry());
  s.set('Audient iD44', 0, { ...entry(), sensitivity: Number.NaN });
  expect(get(s)).toEqual({});
});

test('deviceKeyFor: the server device name, else the capture label, else the driver', () => {
  expect(deviceKeyFor({ device_name: 'Audient iD44', capture_device_label: 'x', device_driver: 'soundcard' }))
    .toBe('Audient iD44');
  expect(deviceKeyFor({ device_name: null, capture_device_label: 'Dev1', device_driver: 'nidaq' })).toBe('Dev1');
  expect(deviceKeyFor({ device_name: null, device_driver: 'nidaq' })).toBe('nidaq');
  expect(deviceKeyFor({ device_name: '', device_driver: 'web_audio' })).toBe('web_audio');
  expect(deviceKeyFor({ fs: 8000 })).toBe('');
  expect(deviceKeyFor(null)).toBe('');
});

test('carryKeyFor: only a key a new capture can be filed under', () => {
  expect(carryKeyFor({ device_name: 'Audient iD44', device_driver: 'soundcard' })).toBe('Audient iD44');
  expect(carryKeyFor({ capture_device_label: 'Dev1', device_driver: 'nidaq' })).toBe('Dev1');
  expect(carryKeyFor({ device_driver: 'web_audio' })).toBe('web_audio');
  for (const driver of ['soundcard', 'nidaq', 'mock']) {
    expect(carryKeyFor({ device_name: null, device_driver: driver })).toBeNull();
  }
  expect(carryKeyFor({ fs: 8000 })).toBeNull();
  expect(carryKeyFor(null)).toBeNull();
});

test('carryWarnings: nothing when the stated gain, mode and pad are unchanged', () => {
  expect(carryWarnings(entry(), { gain_db: 60, input_mode: 'mic', pad: false }, 0, 'V')).toEqual([]);
});

test('carryWarnings: a different stated gain', () => {
  expect(carryWarnings(entry(), { gain_db: 50, input_mode: 'mic', pad: false }, 0, 'V')).toEqual([
    'channel 1: calibrated at gain 60 dB, this recording states 50 dB',
  ]);
});

test('carryWarnings: a gain unstated at either end', () => {
  const msg = 'channel 2: gain not stated, so pydvma cannot tell whether it moved';
  expect(carryWarnings(entry(), { gain_db: null, input_mode: 'mic', pad: false }, 1, 'V')).toEqual([msg]);
  expect(carryWarnings(entry({ gain_db: null }), { gain_db: 60, input_mode: 'mic', pad: false }, 1, 'V'))
    .toEqual([msg]);
});

test('carryWarnings: no knob to move on a volts channel with no gain stated at either end', () => {
  // NI, or a fixed-gain card: in volts, no gain anywhere, nothing to warn of.
  const ni = entry({ gain_db: null, input_mode: null, pad: null }, 'V');
  expect(carryWarnings(ni, { gain_db: null, input_mode: null, pad: null }, 0, 'V')).toEqual([]);
  // Full-scale units with no gain stated (Web Audio, an unstated preamp) still warn.
  const fs = entry({ gain_db: null, input_mode: null, pad: null }, 'FS');
  expect(carryWarnings(fs, { gain_db: null, input_mode: null, pad: null }, 0, 'FS')).toEqual([
    'channel 1: gain not stated, so pydvma cannot tell whether it moved',
  ]);
});

test('carryBasisMessage: a calibration is never carried across volts and full-scale units', () => {
  expect(carryBasisMessage(entry({}, 'V'), 'V', 0)).toBeNull();
  expect(carryBasisMessage(entry({}, 'FS'), 'FS', 0)).toBeNull();
  expect(carryBasisMessage(entry({}, 'V'), 'FS', 0))
    .toBe('channel 1: calibrated in volts, this recording is in full-scale units — not applied');
  expect(carryBasisMessage(entry({}, 'FS'), 'V', 1))
    .toBe('channel 2: calibrated in full-scale units, this recording is in volts — not applied');
  expect(carryBasisMessage(entry({}, null), 'V', 0))
    .toBe('channel 1: calibrated in units it did not record, this recording is in volts — not applied');
});

test('carryWarnings: a different input mode or pad, one message each', () => {
  const w = carryWarnings(entry(), { gain_db: 60, input_mode: 'line', pad: true }, 0, 'V');
  expect(w).toHaveLength(2);
  expect(w[0]).toBe('channel 1: calibrated in mic mode, this recording states line');
  expect(w[1]).toBe('channel 1: calibrated with the pad off, this recording states it on');
});

test('carriedNote names the carried channels and their units', () => {
  expect(carriedNote({})).toBeNull();
  expect(carriedNote({ 0: entry(), 1: entry() })).toBe('calibration carried for channels 1, 2 (Pa)');
  expect(carriedNote({ 2: entry({ unit: 'm/s²' }) })).toBe('calibration carried for channel 3 (m/s²)');
  expect(carriedNote({ 1: entry({ unit: 'm/s²' }), 0: entry() }))
    .toBe('calibration carried for channels 1, 2 (Pa, m/s²)');
});

test('captureDeviceLabel: the bridge caps name or the browser label, never for the Default row', () => {
  const caps = {
    backends: ['soundcard'], devices: { soundcard: ['MacBook Pro Microphone', 'Audient iD44'], nidaq: [] },
    device_caps: { 'soundcard:1': { name: 'Audient iD44' } },
    default_input: { driver: 'soundcard', index: 0, name: 'MacBook Pro Microphone' },
  } as unknown as BridgeCaps;
  expect(captureDeviceLabel(caps, [], 'soundcard:1')).toBe('Audient iD44');
  expect(captureDeviceLabel(caps, [], '')).toBeNull();          // not default_input
  expect(captureDeviceLabel(caps, [], 'soundcard:7')).toBeNull();
  const web = [
    { deviceId: 'default', label: 'Default - iD44', groupId: 'g', hasLabel: true },
    { deviceId: 'abc', label: 'Audient iD44', groupId: 'g', hasLabel: true },
    { deviceId: 'def', label: 'Input def', groupId: 'g', hasLabel: false },
  ];
  expect(captureDeviceLabel(null, web, 'abc')).toBe('Audient iD44');
  expect(captureDeviceLabel(null, web, '')).toBeNull();
  expect(captureDeviceLabel(null, web, 'def')).toBeNull();     // no permission: a placeholder label

  // Setup's key for the selected device is the key a capture from it is filed under.
  expect(selectedDeviceKey(caps, [], 'soundcard:1')).toBe('Audient iD44');
  expect(selectedDeviceKey(caps, [], '')).toBe('');            // only the server knows
  expect(selectedDeviceKey(caps, [], 'soundcard:7')).toBe('');
  expect(selectedDeviceKey(null, web, 'abc')).toBe('Audient iD44');
  expect(selectedDeviceKey(null, web, '')).toBe('web_audio');
  expect(selectedDeviceKey(null, web, 'def')).toBe('web_audio');
});
