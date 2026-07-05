/**
 * Tests for the monitor store (oscilloscope state management).
 * Verifies: lifecycle, ring buffer, levels, pause, snapshot.
 */
import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createMonitorStore } from '../../src/lib/stores/monitor';
import { createAcquireStore } from '../../src/lib/stores/acquire';
import { capabilities } from '../../src/lib/stores/stages';
import type { MonitorChunk } from '../../src/lib/audio/source';

// ---- Mock the audio source layer ----

let capturedOndata: ((chunk: MonitorChunk) => void) | null = null;
const mockStop = vi.fn();

vi.mock('../../src/lib/audio/source', async () => {
  const actual = await vi.importActual<typeof import('../../src/lib/audio/source')>('../../src/lib/audio/source');
  return {
    ...actual,
    startMonitor: vi.fn(async (_cfg: unknown, ondata: (chunk: MonitorChunk) => void) => {
      capturedOndata = ondata;
      return { stop: mockStop, fs: 44100, nChannels: 2 };
    }),
  };
});

beforeEach(() => {
  capturedOndata = null;
  mockStop.mockClear();
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
