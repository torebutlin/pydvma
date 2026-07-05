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

beforeEach(() => {
  mockProcessorCallback = null;
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
afterEach(() => vi.restoreAllMocks());

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
