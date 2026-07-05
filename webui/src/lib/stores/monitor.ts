/**
 * Oscilloscope / monitor store (Plan 2 — Live tab).
 *
 * Manages the real-time audio monitor lifecycle: start/stop streaming,
 * a ring buffer of recent samples for canvas rendering, per-channel
 * peak/RMS level metering, pause toggle, and display options (stacked
 * traces, autoscale).
 *
 * The monitor uses the continuous `startMonitor` API from the audio
 * source layer (distinct from `startRecording` which accumulates a
 * fixed-duration capture).  The ring buffer holds a configurable
 * window of history (default ~100 ms) — enough to render a smooth
 * oscilloscope trace at 30–60 fps without storing megabytes.
 *
 * Created once at the app root and threaded to LiveCard.
 */
import { writable, get } from 'svelte/store';
import { startMonitor, type MonitorHandle, type MonitorCallback } from '../audio/source';
import type { AcquireStore } from './acquire';

// ---- types ----

export type MonitorStatus = 'idle' | 'starting' | 'streaming' | 'paused' | 'error';

export interface ChannelLevel {
  peak: number;   // max |sample| over the current callback
  rms: number;    // RMS over the current callback
}

export type MonitorStore = ReturnType<typeof createMonitorStore>;

// ---- constants ----

/** Default ring buffer window in seconds.  ~100 ms at 44.1 kHz = 4410 samples. */
const DEFAULT_WINDOW_S = 0.1;

// ---- store factory ----

/**
 * Create the monitor store.  Reads device/sample-rate/channel config
 * from the companion `AcquireStore` so Setup configures both recording
 * AND monitoring in one place.
 */
