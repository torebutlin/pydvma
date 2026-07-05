import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { enumerateInputDevices, startRecording, type RecordConfig } from '../../src/lib/audio/source';

// ---- Mock navigator.mediaDevices ----

const MOCK_DEVICES: MediaDeviceInfo[] = [
  { deviceId: 'mic-1', label: 'Built-in Microphone', groupId: 'g1', kind: 'audioinput', toJSON: () => ({}) },
  { deviceId: 'mic-2', label: 'USB Mic', groupId: 'g2', kind: 'audioinput', toJSON: () => ({}) },
  { deviceId: 'spk-1', label: 'Speakers', groupId: 'g1', kind: 'audiooutput', toJSON: () => ({}) },
];

beforeEach(() => {
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue(MOCK_DEVICES),
      getUserMedia: vi.fn(),
    },
  });
});
afterEach(() => vi.restoreAllMocks());

test('enumerateInputDevices filters to audioinput only', async () => {
  const devices = await enumerateInputDevices();
  expect(devices).toHaveLength(2);
  expect(devices[0].deviceId).toBe('mic-1');
  expect(devices[1].deviceId).toBe('mic-2');
  expect(devices.every(d => 'label' in d && 'deviceId' in d && 'groupId' in d)).toBe(true);
});

test('enumerateInputDevices returns [] when mediaDevices is unavailable', async () => {
  vi.stubGlobal('navigator', {});
  const devices = await enumerateInputDevices();
  expect(devices).toEqual([]);
});

test('startRecording.cancel rejects with "cancelled"', async () => {
  // Mock getUserMedia to return a stream that never produces data.
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track], getAudioTracks: () => [{ getSettings: () => ({ channelCount: 1 }) }] };
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockResolvedValue(stream);

  // Mock AudioContext as a proper constructor class.
  const mockProcessor = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    onaudioprocess: null as ((ev: unknown) => void) | null,
  };
  const mockSource = { connect: vi.fn(), disconnect: vi.fn(), channelCount: 1 };
  class MockAudioContext {
    sampleRate = 44100;
    destination = {};
    createMediaStreamSource() { return mockSource; }
    createScriptProcessor() { return mockProcessor; }
    close = vi.fn();
  }
  vi.stubGlobal('AudioContext', MockAudioContext);

  const cfg: RecordConfig = { sampleRate: 44100, channelCount: 1, durationS: 2 };
  const handle = startRecording(cfg);

  // Give the async chain a tick to set up, then cancel.
  await new Promise(r => setTimeout(r, 10));
  handle.cancel();

  // Fire the processor callback so the cancel path runs.
  if (mockProcessor.onaudioprocess) {
    mockProcessor.onaudioprocess({
      inputBuffer: { length: 1024, getChannelData: () => new Float32Array(1024) },
    });
  }

  await expect(handle.promise).rejects.toThrow('cancelled');
  expect(track.stop).toHaveBeenCalled();
});

test('startRecording rejects with clear message on permission denied', async () => {
  const err = new DOMException('Permission denied', 'NotAllowedError');
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockRejectedValue(err);

  vi.stubGlobal('AudioContext', vi.fn(() => ({ sampleRate: 44100 })));
  const cfg: RecordConfig = { sampleRate: 44100, channelCount: 1, durationS: 1 };
  const handle = startRecording(cfg);

  await expect(handle.promise).rejects.toThrow('Microphone permission denied');
});

test('startRecording completes and returns correct shape', async () => {
  const BLOCK = 256;
  const FS = 8000;
  const DURATION = 0.05; // 400 samples at 8 kHz
  const TOTAL = Math.ceil(FS * DURATION);

  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track], getAudioTracks: () => [{ getSettings: () => ({ channelCount: 1 }) }] };
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockResolvedValue(stream);

  let processorCallback: ((ev: unknown) => void) | null = null;
  const mockProcessor = {
    connect: vi.fn(),
    disconnect: vi.fn(),
    set onaudioprocess(fn: ((ev: unknown) => void) | null) { processorCallback = fn; },
    get onaudioprocess() { return processorCallback; },
  };
  const mockSource = { connect: vi.fn(), disconnect: vi.fn(), channelCount: 1 };
  class MockAudioContext {
    sampleRate = FS;
    destination = {};
    createMediaStreamSource() { return mockSource; }
    createScriptProcessor() { return mockProcessor; }
    close = vi.fn();
  }
  vi.stubGlobal('AudioContext', MockAudioContext);

  const cfg: RecordConfig = { sampleRate: FS, channelCount: 1, durationS: DURATION };
  const handle = startRecording(cfg);

  // Wait for the async setup to wire the callback.
  await new Promise(r => setTimeout(r, 10));

  // Simulate audio callbacks until done.
  let samplesDelivered = 0;
  while (samplesDelivered < TOTAL && processorCallback) {
    const n = Math.min(BLOCK, TOTAL - samplesDelivered);
    const buf = new Float32Array(n);
    for (let i = 0; i < n; i++) buf[i] = Math.sin(2 * Math.PI * 440 * (samplesDelivered + i) / FS);
    processorCallback({
      inputBuffer: { length: n, getChannelData: () => buf },
    });
    samplesDelivered += n;
  }

  const rec = await handle.promise;
  expect(rec.fs).toBe(FS);
  expect(rec.nChannels).toBe(1);
  expect(rec.nSamples).toBe(TOTAL);
  expect(rec.data.length).toBe(TOTAL * 1); // (N, 1) row-major
  expect(rec.timeAxis.length).toBe(TOTAL);
  // Time axis starts at 0, ends near duration.
  expect(rec.timeAxis[0]).toBe(0);
  expect(rec.timeAxis[TOTAL - 1]).toBeCloseTo((TOTAL - 1) / FS, 6);
  // First sample should be sin(0) ≈ 0.
  expect(Math.abs(rec.data[0])).toBeLessThan(0.01);
});
