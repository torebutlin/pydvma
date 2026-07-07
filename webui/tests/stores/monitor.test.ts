/**
 * Tests for the monitor store (oscilloscope state management).
 * Verifies: lifecycle, ring buffer, levels, pause, snapshot.
 */
import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createMonitorStore } from '../../src/lib/stores/monitor';
import { createAcquireStore } from '../../src/lib/stores/acquire';
import { capabilities } from '../../src/lib/stores/stages';
import { startMonitor, type MonitorChunk, type MonitorHandle } from '../../src/lib/audio/source';

// ---- Mock the audio source layer ----

let capturedOndata: ((chunk: MonitorChunk) => void) | null = null;
let capturedCfg: Record<string, unknown> | null = null;
const mockStop = vi.fn();

vi.mock('../../src/lib/audio/source', async () => {
  const actual = await vi.importActual<typeof import('../../src/lib/audio/source')>('../../src/lib/audio/source');
  return {
    ...actual,
    startMonitor: vi.fn(async (cfg: Record<string, unknown>, ondata: (chunk: MonitorChunk) => void) => {
      capturedCfg = cfg;
      capturedOndata = ondata;
      return { stop: mockStop, fs: 44100, nChannels: 2 };
    }),
  };
});

beforeEach(() => {
  capturedOndata = null;
  capturedCfg = null;
  mockStop.mockClear();
  vi.mocked(startMonitor).mockClear();   // reset call count per test (I3 asserts it)
  capabilities.set({ liveSource: false, fitEngine: false });
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue([]),
      getUserMedia: vi.fn(),
    },
  });
});
afterEach(() => vi.restoreAllMocks());

function makeAcquire() {
  return createAcquireStore();
}

test('status starts idle', () => {
  const mon = createMonitorStore(makeAcquire());
  expect(get(mon.status)).toBe('idle');
});

test('start transitions to streaming and stop returns to idle', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();
  expect(get(mon.status)).toBe('streaming');

  mon.stop();
  expect(get(mon.status)).toBe('idle');
  expect(mockStop).toHaveBeenCalled();
});

test('stop() during start does NOT revive the monitor and releases the stream (I2)', async () => {
  const mon = createMonitorStore(makeAcquire());
  // Defer this one startMonitor so we can stop() while it is still in flight.
  let resolveStart!: (h: MonitorHandle) => void;
  vi.mocked(startMonitor).mockImplementationOnce(
    () => new Promise<MonitorHandle>((res) => { resolveStart = res; }),
  );

  const p = mon.start();                 // 'starting', awaiting our deferred promise
  mon.stop();                            // user cancels before it resolves
  expect(get(mon.status)).toBe('idle');
  resolveStart({ stop: mockStop, fs: 44100, nChannels: 2 });  // now it resolves
  await p;

  // The cancelled monitor must NOT come back to life, and the stream that was
  // opened after the cancel must be torn down (not orphaned).
  expect(get(mon.status)).toBe('idle');
  expect(mockStop).toHaveBeenCalled();
});

test('double start() opens only one monitor (I3)', async () => {
  const mon = createMonitorStore(makeAcquire());
  let resolveStart!: (h: MonitorHandle) => void;
  vi.mocked(startMonitor).mockImplementationOnce(
    () => new Promise<MonitorHandle>((res) => { resolveStart = res; }),
  );

  const p1 = mon.start();
  const p2 = mon.start();                // guarded by the synchronous 'starting' sentinel
  resolveStart({ stop: mockStop, fs: 44100, nChannels: 2 });
  await Promise.all([p1, p2]);

  expect(vi.mocked(startMonitor)).toHaveBeenCalledTimes(1);
  expect(get(mon.status)).toBe('streaming');
});

test('pause and resume toggle status', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();

  mon.pause();
  expect(get(mon.status)).toBe('paused');

  mon.resume();
  expect(get(mon.status)).toBe('streaming');
});

test('togglePause alternates between streaming and paused', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();

  mon.togglePause();
  expect(get(mon.status)).toBe('paused');

  mon.togglePause();
  expect(get(mon.status)).toBe('streaming');
});

test('ring buffer populates on audio data and snapshot returns chronological copy', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();

  // Feed a chunk of data (2 channels, 100 samples).
  const chunk: MonitorChunk = {
    data: new Float32Array(200),
    nSamples: 100,
    nChannels: 2,
    fs: 44100,
  };
  // Fill with identifiable values.
  for (let i = 0; i < 100; i++) {
    chunk.data[i * 2 + 0] = i;       // ch0
    chunk.data[i * 2 + 1] = i + 100; // ch1
  }
  capturedOndata!(chunk);

  const snap = mon.snapshot();
  expect(snap.channels).toHaveLength(2);
  expect(snap.fs).toBe(44100);
  expect(snap.rev).toBeGreaterThan(0);
  // The ring buffer is larger than 100 samples, so the first 100
  // entries (after the zero-filled prefix) should contain our data.
  // The snapshot is in chronological order: oldest → newest.
  const ch0 = snap.channels[0];
  // The tail of ch0 should have our values 0..99.
  const tail = ch0.subarray(ch0.length - 100);
  expect(tail[0]).toBe(0);
  expect(tail[99]).toBe(99);

  mon.stop();
});

