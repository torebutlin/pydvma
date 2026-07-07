import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createAcquireStore, recordingToItem, recordingToDataset, type AcquireSettings } from '../../src/lib/stores/acquire';
import { capabilities } from '../../src/lib/stores/stages';
import type { Recording } from '../../src/lib/audio/source';
import type {
  BridgeCaps,
  BridgeConfig,
  BridgeRecordingMeta,
  ConfiguredInfo,
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

// ---- Wave D follow-up: voltage clamp + DSA coerced-fs note ----

/**
 * A bridge fake carrying a cDAQ device_caps entry (9234 AI rail ±5 V, 9260
 * AO rail ±4.2426 V) plus injectable hooks: `fireConfigured` drives the
 * onConfigured sink, `config()` reads the last kwargs forwarded to setConfig.
 */
function richBridgeProvider() {
  let configuredCb: ((info: ConfiguredInfo) => void) | null = null;
  let lastConfig: BridgeConfig = {};
  const caps: BridgeCaps = {
    v: 1,
    backends: ['nidaq'],
    devices: {
      soundcard: [],
      nidaq: [{
        name: 'cDAQ1', product_type: 'cDAQ-9174', is_chassis: true,
        ai_channel_count: 4, ao_channel_count: 2,
        module_names: [], module_ai_counts: {}, module_ao_counts: {},
      }],
    },
    fs_ladders: { 'nidaq:0': [51200] },
    max_channels: { 'nidaq:0': { input: 4, output: 2 } },
    pretrigger: true,
    ao: true,
    device_caps: {
      'nidaq:0': { driver: 'nidaq', index: 0, name: 'cDAQ1', ao: true, ai_vmax: 5, ao_vmax: 4.2426 },
    },
  };
  const provider: SourceProvider = {
    kind: 'bridge',
    async capabilities() { return caps; },
    async enumerateInputDevices() {
      return [{ deviceId: 'nidaq:0', label: 'NI: cDAQ1 (4 ch)', groupId: 'nidaq', hasLabel: true }];
    },
    startRecording() {
      return { promise: Promise.resolve(fakeRecording()), cancel() {}, elapsed: () => 0 };
    },
    async startMonitor() { return { stop() {}, fs: 51200, nChannels: 4 }; },
    setConfig(cfg) { lastConfig = { ...cfg }; },
    onLogStatus() {},
    onConfigured(cb) { configuredCb = cb; },
    lastMeta() { return null; },
  };
  return {
    provider,
    fireConfigured: (info: ConfiguredInfo) => configuredCb?.(info),
    config: () => lastConfig,
  };
}

test('selecting a device clamps output_VmaxNI down to the ao_vmax rail (motivating 9260 bug)', async () => {
  const { provider, config } = richBridgeProvider();
  const store = createAcquireStore(provider);
  await store.init();
  // Nothing selected yet → no clamp (deviceId '').
  expect(get(store.bridgeConfig).outputVmaxNI).toBeUndefined();
  // Select the chassis: the pydvma 5 V default exceeds the 9260's ±4.2426 V
  // rail, so the store clamps output_VmaxNI down AND forwards it to the bridge.
  store.patch({ deviceId: 'nidaq:0' });
  expect(get(store.bridgeConfig).outputVmaxNI).toBe(4.2426);
  expect(config().outputVmaxNI).toBe(4.2426);
  // The AI rail equals the 5 V default → VmaxNI left unset (no needless clamp).
  expect(get(store.bridgeConfig).vmaxNI).toBeUndefined();
});

test('an over-range VmaxNI is clamped to the device ai_vmax on device select', async () => {
  const { provider } = richBridgeProvider();
  const store = createAcquireStore(provider);
  await store.init();
  store.patchBridge({ vmaxNI: 10 });        // user asked for ±10 V input range
  store.patch({ deviceId: 'nidaq:0' });
  expect(get(store.bridgeConfig).vmaxNI).toBe(5); // clamped to the 9234 ±5 rail
});

test('coercedFs is set on a DSA rate snap and cleared on an exact honour', async () => {
  const { provider, fireConfigured } = richBridgeProvider();
  const store = createAcquireStore(provider);
  await store.init();
  expect(get(store.coercedFs)).toBeNull();
  // Requested 8000, device runs 8533.33 (9234 off-ladder snap).
  fireConfigured({ requestedFs: 8000, configuredFs: 8533.33, channels: 2 });
  expect(get(store.coercedFs)).toEqual({ requested: 8000, configured: 8533.33 });
  // A later exact honour clears the note.
  fireConfigured({ requestedFs: 44100, configuredFs: 44100, channels: 1 });
  expect(get(store.coercedFs)).toBeNull();
});

test('sub-Hz float noise in the resolved rate is treated as an exact honour', async () => {
  const { provider, fireConfigured } = richBridgeProvider();
  const store = createAcquireStore(provider);
  await store.init();
  fireConfigured({ requestedFs: 48000, configuredFs: 48000.01, channels: 1 });
  expect(get(store.coercedFs)).toBeNull();
});

test('editing the requested fs or device clears a standing coerced-fs note', async () => {
  const { provider, fireConfigured } = richBridgeProvider();
  const store = createAcquireStore(provider);
  await store.init();
  fireConfigured({ requestedFs: 8000, configuredFs: 8533.33, channels: 2 });
  expect(get(store.coercedFs)).not.toBeNull();
  store.patch({ sampleRate: 16000 });
  expect(get(store.coercedFs)).toBeNull();
});
