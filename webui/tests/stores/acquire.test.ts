import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createAcquireStore, recordingToItem, recordingToDataset, type AcquireSettings } from '../../src/lib/stores/acquire';
import { capabilities } from '../../src/lib/stores/stages';
import type { Recording } from '../../src/lib/audio/source';
import type {
  BridgeRecordingMeta,
  LogStatusEvent,
  SourceProvider,
} from '../../src/lib/audio/provider';

beforeEach(() => {
  // Reset capabilities before each test.
  capabilities.set({ liveSource: false, fitEngine: false });
  // Stub navigator.mediaDevices for init().
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue([
        { deviceId: 'mic-1', label: 'Test Mic', groupId: 'g1', kind: 'audioinput', toJSON: () => ({}) },
      ]),
      getUserMedia: vi.fn(),
    },
  });
});
afterEach(() => vi.restoreAllMocks());

test('init() flips liveSource capability and populates devices', async () => {
  const store = createAcquireStore();
  expect(get(capabilities).liveSource).toBe(false);
  await store.init();
  expect(get(capabilities).liveSource).toBe(true);
  expect(get(store.devices)).toHaveLength(1);
  expect(get(store.devices)[0].label).toBe('Test Mic');
});

test('init() is a no-op when navigator.mediaDevices is missing', async () => {
  vi.stubGlobal('navigator', {});
  const store = createAcquireStore();
  await store.init();
  // Should not throw; liveSource stays false.
  expect(get(capabilities).liveSource).toBe(false);
});

test('patch() updates individual settings fields', () => {
  const store = createAcquireStore();
  const initial = get(store.settings);
  expect(initial.sampleRate).toBe(44100);
  store.patch({ sampleRate: 48000 });
  expect(get(store.settings).sampleRate).toBe(48000);
  expect(get(store.settings).durationS).toBe(initial.durationS); // unchanged
});

test('default settings are sensible', () => {
  const store = createAcquireStore();
  const s = get(store.settings);
  expect(s.sampleRate).toBe(44100);
  expect(s.channelCount).toBe(1);
  expect(s.durationS).toBe(2.0);
  expect(s.deviceId).toBe('');
  // DSP constraints default OFF (raw measurement — browsers default them on).
  expect(s.echoCancellation).toBe(false);
  expect(s.noiseSuppression).toBe(false);
  expect(s.autoGainControl).toBe(false);
});

test('requestPermission opens a throwaway stream then re-enumerates', async () => {
  const track = {
    stop: vi.fn(),
    getCapabilities: () => ({
      channelCount: { min: 1, max: 2 },
      sampleRate: { min: 8000, max: 96000 },
      latency: { min: 0.01, max: 0.1 },
    }),
    getSettings: () => ({ sampleRate: 48000, channelCount: 2, latency: 0.02 }),
  };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockResolvedValue(stream);

  const store = createAcquireStore();
  await store.requestPermission();

  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled();
  expect(track.stop).toHaveBeenCalled();                 // throwaway stream released
  // Round-3: the full capability ranges + current settings are surfaced.
  expect(get(store.deviceCaps)).toEqual({
    channelCount: { min: 1, max: 2 },
    sampleRate: { min: 8000, max: 96000 },
    latency: { min: 0.01, max: 0.1 },
    current: { sampleRate: 48000, channelCount: 2, latency: 0.02 },
  });
  expect(get(store.devices)).toHaveLength(1);            // re-enumerated
});

test('latency hint defaults to unset and round-trips through patch', () => {
  const store = createAcquireStore();
  expect(get(store.settings).latency).toBeUndefined();   // no hint by default
  store.patch({ latency: 0.02 });
  expect(get(store.settings).latency).toBe(0.02);
  store.patch({ latency: undefined });
  expect(get(store.settings).latency).toBeUndefined();   // clearable
});

test('status starts idle', () => {
  const store = createAcquireStore();
  expect(get(store.status)).toBe('idle');
  expect(get(store.statusText)).toBe('');
  expect(get(store.errorMsg)).toBe('');
});

// ---- recordingToItem / recordingToDataset ----

function fakeRecording(): Recording {
  const nSamples = 100;
  const nChannels = 2;
  const timeAxis = new Float64Array(nSamples);
  const data = new Float64Array(nSamples * nChannels);
  for (let i = 0; i < nSamples; i++) {
    timeAxis[i] = i / 44100;
    data[i * nChannels + 0] = Math.sin(i);
    data[i * nChannels + 1] = Math.cos(i);
  }
  return { data, timeAxis, fs: 44100, nChannels, nSamples };
}

