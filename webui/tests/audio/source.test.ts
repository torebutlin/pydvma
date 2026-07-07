import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { enumerateInputDevices, startRecording, type RecordConfig } from '../../src/lib/audio/source';

// ---- Mock navigator.mediaDevices ----

const MOCK_DEVICES: MediaDeviceInfo[] = [
  { deviceId: 'mic-1', label: 'Built-in Microphone', groupId: 'g1', kind: 'audioinput', toJSON: () => ({}) },
  { deviceId: 'mic-2', label: 'USB Mic', groupId: 'g2', kind: 'audioinput', toJSON: () => ({}) },
  { deviceId: 'spk-1', label: 'Speakers', groupId: 'g1', kind: 'audiooutput', toJSON: () => ({}) },
];

// ---- worklet-path (primary) mocks ----
// Tests that stub a bare AudioContext WITHOUT `audioWorklet` exercise the
// ScriptProcessorNode FALLBACK; these add a working AudioWorklet surface so
// the primary path can be driven too.

let lastWorkletNode: MockAudioWorkletNode | null = null;
class MockAudioWorkletNode {
  port = { onmessage: null as ((ev: unknown) => void) | null, close: vi.fn() };
  connect = vi.fn();
  disconnect = vi.fn();
  processorOptions: { chunkFrames?: number; nChannels?: number } | undefined;
  constructor(_ctx: unknown, _name: string, options?: { processorOptions?: unknown }) {
    this.processorOptions = options?.processorOptions as this['processorOptions'];
    lastWorkletNode = this;
  }
}
/** An AudioContext class (rate `fs`) whose `audioWorklet.addModule` uses `addModule`. */
function workletCtxClass(fs: number, addModule: ReturnType<typeof vi.fn>) {
  return class MockWorkletAudioContext {
    sampleRate = fs;
    destination = {};
    audioWorklet = { addModule };
    createMediaStreamSource() { return { connect: vi.fn(), disconnect: vi.fn(), channelCount: 1 }; }
    createScriptProcessor() { return { connect: vi.fn(), disconnect: vi.fn(), onaudioprocess: null }; }
    close = vi.fn();
  };
}

beforeEach(() => {
  lastWorkletNode = null;
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue(MOCK_DEVICES),
      getUserMedia: vi.fn(),
    },
  });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

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

test('startRecording completes on the AudioWorklet path and returns correct shape', async () => {
  const FS = 8000;
  const DURATION = 0.05; // 400 samples at 8 kHz
  const TOTAL = Math.ceil(FS * DURATION);

  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track], getAudioTracks: () => [{ getSettings: () => ({ channelCount: 1 }) }] };
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockResolvedValue(stream);

  const addModule = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('AudioContext', workletCtxClass(FS, addModule));
  vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode);

  const cfg: RecordConfig = { sampleRate: FS, channelCount: 1, durationS: DURATION };
  const handle = startRecording(cfg);

  // Wait for the async setup (getUserMedia + addModule) to wire the port.
  await new Promise(r => setTimeout(r, 10));

  expect(addModule).toHaveBeenCalledTimes(1);
  expect(lastWorkletNode).not.toBeNull();
  // Recording cadence == old ScriptProcessorNode BUFFER_SIZE (4096).
  expect(lastWorkletNode!.processorOptions?.chunkFrames).toBe(4096);

  // Drive interleaved mono chunks over the port; the final chunk overshoots
  // TOTAL so the consume()/remaining clamp is exercised.
  const BLOCK = 256;
  let delivered = 0;
  while (delivered < TOTAL && lastWorkletNode!.port.onmessage) {
    const chunk = new Float32Array(BLOCK);
    for (let i = 0; i < BLOCK; i++) chunk[i] = Math.sin(2 * Math.PI * 440 * (delivered + i) / FS);
    lastWorkletNode!.port.onmessage!({ data: { data: chunk, nSamples: BLOCK, nChannels: 1 } });
    delivered += BLOCK;
  }

  const rec = await handle.promise;
  expect(rec.fs).toBe(FS);
  expect(rec.nChannels).toBe(1);
  expect(rec.nSamples).toBe(TOTAL);
  expect(rec.data.length).toBe(TOTAL * 1);
  expect(rec.timeAxis.length).toBe(TOTAL);
  expect(rec.timeAxis[0]).toBe(0);
  expect(rec.timeAxis[TOTAL - 1]).toBeCloseTo((TOTAL - 1) / FS, 6);
  expect(Math.abs(rec.data[0])).toBeLessThan(0.01); // sin(0) ≈ 0
  expect(track.stop).toHaveBeenCalled();
});

test('startRecording releases the mic if the worklet module fails to load (C2)', async () => {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track], getAudioTracks: () => [{ getSettings: () => ({ channelCount: 1 }) }] };
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockResolvedValue(stream);

  // addModule rejects (a fetch failure or worklet syntax error) — the mic is
  // already open, so it must be released before rethrowing.
  const addModule = vi.fn().mockRejectedValue(new Error('addModule failed'));
  vi.stubGlobal('AudioContext', workletCtxClass(44100, addModule));
  vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode);

  const handle = startRecording({ sampleRate: 44100, channelCount: 1, durationS: 2 });
  await expect(handle.promise).rejects.toThrow(/Could not start audio capture/);
  expect(track.stop, 'the opened mic must be released when addModule rejects').toHaveBeenCalled();
});

test('startRecording releases the mic if AudioContext/node setup throws (C2)', async () => {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track], getAudioTracks: () => [{ getSettings: () => ({ channelCount: 1 }) }] };
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockResolvedValue(stream);

  // An AudioContext whose node construction throws (as Safari/large channel
  // counts realistically do) — the mic is already open at this point.
  class ThrowingAudioContext {
    sampleRate = 44100;
    destination = {};
    createMediaStreamSource() { return { connect: vi.fn(), disconnect: vi.fn(), channelCount: 1 }; }
    createScriptProcessor(): never { throw new Error('createScriptProcessor unsupported'); }
    close = vi.fn();
  }
  vi.stubGlobal('AudioContext', ThrowingAudioContext);

  const handle = startRecording({ sampleRate: 44100, channelCount: 1, durationS: 2 });
  await expect(handle.promise).rejects.toThrow(/Could not start audio capture/);
  // The mic opened by getUserMedia must be released, not left live.
  expect(track.stop, 'the opened mic must be released on setup failure').toHaveBeenCalled();
});
