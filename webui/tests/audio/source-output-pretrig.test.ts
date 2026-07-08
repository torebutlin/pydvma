/**
 * Tests for the Web Audio output-stimulus + pretrigger extensions to
 * `startRecording` (src/lib/audio/source.ts), round-5 item 10.  Drives the
 * AudioWorklet capture path with a mocked AudioContext that also supports the
 * output graph (createBuffer / createBufferSource / setSinkId), and verifies:
 * - an armed capture waits for a threshold crossing, surfaces armed→triggered,
 *   and returns a full-length window with the crossing at index pretrigSamples;
 * - the timeout fallback surfaces armed→timeout and still returns a full set;
 * - an output stimulus builds, starts in sync, and is stopped on completion,
 *   with the DSP flags forced OFF (echo cancellation would cancel the output).
 */
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { startRecording, type RecordConfig, type CaptureStatusEvent } from '../../src/lib/audio/source';

// ---- mocks ----

let lastWorkletNode: MockAudioWorkletNode | null = null;
class MockAudioWorkletNode {
  port = { onmessage: null as ((ev: unknown) => void) | null, close: vi.fn() };
  connect = vi.fn();
  disconnect = vi.fn();
  constructor() { lastWorkletNode = this; }
}

let lastBufferSource: MockBufferSource | null = null;
class MockBufferSource {
  buffer: unknown = null;
  connect = vi.fn();
  disconnect = vi.fn();
  start = vi.fn();
  stop = vi.fn();
  constructor() { lastBufferSource = this; }
}

interface MockCtxOpts { fs: number; withSinkId?: boolean; }

function makeMockCtx(opts: MockCtxOpts) {
  const addModule = vi.fn().mockResolvedValue(undefined);
  const setSinkId = opts.withSinkId ? vi.fn().mockResolvedValue(undefined) : undefined;
  const created: MockAudioContext[] = [];
  class MockAudioContext {
    sampleRate = opts.fs;
    destination = {};
    audioWorklet = { addModule };
    setSinkId = setSinkId;
    createMediaStreamSource() { return { connect: vi.fn(), disconnect: vi.fn(), channelCount: 1 }; }
    createBuffer(channels: number, length: number) {
      const data = Array.from({ length: channels }, () => new Float32Array(length));
      return { getChannelData: (ch: number) => data[ch], length, numberOfChannels: channels };
    }
    createBufferSource() { return new MockBufferSource(); }
    close = vi.fn();
    constructor() { created.push(this); }
  }
  return { MockAudioContext, addModule, setSinkId, created };
}

let lastConstraints: MediaTrackConstraints | undefined;
function mockGetUserMedia(track = { stop: vi.fn() }) {
  const stream = { getTracks: () => [track], getAudioTracks: () => [{ getSettings: () => ({ channelCount: 1 }) }] };
  const gum = vi.fn().mockImplementation((c: MediaStreamConstraints) => {
    lastConstraints = c.audio as MediaTrackConstraints;
    return Promise.resolve(stream);
  });
  return { track, stream, gum };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Deliver interleaved mono chunks (value per global sample index) over the port. */
async function deliverMono(total: number, chunk: number, val: (i: number) => number): Promise<void> {
  let delivered = 0;
  while (delivered < total && lastWorkletNode?.port.onmessage) {
    const m = Math.min(chunk, total - delivered);
    const buf = new Float32Array(m);
    for (let i = 0; i < m; i++) buf[i] = val(delivered + i);
    lastWorkletNode.port.onmessage({ data: { data: buf, nSamples: m, nChannels: 1 } });
    delivered += m;
    await Promise.resolve();
  }
}

beforeEach(() => {
  lastWorkletNode = null;
  lastBufferSource = null;
  lastConstraints = undefined;
  vi.stubGlobal('AudioWorkletNode', MockAudioWorkletNode);
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(), enumerateDevices: vi.fn() } });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

// ---- armed capture ----

test('armed capture waits for a crossing, surfaces armed→triggered, crossing at index pretrigSamples', async () => {
  const FS = 8000, DUR = 0.05, TOTAL = Math.ceil(FS * DUR); // 400
  const { track, gum } = mockGetUserMedia();
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>) = gum;
  vi.stubGlobal('AudioContext', makeMockCtx({ fs: FS }).MockAudioContext);

  const events: CaptureStatusEvent[] = [];
  const cfg: RecordConfig = {
    sampleRate: FS, channelCount: 1, durationS: DUR,
    pretrig: { channel: 0, threshold: 0.5, pretrigSamples: 10, timeoutS: 5, onStatus: (e) => events.push(e) },
  };
  const handle = startRecording(cfg);
  await sleep(10); // getUserMedia + addModule wiring

  // 50 pre-samples below threshold (fills the pretrig ring), a crossing (1.0),
  // then enough post-samples to complete the 400-sample window.
  const crossAt = 50;
  await deliverMono(600, 64, (i) => (i === crossAt ? 1.0 : 0.1));

  const rec = await handle.promise;
  expect(rec.nSamples).toBe(TOTAL);
  expect(rec.data.length).toBe(TOTAL);
  expect(rec.data[10]).toBeCloseTo(1.0, 6);      // crossing at window index pretrigSamples
  expect(events).toContain('armed');
  expect(events).toContain('triggered');
  expect(events).not.toContain('timeout');
  expect(track.stop).toHaveBeenCalled();          // mic released
});

