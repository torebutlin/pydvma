/**
 * Tests for the continuous audio monitor (startMonitor) in source.ts.
 * Verifies: stream lifecycle, data callback shape, permission error,
 * stop cleanup.
 */
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { startMonitor, type MonitorCallback, type MonitorChunk } from '../../src/lib/audio/source';

// ---- Mock navigator.mediaDevices ----

let mockProcessorCallback: ((ev: unknown) => void) | null = null;
const mockTrack = { stop: vi.fn() };
const mockStream = {
  getTracks: () => [mockTrack],
  getAudioTracks: () => [{ getSettings: () => ({ channelCount: 2 }) }],
};
const mockProcessor = {
  connect: vi.fn(),
  disconnect: vi.fn(),
  set onaudioprocess(fn: ((ev: unknown) => void) | null) { mockProcessorCallback = fn; },
  get onaudioprocess() { return mockProcessorCallback; },
};
const mockSource = { connect: vi.fn(), disconnect: vi.fn(), channelCount: 2 };

class MockAudioContext {
  sampleRate = 44100;
  destination = {};
  createMediaStreamSource() { return mockSource; }
  createScriptProcessor() { return mockProcessor; }
  close = vi.fn();
}

// ---- worklet-path (primary) mocks ----
// The default MockAudioContext above has NO `audioWorklet`, so the existing
// tests exercise the ScriptProcessorNode FALLBACK.  These mocks add a working
// AudioWorklet surface so the primary path can be driven directly.

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
/** An AudioContext class whose `audioWorklet.addModule` uses the given fn. */
function workletCtxClass(addModule: ReturnType<typeof vi.fn>) {
  return class MockWorkletAudioContext {
    sampleRate = 44100;
    destination = {};
    audioWorklet = { addModule };
    createMediaStreamSource() { return mockSource; }
    createScriptProcessor() { return mockProcessor; }
    close = vi.fn();
  };
}

beforeEach(() => {
  mockProcessorCallback = null;
  lastWorkletNode = null;
  mockTrack.stop.mockClear();
  mockProcessor.connect.mockClear();
  mockProcessor.disconnect.mockClear();
  mockSource.connect.mockClear();
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue([]),
      getUserMedia: vi.fn().mockResolvedValue(mockStream),
    },
  });
  vi.stubGlobal('AudioContext', MockAudioContext);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test('startMonitor opens stream and calls ondata with correct shape', async () => {
  const chunks: MonitorChunk[] = [];
  const ondata: MonitorCallback = (chunk) => chunks.push(chunk);

  const handle = await startMonitor(
    { sampleRate: 44100, channelCount: 2 },
    ondata,
  );

  expect(handle.fs).toBe(44100);
  expect(handle.nChannels).toBe(2);

  // Simulate an audio callback.
  const N = 512;
  const chData = new Float32Array(N);
  for (let i = 0; i < N; i++) chData[i] = Math.sin(i);

  if (mockProcessorCallback) {
    mockProcessorCallback({
      inputBuffer: {
        length: N,
        getChannelData: () => chData,
      },
    });
  }

  expect(chunks).toHaveLength(1);
  expect(chunks[0].nSamples).toBe(N);
  expect(chunks[0].nChannels).toBe(2);
  expect(chunks[0].fs).toBe(44100);
  // Data is interleaved (N, 2) so length = N * 2.
  expect(chunks[0].data.length).toBe(N * 2);

  handle.stop();
});

test('startMonitor.stop releases stream and audio context', async () => {
  const ondata = vi.fn();
  const handle = await startMonitor(
    { sampleRate: 44100, channelCount: 1 },
    ondata,
  );

  handle.stop();

  expect(mockTrack.stop).toHaveBeenCalled();
  expect(mockProcessor.disconnect).toHaveBeenCalled();

  // After stop, callbacks should be no-ops.
  if (mockProcessorCallback) {
    mockProcessorCallback({
      inputBuffer: {
        length: 256,
        getChannelData: () => new Float32Array(256),
      },
    });
  }
  // ondata should NOT have been called after stop.
  expect(ondata).not.toHaveBeenCalled();
});

test('startMonitor requests raw-measurement constraints by default (echo/noise/agc OFF)', async () => {
  const gum = navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>;
  const handle = await startMonitor({ sampleRate: 44100, channelCount: 1 }, vi.fn());
  expect(gum).toHaveBeenCalledWith(expect.objectContaining({
    audio: expect.objectContaining({
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    }),
  }));
  handle.stop();
});