export function createMonitorStore(acquire: AcquireStore) {
  const status = writable<MonitorStatus>('idle');
  const errorMsg = writable('');
  const stacked = writable(false);
  const autoscaleY = writable(true);
  const levels = writable<ChannelLevel[]>([]);

  // Ring buffer: per-channel Float32Arrays, circular write position.
  // Exposed as a snapshot for the canvas renderer.
  let ringBuf: Float32Array[] = [];
  let ringLen = 0;        // allocated length per channel
  let ringPos = 0;        // next write position (wraps)
  let ringFs = 44100;     // actual fs (set on stream open)
  let ringChannels = 1;
  // Revision counter bumped on each write — the canvas renderer can
  // skip redraws when nothing changed (e.g. while paused).
  let ringRev = 0;

  /** Writable store so Svelte reactivity picks up ring buffer changes. */
  const ringRevision = writable(0);

  let handle: MonitorHandle | null = null;
  let paused = false;
  // Generation token: bumped on every start() and stop()/cancel so an
  // in-flight `startMonitor` promise can tell it was superseded/cancelled
  // while it awaited, and tear its just-opened stream down instead of
  // reviving a monitor the user already stopped (I2/I3).
  let startGen = 0;

  /**
   * The monitor callback — processes each audio chunk from the source
   * layer.  When paused, still reads levels (for the meter) but skips
   * the ring buffer write so the trace freezes.
   */
  const ondata: MonitorCallback = (chunk) => {
    // Compute per-channel levels.
    const nCh = chunk.nChannels;
    const n = chunk.nSamples;
    const lvls: ChannelLevel[] = [];
    for (let ch = 0; ch < nCh; ch++) {
      let peak = 0;
      let sumSq = 0;
      for (let i = 0; i < n; i++) {
        const v = chunk.data[i * nCh + ch];
        const a = Math.abs(v);
        if (a > peak) peak = a;
        sumSq += v * v;
      }
      lvls.push({ peak, rms: Math.sqrt(sumSq / n) });
    }
    levels.set(lvls);

    if (paused) return;

    // Write into ring buffer.
    for (let i = 0; i < n; i++) {
      const wp = (ringPos + i) % ringLen;
      for (let ch = 0; ch < nCh; ch++) {
        ringBuf[ch][wp] = chunk.data[i * nCh + ch];
      }
    }
    ringPos = (ringPos + n) % ringLen;
    ringRev++;
    ringRevision.set(ringRev);
  };

  /**
   * Start the monitor (opens the mic and begins streaming).  Reads
   * device settings from the acquire store so Setup controls both.
   */
  async function start(): Promise<void> {
    if (handle || get(status) === 'starting') return; // already running/starting (I3)
    const gen = ++startGen;                            // this start's generation (I2)
    status.set('starting');
    errorMsg.set('');
    paused = false;

    const cfg = get(acquire.settings);
    ringFs = cfg.sampleRate;
    ringChannels = cfg.channelCount;
    ringLen = Math.max(256, Math.ceil(cfg.sampleRate * DEFAULT_WINDOW_S));

    // Allocate ring buffer.
    ringBuf = [];
    for (let ch = 0; ch < cfg.channelCount; ch++) {
      ringBuf.push(new Float32Array(ringLen));
    }
    ringPos = 0;
    ringRev = 0;

    try {
      const h = await startMonitor(
        { deviceId: cfg.deviceId || undefined, sampleRate: cfg.sampleRate, channelCount: cfg.channelCount },
        ondata,
      );
      // stop()/cancel bumped the generation while we awaited — this start was
      // superseded/cancelled. Tear the just-opened stream down and bail
      // without reviving the monitor the user already stopped (I2).
      if (gen !== startGen) { h.stop(); return; }
      handle = h;
      // Update ring config from actual hardware values.
      ringFs = handle.fs;
      ringChannels = handle.nChannels;
      // Re-allocate if channel count differs from requested.
      if (handle.nChannels !== cfg.channelCount) {
        ringBuf = [];
        for (let ch = 0; ch < handle.nChannels; ch++) {
          ringBuf.push(new Float32Array(ringLen));
        }
      }
      status.set('streaming');
    } catch (e) {
      if (gen !== startGen) return;   // cancelled while awaiting — leave the newer state alone
      const msg = e instanceof Error ? e.message : String(e);
      status.set('error');
      errorMsg.set(msg);
    }
  }

  /** Stop the monitor and release all resources. */
  function stop(): void {
    startGen++;            // invalidate any in-flight start() (I2)
    handle?.stop();
    handle = null;
    paused = false;
    status.set('idle');
    levels.set([]);
  }

  /** Pause: freeze the trace (ring buffer stops writing) but keep metering. */
  function pause(): void {
    if (!handle) return;
    paused = true;
    status.set('paused');
  }

  /** Resume after pause. */
  function resume(): void {
    if (!handle) return;
    paused = false;
    status.set('streaming');
  }

  /** Toggle pause ↔ streaming. */
  function togglePause(): void {
    if (get(status) === 'paused') resume();
    else if (get(status) === 'streaming') pause();
  }

  return {
    status,
    errorMsg,
    stacked,
    autoscaleY,
    levels,
    /** Revision counter — subscribe to get notified on new ring data. */
    ringRevision,

    start,
    stop,
    pause,
    resume,
    togglePause,

    /**
     * Read a snapshot of the ring buffer for rendering.  Returns per-
     * channel arrays in chronological order (oldest → newest), the
     * sample rate, and the current revision.  The arrays are COPIES so
     * the renderer can read them without worrying about concurrent
     * writes mid-frame.
     */
    snapshot(): { channels: Float32Array[]; fs: number; rev: number } {
      if (ringBuf.length === 0) return { channels: [], fs: ringFs, rev: ringRev };
      const out: Float32Array[] = [];
      for (let ch = 0; ch < ringChannels; ch++) {
        const arr = new Float32Array(ringLen);
        // Copy in chronological order: [ringPos..end, 0..ringPos).
        const tail = ringLen - ringPos;
        arr.set(ringBuf[ch].subarray(ringPos, ringLen), 0);
        arr.set(ringBuf[ch].subarray(0, ringPos), tail);
        out.push(arr);
      }
      return { channels: out, fs: ringFs, rev: ringRev };
    },

    /** Current ring buffer length in samples. */
    get ringLength() { return ringLen; },
  };
}
