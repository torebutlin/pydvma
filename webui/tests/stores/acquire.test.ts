import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createAcquireStore, recordingToItem, recordingToDataset, type AcquireSettings } from '../../src/lib/stores/acquire';
import { capabilities } from '../../src/lib/stores/stages';
import type { Recording } from '../../src/lib/audio/source';

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
  const track = { stop: vi.fn(), getCapabilities: () => ({ channelCount: { max: 2 } }), getSettings: () => ({ sampleRate: 48000 }) };
  const stream = { getTracks: () => [track], getAudioTracks: () => [track] };
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockResolvedValue(stream);

  const store = createAcquireStore();
  await store.requestPermission();

  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled();
  expect(track.stop).toHaveBeenCalled();                 // throwaway stream released
  expect(get(store.deviceCaps)).toEqual({ maxChannels: 2, sampleRate: 48000 });
  expect(get(store.devices)).toHaveLength(1);            // re-enumerated
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