test('armed capture times out (no crossing) → armed→timeout, still returns a full set', async () => {
  const FS = 8000, DUR = 0.05, TOTAL = Math.ceil(FS * DUR);
  const { gum } = mockGetUserMedia();
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>) = gum;
  vi.stubGlobal('AudioContext', makeMockCtx({ fs: FS }).MockAudioContext);

  const events: CaptureStatusEvent[] = [];
  const cfg: RecordConfig = {
    sampleRate: FS, channelCount: 1, durationS: DUR,
    pretrig: { channel: 0, threshold: 100, pretrigSamples: 10, timeoutS: 0.02, onStatus: (e) => events.push(e) },
  };
  const handle = startRecording(cfg);
  await sleep(10);

  // Deliver some pre-samples (fills the ring), let the timeout fire, then the rest.
  await deliverMono(40, 20, () => 0.1);
  await sleep(40);                       // > timeoutS → forceTrigger fires
  await deliverMono(600, 64, () => 0.1); // completes the window post-force

  const rec = await handle.promise;
  expect(rec.nSamples).toBe(TOTAL);
  expect(events).toContain('armed');
  expect(events).toContain('timeout');
  expect(events).not.toContain('triggered');
});

// ---- output stimulus ----

test('an output stimulus builds, starts in sync, forces DSP flags off, and stops on completion', async () => {
  const FS = 8000, DUR = 0.05, TOTAL = Math.ceil(FS * DUR);
  const { gum } = mockGetUserMedia();
  (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>) = gum;
  const { MockAudioContext } = makeMockCtx({ fs: FS });
  vi.stubGlobal('AudioContext', MockAudioContext);

  const cfg: RecordConfig = {
    sampleRate: FS, channelCount: 1, durationS: DUR,
    echoCancellation: true, // user asked for EC — but output must force it off
    output: { type: 'sweep', amp: 0.3, f1: 10, f2: 500 },
  };
  const handle = startRecording(cfg);
  await sleep(10);

  // The stimulus node must have been built and started.
  expect(lastBufferSource).not.toBeNull();
  expect(lastBufferSource!.start).toHaveBeenCalled();
  expect(lastBufferSource!.connect).toHaveBeenCalled();
  // DSP flags forced off when an output plays (echo cancellation would cancel it).
  expect(lastConstraints?.echoCancellation).toBe(false);
  expect(lastConstraints?.noiseSuppression).toBe(false);
  expect(lastConstraints?.autoGainControl).toBe(false);

  // Complete the capture; the output node is stopped/disconnected on cleanup.
  await deliverMono(TOTAL, 128, (i) => Math.sin(i));
  const rec = await handle.promise;
  expect(rec.nSamples).toBe(TOTAL);
  expect(lastBufferSource!.stop).toHaveBeenCalled();
});

test('setSinkId routes to a chosen output device when supported, and is skipped otherwise', async () => {
  const FS = 8000, DUR = 0.02;
  // With setSinkId (Chromium): the chosen device is applied.
  {
    const { gum } = mockGetUserMedia();
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>) = gum;
    const { MockAudioContext, setSinkId } = makeMockCtx({ fs: FS, withSinkId: true });
    vi.stubGlobal('AudioContext', MockAudioContext);
    const handle = startRecording({
      sampleRate: FS, channelCount: 1, durationS: DUR,
      output: { type: 'uniform', amp: 0.2, f1: 100, f2: 800, deviceId: 'spk-42' },
    });
    await sleep(10);
    expect(setSinkId).toHaveBeenCalledWith('spk-42');
    handle.cancel();
    await deliverMono(1, 1, () => 0); // let the cancel path run
    await handle.promise.catch(() => {});
  }
  // Without setSinkId (Safari/Firefox): no throw, output still built.
  {
    const { gum } = mockGetUserMedia();
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>) = gum;
    const { MockAudioContext } = makeMockCtx({ fs: FS, withSinkId: false });
    vi.stubGlobal('AudioContext', MockAudioContext);
    const handle = startRecording({
      sampleRate: FS, channelCount: 1, durationS: DUR,
      output: { type: 'uniform', amp: 0.2, f1: 100, f2: 800, deviceId: 'spk-42' },
    });
    await sleep(10);
    expect(lastBufferSource).not.toBeNull(); // built, played to default device
    handle.cancel();
    await deliverMono(1, 1, () => 0);
    await handle.promise.catch(() => {});
  }
});