test('recordingToItem produces a valid TimeData DvmaItem', () => {
  const rec = fakeRecording();
  const item = recordingToItem(rec, 'test_capture');
  expect(item.kind).toBe('TimeData');
  expect(item.arrays.time_axis.shape).toEqual([100]);
  expect(item.arrays.time_data.shape).toEqual([100, 2]);
  expect(item.arrays.time_data.data).toBe(rec.data); // same buffer
  expect(item.meta.test_name).toBe('test_capture');
  expect(item.settings).toEqual(expect.objectContaining({
    fs: 44100,
    channels: 2,
    device_driver: 'web_audio',
  }));
});

test('recordingToItem auto-generates a timestamp-based name when none provided', () => {
  const rec = fakeRecording();
  const item = recordingToItem(rec);
  expect((item.meta.test_name as string).startsWith('set_')).toBe(true);
});

test('recordingToDataset wraps a recording as a single-item dataset', () => {
  const rec = fakeRecording();
  const ds = recordingToDataset(rec, 'my_set');
  expect(ds.formatVersion).toBe(2);
  expect(ds.items).toHaveLength(1);
  expect(ds.items[0].kind).toBe('TimeData');
  expect(ds.items[0].meta.test_name).toBe('my_set');
});

// ---- Wave C: bridged-set metadata join ----

test('recordingToItem carries bridge metadata (driver/units/cal/name/time) when provided', () => {
  const item = recordingToItem(fakeRecording(), undefined, {
    deviceDriver: 'nidaq',
    testName: 'imp_01',
    timestring: '2026-07-07 09:00:00',
    timestamp: '2026-07-07T09:00:00',
    units: ['V', 'm/s^2'],
    channelCalFactors: [1.5, 3.0],
  });
  expect(item.settings!.device_driver).toBe('nidaq');
  expect(item.meta.test_name).toBe('imp_01');
  expect(item.meta.timestring).toBe('2026-07-07 09:00:00');
  expect(item.meta.timestamp).toBe('2026-07-07T09:00:00');
  expect(item.meta.units).toEqual(['V', 'm/s^2']);
  expect(item.meta.channel_cal_factors).toEqual([1.5, 3.0]);
});

test('recordingToItem without meta keeps the Web Audio behaviour (device_driver web_audio)', () => {
  const item = recordingToItem(fakeRecording(), 'x');
  expect(item.settings!.device_driver).toBe('web_audio');
  expect(item.meta.timestamp).toBeUndefined();
  expect(item.meta.units).toBeUndefined();
});

// ---- Wave C: bridge record wiring (status events + metadata) ----

/** A minimal fake bridge provider whose log emits armed→timeout then resolves. */
function fakeBridgeProvider(rec: Recording, meta: BridgeRecordingMeta | null): SourceProvider {
  let statusCb: ((e: LogStatusEvent) => void) | null = null;
  return {
    kind: 'bridge',
    async capabilities() {
      return {
        v: 1, backends: ['mock'], devices: { soundcard: [], nidaq: [] },
        fs_ladders: {}, max_channels: null, pretrigger: true, ao: true,
      };
    },
    async enumerateInputDevices() {
      return [{ deviceId: 'mock:0', label: 'Mock', groupId: 'mock', hasLabel: true }];
    },
    startRecording() {
      return {
        promise: (async () => { statusCb?.('armed'); statusCb?.('timeout'); return rec; })(),
        cancel() {},
        elapsed: () => 0,
      };
    },
    async startMonitor() {
      return { stop() {}, fs: 44100, nChannels: 1 };
    },
    setConfig() {},
    onLogStatus(cb) { statusCb = cb; },
    lastMeta() { return meta; },
  };
}

test('bridge record surfaces pretrigger status events and carries container metadata', async () => {
  const rec = fakeRecording();
  const meta: BridgeRecordingMeta = {
    deviceDriver: 'nidaq', testName: 'shot1', channelCalFactors: [2, 1], units: ['V', 'V'],
  };
  const store = createAcquireStore(fakeBridgeProvider(rec, meta));

  const out = await store.record();
  expect(out).toBe(rec);
  // The last pretrigger event surfaced to the status store.
  expect(get(store.pretrigStatus)).toBe('timeout');
  // Provenance captured from the provider's lastMeta().
  expect(store.lastRecordingMeta).toEqual(meta);
  // The join keeps the real driver + name (not relabelled web_audio).
  const item = recordingToItem(out, undefined, store.lastRecordingMeta);
  expect(item.settings!.device_driver).toBe('nidaq');
  expect(item.meta.test_name).toBe('shot1');
  expect(item.meta.channel_cal_factors).toEqual([2, 1]);
});

test('bridge record resets pretrigStatus and lastRecordingMeta at the start of each capture', async () => {
  const store = createAcquireStore(fakeBridgeProvider(fakeRecording(), null));
  await store.record();
  // Provider returned null meta → nothing carried over.
  expect(store.lastRecordingMeta).toBeNull();
  // Even with a null-meta provider, the status events still flowed.
  expect(get(store.pretrigStatus)).toBe('timeout');
});