test('levels update on each audio chunk', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();

  // A sine wave on ch0, silence on ch1.
  const N = 200;
  const chunk: MonitorChunk = {
    data: new Float32Array(N * 2),
    nSamples: N,
    nChannels: 2,
    fs: 44100,
  };
  for (let i = 0; i < N; i++) {
    chunk.data[i * 2 + 0] = Math.sin(2 * Math.PI * 440 * i / 44100);
    chunk.data[i * 2 + 1] = 0;
  }
  capturedOndata!(chunk);

  const lvls = get(mon.levels);
  expect(lvls).toHaveLength(2);
  // ch0 has non-zero peak and RMS.
  expect(lvls[0].peak).toBeGreaterThan(0);
  expect(lvls[0].rms).toBeGreaterThan(0);
  // ch1 is all zeros.
  expect(lvls[1].peak).toBe(0);
  expect(lvls[1].rms).toBe(0);

  mon.stop();
});

test('paused monitor still updates levels but does not advance ring revision', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();

  // Feed one chunk to get a baseline revision.
  const chunk: MonitorChunk = {
    data: new Float32Array(100),
    nSamples: 50,
    nChannels: 2,
    fs: 44100,
  };
  capturedOndata!(chunk);
  const rev1 = mon.snapshot().rev;

  // Pause.
  mon.pause();

  // Feed another chunk.
  for (let i = 0; i < 100; i++) chunk.data[i] = 0.5;
  capturedOndata!(chunk);

  // Levels should update even while paused.
  const lvls = get(mon.levels);
  expect(lvls[0].peak).toBeGreaterThan(0);

  // But the ring revision should NOT have advanced.
  expect(mon.snapshot().rev).toBe(rev1);

  mon.stop();
});

test('snapshot returns empty channels when not started', () => {
  const mon = createMonitorStore(makeAcquire());
  const snap = mon.snapshot();
  expect(snap.channels).toHaveLength(0);
  expect(snap.fs).toBe(44100);
  expect(snap.rev).toBe(0);
});

test('stacked and autoscaleY default to false/true', () => {
  const mon = createMonitorStore(makeAcquire());
  expect(get(mon.stacked)).toBe(false);
  expect(get(mon.autoscaleY)).toBe(true);
});

// ---- round-2 osc settings ----

test('osc display settings have sensible defaults', () => {
  const mon = createMonitorStore(makeAcquire());
  expect(get(mon.windowS)).toBe(0.1);
  expect(get(mon.fftYLog)).toBe(true);   // dB by default
  expect(get(mon.fftXLog)).toBe(false);  // linear freq by default
  expect(get(mon.panes)).toEqual({ time: true, freq: true, levels: true });
  expect(get(mon.clipLatched)).toBe(false);
});

test('setWindow clamps and re-allocates the ring while streaming', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();               // fs 44100 (from mock handle)
  const len01 = mon.ringLength;
  expect(len01).toBe(Math.ceil(44100 * 0.1));

  mon.setWindow(0.5);
  expect(get(mon.windowS)).toBe(0.5);
  expect(mon.ringLength).toBe(Math.ceil(44100 * 0.5));

  // Clamp: absurd values are pinned to [0.02, 5] s.
  mon.setWindow(999);
  expect(get(mon.windowS)).toBe(5);
  expect(mon.ringLength).toBe(Math.ceil(44100 * 5));

  mon.stop();
});

test('clip flag latches at peak ≥ 0.95 and resets on demand', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();
  expect(get(mon.clipLatched)).toBe(false);

  // A hot chunk (peak 0.99) trips the latch.
  const hot: MonitorChunk = { data: new Float32Array([0.99, 0.1]), nSamples: 1, nChannels: 2, fs: 44100 };
  capturedOndata!(hot);
  expect(get(mon.clipLatched)).toBe(true);

  // A quiet chunk does NOT clear it (it latches).
  const quiet: MonitorChunk = { data: new Float32Array([0.1, 0.1]), nSamples: 1, nChannels: 2, fs: 44100 };
  capturedOndata!(quiet);
  expect(get(mon.clipLatched)).toBe(true);

  // Explicit reset clears it.
  mon.resetClip();
  expect(get(mon.clipLatched)).toBe(false);
  mon.stop();
});

test('start() resets a previously latched clip flag', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();
  capturedOndata!({ data: new Float32Array([1, 1]), nSamples: 1, nChannels: 2, fs: 44100 });
  expect(get(mon.clipLatched)).toBe(true);
  mon.stop();
  await mon.start();
  expect(get(mon.clipLatched)).toBe(false);
  mon.stop();
});

test('togglePane flips a single pane', () => {
  const mon = createMonitorStore(makeAcquire());
  mon.togglePane('freq');
  expect(get(mon.panes)).toEqual({ time: true, freq: false, levels: true });
  mon.togglePane('freq');
  expect(get(mon.panes).freq).toBe(true);
});

test('monitor passes the getUserMedia DSP constraints through to startMonitor', async () => {
  const acq = makeAcquire();
  const mon = createMonitorStore(acq);
  await mon.start();
  // Defaults: all three off (raw measurement).
  expect(capturedCfg).toMatchObject({
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false,
  });
  mon.stop();

  // A user override reaches the source layer too.
  acq.patch({ echoCancellation: true });
  await mon.start();
  expect(capturedCfg!.echoCancellation).toBe(true);
  mon.stop();
});

test('lifecycle contract: settings changes do NOT stop the monitor (only stop() idles it)', async () => {
  const mon = createMonitorStore(makeAcquire());
  await mon.start();
  expect(get(mon.status)).toBe('streaming');

  // Changing display settings / window must not tear the monitor down —
  // the round-2 redesign replaced the auto-stop-on-stage-change behaviour
  // with explicit user stop only.
  mon.setWindow(0.2);
  mon.stacked.set(true);
  mon.togglePane('levels');
  expect(get(mon.status)).toBe('streaming');
  expect(mockStop).not.toHaveBeenCalled();

  mon.stop();
  expect(get(mon.status)).toBe('idle');
  expect(mockStop).toHaveBeenCalled();
});
