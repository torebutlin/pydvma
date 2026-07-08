/**
 * Tests for the monitor store (oscilloscope state management).
 * Verifies: lifecycle, ring buffer, levels, pause, snapshot.
 */
import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createMonitorStore, maxWindowSFor } from '../../src/lib/stores/monitor';
import { createAcquireStore } from '../../src/lib/stores/acquire';
import { capabilities } from '../../src/lib/stores/stages';
import type { MonitorChunk, MonitorHandle } from '../../src/lib/audio/source';
import type { SourceProvider } from '../../src/lib/audio/provider';

// ---- Inject a fake provider (the Wave B provider seam) ----
// The monitor now drives `acquire.provider.startMonitor`; these tests inject
// a fake provider whose startMonitor is a spy, replacing the old
// vi.mock-of-source approach while keeping every assertion's intent.

let capturedOndata: ((chunk: MonitorChunk) => void) | null = null;
let capturedCfg: Record<string, unknown> | null = null;
const mockStop = vi.fn();

/** A fake provider whose startMonitor is a spy the tests can drive. */
function makeFakeProvider() {
  const startMonitor = vi.fn(
    async (cfg: Record<string, unknown>, ondata: (chunk: MonitorChunk) => void) => {
      capturedCfg = cfg;
      capturedOndata = ondata;
      return { stop: mockStop, fs: 44100, nChannels: 2 } as MonitorHandle;
    },
  );
  const provider: SourceProvider = {
    kind: 'webaudio',
    capabilities: async () => null,
    enumerateInputDevices: async () => [],
    startRecording: () => ({ promise: Promise.resolve() as never, cancel() {}, elapsed: () => 0 }),
    startMonitor: startMonitor as unknown as SourceProvider['startMonitor'],
  };
  return { provider, startMonitor };
}

/** Build a monitor store over a fresh acquire store + fake provider. */
function setup() {
  const { provider, startMonitor } = makeFakeProvider();
  const acq = createAcquireStore(provider);
  const mon = createMonitorStore(acq);
  return { mon, acq, provider, startMonitor };
}

beforeEach(() => {
  capturedOndata = null;
  capturedCfg = null;
  mockStop.mockClear();
  capabilities.set({ liveSource: false, fitEngine: false });
});
afterEach(() => vi.restoreAllMocks());

test('status starts idle', () => {
  const { mon } = setup();
  expect(get(mon.status)).toBe('idle');
});

test('start transitions to streaming and stop returns to idle', async () => {
  const { mon } = setup();
  await mon.start();
  expect(get(mon.status)).toBe('streaming');

  mon.stop();
  expect(get(mon.status)).toBe('idle');
  expect(mockStop).toHaveBeenCalled();
});