test('startMonitor forwards explicit DSP constraint overrides to getUserMedia', async () => {
  const gum = navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>;
  const handle = await startMonitor(
    { sampleRate: 44100, channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    vi.fn(),
  );
  expect(gum).toHaveBeenCalledWith(expect.objectContaining({
    audio: expect.objectContaining({
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    }),
  }));
  handle.stop();
});

test('startMonitor rejects on permission denied', async () => {
  const err = new DOMException('Permission denied', 'NotAllowedError');
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockRejectedValue(err);

  await expect(
    startMonitor({ sampleRate: 44100, channelCount: 1 }, vi.fn()),
  ).rejects.toThrow('Microphone permission denied');
});

test('startMonitor stop is idempotent', async () => {
  const handle = await startMonitor(
    { sampleRate: 44100, channelCount: 1 },
    vi.fn(),
  );

  handle.stop();
  // Second stop should not throw.
  expect(() => handle.stop()).not.toThrow();
});

// ---- AudioWorklet primary path ----

test('startMonitor uses the AudioWorklet path when available (2048 cadence, no ScriptProcessor)', async () => {
  const addModule = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal('AudioContext', workletCtxClass(addModule));
  vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode);

  const chunks: MonitorChunk[] = [];
  const handle = await startMonitor(
    { sampleRate: 44100, channelCount: 2 },
    (c) => chunks.push(c),
  );

  expect(handle.fs).toBe(44100);
  expect(handle.nChannels).toBe(2);
  expect(addModule).toHaveBeenCalledTimes(1);
  expect(lastWorkletNode).not.toBeNull();
  // Monitor cadence == old ScriptProcessorNode BUFFER_SIZE (2048); the
  // interleave width == the actual channel count.
  expect(lastWorkletNode!.processorOptions?.chunkFrames).toBe(2048);
  expect(lastWorkletNode!.processorOptions?.nChannels).toBe(2);
  // Wired source→node→destination; the ScriptProcessor fallback was NOT used.
  expect(lastWorkletNode!.connect).toHaveBeenCalled();
  expect(mockProcessor.connect).not.toHaveBeenCalled();

  // The worklet posts an interleaved (N, 2) chunk over its port; source.ts
  // stamps fs and forwards it unchanged.
  const N = 2048;
  const data = new Float32Array(N * 2);
  for (let i = 0; i < N * 2; i++) data[i] = i;
  lastWorkletNode!.port.onmessage!({ data: { data, nSamples: N, nChannels: 2 } });

  expect(chunks).toHaveLength(1);
  expect(chunks[0].nSamples).toBe(N);
  expect(chunks[0].nChannels).toBe(2);
  expect(chunks[0].fs).toBe(44100);
  expect(chunks[0].data.length).toBe(N * 2);
  expect(chunks[0].data).toBe(data);

  handle.stop();
});

test('startMonitor worklet path: stop disconnects the node, releases the stream, and post-stop messages are no-ops', async () => {
  vi.stubGlobal('AudioContext', workletCtxClass(vi.fn().mockResolvedValue(undefined)));
  vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode);

  const ondata = vi.fn();
  const handle = await startMonitor({ sampleRate: 44100, channelCount: 1 }, ondata);

  handle.stop();
  expect(lastWorkletNode!.disconnect).toHaveBeenCalled();
  expect(mockSource.disconnect).toHaveBeenCalled();
  expect(mockTrack.stop).toHaveBeenCalled();

  // A late chunk arriving after stop must not reach the callback.
  lastWorkletNode!.port.onmessage!({
    data: { data: new Float32Array(2), nSamples: 2, nChannels: 1 },
  });
  expect(ondata).not.toHaveBeenCalled();
});

test('startMonitor releases the mic if the worklet module fails to load (C2)', async () => {
  const addModule = vi.fn().mockRejectedValue(new Error('addModule failed'));
  vi.stubGlobal('AudioContext', workletCtxClass(addModule));
  vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode);

  await expect(
    startMonitor({ sampleRate: 44100, channelCount: 1 }, vi.fn()),
  ).rejects.toThrow('Could not start audio monitor');
  // getUserMedia already opened the mic; a rejected addModule must release it.
  expect(mockTrack.stop, 'the opened mic must be released when addModule rejects').toHaveBeenCalled();
});

test('startMonitor falls back to ScriptProcessorNode when audioWorklet is unavailable', async () => {
  // Default MockAudioContext (no `audioWorklet`) + no AudioWorkletNode global.
  const chunks: MonitorChunk[] = [];
  const handle = await startMonitor(
    { sampleRate: 44100, channelCount: 1 },
    (c) => chunks.push(c),
  );

  // The fallback wires the ScriptProcessor and never constructs a worklet node.
  expect(mockProcessor.connect).toHaveBeenCalled();
  expect(lastWorkletNode).toBeNull();

  const N = 256;
  mockProcessorCallback?.({
    inputBuffer: { length: N, getChannelData: () => new Float32Array(N) },
  });
  expect(chunks).toHaveLength(1);
  expect(chunks[0].nSamples).toBe(N);

  handle.stop();
});