test('stop() during start does NOT revive the monitor and releases the stream (I2)', async () => {
  const { mon, startMonitor } = setup();
  // Defer this one startMonitor so we can stop() while it is still in flight.
  let resolveStart!: (h: MonitorHandle) => void;
  startMonitor.mockImplementationOnce(
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
  const { mon, startMonitor } = setup();
  let resolveStart!: (h: MonitorHandle) => void;
  startMonitor.mockImplementationOnce(
    () => new Promise<MonitorHandle>((res) => { resolveStart = res; }),
  );

  const p1 = mon.start();
  const p2 = mon.start();                // guarded by the synchronous 'starting' sentinel
  resolveStart({ stop: mockStop, fs: 44100, nChannels: 2 });
  await Promise.all([p1, p2]);

  expect(startMonitor).toHaveBeenCalledTimes(1);
  expect(get(mon.status)).toBe('streaming');
});

test('pause and resume toggle status', async () => {
  const { mon } = setup();
  await mon.start();

  mon.pause();
  expect(get(mon.status)).toBe('paused');

  mon.resume();
  expect(get(mon.status)).toBe('streaming');
});

test('togglePause alternates between streaming and paused', async () => {
  const { mon } = setup();
  await mon.start();

  mon.togglePause();
  expect(get(mon.status)).toBe('paused');

  mon.togglePause();
  expect(get(mon.status)).toBe('streaming');
});

test('ring buffer populates on audio data and snapshot returns chronological copy', async () => {
  const { mon } = setup();
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
  const { mon } = setup();
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
  const { mon } = setup();
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
  const { mon } = setup();
  const snap = mon.snapshot();
  expect(snap.channels).toHaveLength(0);
  expect(snap.fs).toBe(44100);
  expect(snap.rev).toBe(0);
});

test('stacked and autoscaleY default to false/true', () => {
  const { mon } = setup();
  expect(get(mon.stacked)).toBe(false);
  expect(get(mon.autoscaleY)).toBe(true);
});

// ---- round-2 osc settings ----

test('osc display settings have sensible defaults', () => {
  const { mon } = setup();
  expect(get(mon.windowS)).toBe(0.1);
  expect(get(mon.fftYLog)).toBe(true);   // dB by default
  expect(get(mon.fftXLog)).toBe(false);  // linear freq by default
  expect(get(mon.panes)).toEqual({ time: true, freq: true, levels: true });
  expect(get(mon.clipLatched)).toBe(false);
});

test('setWindow clamps and re-allocates the ring while streaming', async () => {
  const { mon } = setup();
  await mon.start();               // fs 44100 (from mock handle)
  const len01 = mon.ringLength;
  expect(len01).toBe(Math.ceil(44100 * 0.1));

  mon.setWindow(0.5);
  expect(get(mon.windowS)).toBe(0.5);
  expect(mon.ringLength).toBe(Math.ceil(44100 * 0.5));

  // Clamp: absurd values pin to the memory-safe max (round-5 item 8). At
  // 44.1 kHz × 2 ch the 64 MiB budget allows ~190 s, so the 30 s hard ceiling
  // wins.
  mon.setWindow(999);
  expect(get(mon.windowS)).toBe(30);
  expect(mon.ringLength).toBe(Math.ceil(44100 * 30));

  mon.stop();
});

// ── Memory-bounded view-time cap (round-5 item 8) ──────────────────────────
test('maxWindowSFor: typical fs/channels reach the 30 s ceiling', () => {
  // 48 kHz × 2 ch: 64 MiB / (48000·2·4) ≈ 174 s → capped to the 30 s ceiling.
  expect(maxWindowSFor(48000, 2)).toBe(30);
  expect(maxWindowSFor(44100, 1)).toBe(30);
});

test('maxWindowSFor: heavy fs/channels are bounded by the ~64 MiB ring budget', () => {
  // 96 kHz × 16 ch: 64 MiB / (96000·16·4) ≈ 10.9 s < 30 s ceiling.
  const s = maxWindowSFor(96000, 16);
  expect(s).toBeLessThan(30);
  const ringBytes = 96000 * 16 * s * 4;         // nCh·fs·seconds·Float32
  expect(ringBytes).toBeLessThanOrEqual(64 * 1024 * 1024 + 1);
  expect(s).toBeCloseTo((64 * 1024 * 1024) / (96000 * 16 * 4), 5);
});

test('maxWindowSFor: never drops below the floor', () => {
  // A pathological 192 kHz × 64 ch → tiny budget, but still ≥ the 0.02 s floor.
  expect(maxWindowSFor(192000, 64)).toBeGreaterThanOrEqual(0.02);
});

test('setWindow honours the memory budget at high channel counts', async () => {
  // Drive the fake handle to a heavy config by overriding acquire settings so
  // the ring realloc + clamp use the bounded max, not the 30 s ceiling.
  const { mon, acq } = setup();
  acq.patch({ sampleRate: 96000, channelCount: 16 });
  const cap = maxWindowSFor(96000, 16);
  mon.setWindow(30);                              // ask for the ceiling…
  expect(get(mon.windowS)).toBeCloseTo(cap, 6);   // …get the budgeted cap
});

test('clip flag latches at peak ≥ 0.95 and resets on demand', async () => {
  const { mon } = setup();
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
  const { mon } = setup();
  await mon.start();
  capturedOndata!({ data: new Float32Array([1, 1]), nSamples: 1, nChannels: 2, fs: 44100 });
  expect(get(mon.clipLatched)).toBe(true);
  mon.stop();
  await mon.start();
  expect(get(mon.clipLatched)).toBe(false);
  mon.stop();
});

test('togglePane flips a single pane', () => {
  const { mon } = setup();
  mon.togglePane('freq');
  expect(get(mon.panes)).toEqual({ time: true, freq: false, levels: true });
  mon.togglePane('freq');
  expect(get(mon.panes).freq).toBe(true);
});

// ---- round-3 FFT / PSD settings ----

test('round-3 fft settings have sensible defaults', () => {
  const { mon } = setup();
  expect(get(mon.fftFMax)).toBe(null);          // full / Nyquist by default
  expect(get(mon.spectrumMode)).toBe('instant');
  expect(get(mon.psdSegments)).toBe(4);
  expect(get(mon.psdSmoothing)).toBe(0);
});

test('setFftFMax accepts a value, clamps below the floor, and null = full', () => {
  const { mon } = setup();
  mon.setFftFMax(2000);
  expect(get(mon.fftFMax)).toBe(2000);
  mon.setFftFMax(1);                            // below MIN_FMAX_HZ (10) → clamped
  expect(get(mon.fftFMax)).toBe(10);
  mon.setFftFMax(null);
  expect(get(mon.fftFMax)).toBe(null);
  mon.setFftFMax(Number.NaN);                   // non-finite → full
  expect(get(mon.fftFMax)).toBe(null);
});

test('fft frequency band defaults to full span (fmin/fmax null, mode full)', () => {
  const { mon } = setup();
  expect(get(mon.fftFMin)).toBe(null);
  expect(get(mon.fftFMax)).toBe(null);
  expect(get(mon.fftFreqMode)).toBe('full');
});

test('setFftFMin accepts a value, clamps below zero, and null = natural edge', () => {
  const { mon } = setup();
  mon.setFftFMin(500);
  expect(get(mon.fftFMin)).toBe(500);
  mon.setFftFMin(-10);                          // negative → clamped to 0
  expect(get(mon.fftFMin)).toBe(0);
  mon.setFftFMin(null);
  expect(get(mon.fftFMin)).toBe(null);
  mon.setFftFMin(Number.NaN);                   // non-finite → natural edge
  expect(get(mon.fftFMin)).toBe(null);
});

test('setFftFreqMode: range keeps the band, full resets fmin/fmax to the edges', () => {
  const { mon } = setup();
  mon.setFftFreqMode('range');
  expect(get(mon.fftFreqMode)).toBe('range');
  mon.setFftFMin(200);
  mon.setFftFMax(2000);
  expect(get(mon.fftFMin)).toBe(200);
  expect(get(mon.fftFMax)).toBe(2000);
  // Switching back to full restores the whole span (both null).
  mon.setFftFreqMode('full');
  expect(get(mon.fftFreqMode)).toBe('full');
  expect(get(mon.fftFMin)).toBe(null);
  expect(get(mon.fftFMax)).toBe(null);
});

test('setSpectrumMode toggles between instant and psd (invalid → instant)', () => {
  const { mon } = setup();
  mon.setSpectrumMode('psd');
  expect(get(mon.spectrumMode)).toBe('psd');
  mon.setSpectrumMode('instant');
  expect(get(mon.spectrumMode)).toBe('instant');
  // Anything not 'psd' falls back to 'instant'.
  mon.setSpectrumMode('bogus' as unknown as 'instant');
  expect(get(mon.spectrumMode)).toBe('instant');
});

test('setPsdSegments clamps to an integer ≥ 1', () => {
  const { mon } = setup();
  mon.setPsdSegments(8);
  expect(get(mon.psdSegments)).toBe(8);
  mon.setPsdSegments(2.9);
  expect(get(mon.psdSegments)).toBe(2);         // floored
  mon.setPsdSegments(0);
  expect(get(mon.psdSegments)).toBe(1);         // min 1
  mon.setPsdSegments(-5);
  expect(get(mon.psdSegments)).toBe(1);
});

test('setPsdSmoothing clamps to [0, 0.95]', () => {
  const { mon } = setup();
  mon.setPsdSmoothing(0.5);
  expect(get(mon.psdSmoothing)).toBe(0.5);
  mon.setPsdSmoothing(2);                        // over the cap
  expect(get(mon.psdSmoothing)).toBe(0.95);
  mon.setPsdSmoothing(-1);                       // below 0
  expect(get(mon.psdSmoothing)).toBe(0);
  mon.setPsdSmoothing(Number.NaN);
  expect(get(mon.psdSmoothing)).toBe(0);
});

test('monitor passes the latency hint through to startMonitor', async () => {
  const { mon, acq } = setup();
  await mon.start();
  expect(capturedCfg!.latency).toBeUndefined();  // no hint by default
  mon.stop();

  acq.patch({ latency: 0.02 });
  await mon.start();
  expect(capturedCfg!.latency).toBe(0.02);
  mon.stop();
});

test('monitor passes the getUserMedia DSP constraints through to startMonitor', async () => {
  const { mon, acq } = setup();
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
  const { mon } = setup();
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
