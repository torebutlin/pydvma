/**
 * Oscilloscope / monitor store (Plan 2 — Live tab).
 *
 * Manages the real-time audio monitor lifecycle: start/stop streaming,
 * a ring buffer of recent samples for canvas rendering, per-channel
 * peak/RMS level metering, pause toggle, a latching clip flag, and the
 * scope's display options (stacked traces, autoscale, viewed time
 * window, FFT axis scaling, and which panes are shown on the Live tab).
 *
 * The monitor uses the continuous `startMonitor` API from the audio
 * source layer (distinct from `startRecording` which accumulates a
 * fixed-duration capture).  The ring buffer holds a configurable
 * window of history — enough to render a smooth oscilloscope trace and
 * compute a live FFT at 30–60 fps without storing megabytes.
 *
 * Lifecycle contract (round-2 redesign): the monitor is a persistent
 * "mini-oscilloscope" that lives bottom-left across ALL stages.  It runs
 * until the USER stops it (from the mini monitor or the Live card) or the
 * whole app tears down — it is NOT auto-stopped on stage change.  App.svelte
 * owns the teardown (onDestroy + pagehide/beforeunload → `stop()`).
 *
 * Created once at the app root and threaded to MiniMonitor, LiveCard,
 * OscCanvas and the Live scope.
 */
import { writable, get } from 'svelte/store';
import type { MonitorHandle, MonitorCallback } from '../audio/source';
import type { AcquireStore } from './acquire';

// ---- types ----

export type MonitorStatus = 'idle' | 'starting' | 'streaming' | 'paused' | 'error';

export interface ChannelLevel {
  peak: number;   // max |sample| over the current callback
  rms: number;    // RMS over the current callback
}

/** Which panes the expanded Live scope shows (time trace / FFT / levels). */
export interface PaneState {
  time: boolean;
  freq: boolean;
  levels: boolean;
}

/**
 * FFT-pane spectrum mode: `'instant'` = the per-frame amplitude spectrum
 * (today's behaviour, unit amplitude), `'psd'` = an averaged Welch power
 * spectral density over the ring buffer (unit²/Hz, lower variance).
 */
export type SpectrumMode = 'instant' | 'psd';

export type MonitorStore = ReturnType<typeof createMonitorStore>;

// ---- constants ----

/** Default ring buffer window in seconds.  ~100 ms at 44.1 kHz = 4410 samples. */
const DEFAULT_WINDOW_S = 0.1;
/** Smallest viewable window — a couple of buffers' worth. */
const MIN_WINDOW_S = 0.02;
/**
 * Ceiling on the viewed window (round-5 item 8: raise the too-low 5 s cap so
 * long records fit).  The EFFECTIVE cap is the smaller of this and the
 * memory-bounded {@link maxWindowSFor} — a flat 30 s would OOM at high
 * fs·channels (96 kHz × 16 ch × 30 s × Float32 ≈ 184 MB).
 */
const HARD_MAX_WINDOW_S = 30;
/**
 * Memory budget for the ring pre-allocation, in bytes (round-5 item 8).
 * The ring is `nCh × fs × seconds × 4` bytes (Float32), so the memory-safe
 * max window is `RING_BUDGET_BYTES / (fs · nCh · 4)`.  64 MiB keeps a typical
 * 48 kHz × 2 ch monitor at the full 30 s cap while capping a punishing
 * 96 kHz × 16 ch setup at ~10.9 s (≈64 MiB) instead of ~184 MB at a flat 30 s.
 * (`snapshot()` copies the ring each frame, so peak is ~2× this transiently.)
 */
const RING_BUDGET_BYTES = 64 * 1024 * 1024;
/** Bytes per stored sample — the ring holds Float32 (`Float32Array`). */
const BYTES_PER_SAMPLE = 4;

/**
 * Memory-safe maximum viewed window (seconds) for a given sample rate and
 * channel count (round-5 item 8).  The smaller of {@link HARD_MAX_WINDOW_S}
 * and the {@link RING_BUDGET_BYTES} budget divided by the per-second ring
 * cost (`fs · nCh · 4` bytes), floored at {@link MIN_WINDOW_S} so a pathological
 * fs/channel combination still yields a usable (if tiny) window.  Exported for
 * the LiveCard (custom-window `max`) and for tests.
 */
export function maxWindowSFor(fs: number, nCh: number): number {
  const perSecond = Math.max(1, fs) * Math.max(1, nCh) * BYTES_PER_SAMPLE;
  const budgeted = RING_BUDGET_BYTES / perSecond;
  return Math.max(MIN_WINDOW_S, Math.min(HARD_MAX_WINDOW_S, budgeted));
}
/** The selectable window presets surfaced in the LiveCard. */
export const WINDOW_PRESETS_S = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10] as const;
/** Peak level at or above which the latching clip flag trips. */
const CLIP_THRESHOLD = 0.95;

/** Smallest FFT max-frequency the user may zoom to (Hz). */
const MIN_FMAX_HZ = 10;
/** The Welch averaging choices surfaced in the LiveCard's PSD mode. */
export const PSD_SEGMENT_CHOICES = [1, 2, 4, 8, 16] as const;
/** Default number of Welch averaging segments in PSD mode. */
const DEFAULT_PSD_SEGMENTS = 4;
/**
 * Max exponential temporal-smoothing factor for PSD mode (0 = off).  The
 * canvas blends `s ← a·s + (1−a)·new` each frame; capped below 1 so the
 * display can never freeze entirely.
 */
const MAX_PSD_SMOOTHING = 0.95;

// ---- store factory ----

/**
 * Create the monitor store.  Reads device/sample-rate/channel config
 * (and the getUserMedia constraint flags) from the companion
 * `AcquireStore` so Setup configures both recording AND monitoring in
 * one place.
 */
export function createMonitorStore(acquire: AcquireStore) {
  const status = writable<MonitorStatus>('idle');
  const errorMsg = writable('');
  const stacked = writable(false);
  const autoscaleY = writable(true);
  const levels = writable<ChannelLevel[]>([]);
  // Latching clip flag: trips when any channel peak ≥ CLIP_THRESHOLD and
  // STAYS tripped until the user resets it (or a fresh start()).  The mini
  // + Live CLIP pills read this; clicking a pill calls resetClip().
  const clipLatched = writable(false);

  // ---- scope display settings (osc-specific) ----
  /** Viewed time window in seconds (also the ring-buffer span). */
  const windowS = writable<number>(DEFAULT_WINDOW_S);
  /** FFT magnitude axis: dB (log) when true, linear when false. */
  const fftYLog = writable(true);
  /** FFT frequency axis: log when true, linear when false. */
  const fftXLog = writable(false);
  /**
   * FFT max frequency to display, in Hz.  `null` = "full" (Nyquist,
   * `fs/2`), which is the default; a finite value zooms the frequency
   * axis to the interesting band.  Clamped to Nyquist at draw time (the
   * store doesn't know fs), so an over-large value just shows full span.
   */
  const fftFMax = writable<number | null>(null);
  /**
   * FFT MIN frequency to display, in Hz (round-4 item 6).  `null` = the
   * band's natural lower edge (DC on a linear axis, the first bin on a log
   * axis).  Paired with {@link fftFMax} so the Live scope can window the
   * spectrum to an arbitrary `[fmin, fmax]` band, not just a max.
   */
  const fftFMin = writable<number | null>(null);
  /**
   * FFT frequency-axis mode: `'full'` shows the whole span (fmin/fmax both
   * ignored — the natural edges); `'range'` honours the fmin/fmax band.  A
   * UI convenience so the "range" boxes can be revealed/remembered even when
   * momentarily blank; the draw path reads fmin/fmax directly (both `null` in
   * `'full'`), so it stays back-compatible with the pre-range behaviour.
   */
  const fftFreqMode = writable<'full' | 'range'>('full');
  /** FFT-pane spectrum mode: instantaneous amplitude vs averaged PSD. */
  const spectrumMode = writable<SpectrumMode>('instant');
  /** Number of Welch averaging segments in PSD mode. */
  const psdSegments = writable<number>(DEFAULT_PSD_SEGMENTS);
  /**
   * Exponential temporal-smoothing factor applied to the PSD across
   * frames (0 = off, up to {@link MAX_PSD_SMOOTHING}).  Cheap extra
   * variance reduction layered on top of the Welch spatial averaging.
   */
  const psdSmoothing = writable<number>(0);
  /** Which Live-scope panes are visible. */
  const panes = writable<PaneState>({ time: true, freq: true, levels: true });

  // Ring buffer: per-channel Float32Arrays, circular write position.
  // Exposed as a snapshot for the canvas + FFT renderers.
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
   * Ring length (samples/channel) for a given fs + window, clamped to the
   * memory-safe window for THIS fs and channel count (round-5 item 8; M3).
   * `nCh` is needed because the safe max depends on the total ring cost
   * (`fs · nCh · 4` bytes) — see {@link maxWindowSFor}.
   */
  function ringLenFor(fs: number, seconds: number, nCh: number): number {
    const clamped = Math.min(maxWindowSFor(fs, nCh), Math.max(MIN_WINDOW_S, seconds));
    return Math.max(256, Math.ceil(fs * clamped));
  }

  /**
   * The memory-safe max viewed window (seconds) for the CURRENT config: the
   * live stream's fs/channels while streaming, else the pending acquire
   * settings.  The LiveCard reads this to bound its custom-window input so the
   * user can never request a window that would blow the ring budget.
   */
  function currentMaxWindowS(): number {
    if (ringBuf.length > 0) return maxWindowSFor(ringFs, ringChannels);
    const cfg = get(acquire.settings);
    return maxWindowSFor(cfg.sampleRate, cfg.channelCount);
  }

  /** (Re)allocate the ring buffer to `nCh × len` zero-filled channels. */
  function allocRing(nCh: number, len: number): void {
    ringBuf = [];
    for (let ch = 0; ch < nCh; ch++) ringBuf.push(new Float32Array(len));
    ringLen = len;
    ringPos = 0;
  }

  /**
   * Drop the ring buffer so `snapshot()` reports "no data" and the scope
   * shows its empty prompt.  Used on stop() and on a start() failure so a
   * dead monitor never leaves stale zero-filled traces on screen.
   */
  function clearRing(): void {
    ringBuf = [];
    ringLen = 0;
    ringPos = 0;
    ringRev++;
    ringRevision.set(ringRev);
  }

  /**
   * The monitor callback — processes each audio chunk from the source
   * layer.  When paused, still reads levels (for the meter + clip flag)
   * but skips the ring buffer write so the trace freezes.
   */
  const ondata: MonitorCallback = (chunk) => {
    // Compute per-channel levels.
    const nCh = chunk.nChannels;
    const n = chunk.nSamples;
    const lvls: ChannelLevel[] = [];
    let clippedThisChunk = false;
    for (let ch = 0; ch < nCh; ch++) {
      let peak = 0;
      let sumSq = 0;
      for (let i = 0; i < n; i++) {
        const v = chunk.data[i * nCh + ch];
        const a = Math.abs(v);
        if (a > peak) peak = a;
        sumSq += v * v;
      }
      if (peak >= CLIP_THRESHOLD) clippedThisChunk = true;
      lvls.push({ peak, rms: Math.sqrt(sumSq / n) });
    }
    levels.set(lvls);
    if (clippedThisChunk) clipLatched.set(true);

    if (paused) return;
    if (ringLen === 0) return; // not allocated (shouldn't happen while streaming)

    // Write into ring buffer.
    for (let i = 0; i < n; i++) {
      const wp = (ringPos + i) % ringLen;
      for (let ch = 0; ch < nCh && ch < ringBuf.length; ch++) {
        ringBuf[ch][wp] = chunk.data[i * nCh + ch];
      }
    }
    ringPos = (ringPos + n) % ringLen;
    ringRev++;
    ringRevision.set(ringRev);
  };

  /**
   * Start the monitor (opens the mic and begins streaming).  Reads
   * device settings + constraint flags from the acquire store so Setup
   * controls both.  Resets the latching clip flag for the fresh session.
   */
  async function start(): Promise<void> {
    if (handle || get(status) === 'starting') return; // already running/starting (I3)
    const gen = ++startGen;                            // this start's generation (I2)
    status.set('starting');
    errorMsg.set('');
    clipLatched.set(false);
    paused = false;

    const cfg = get(acquire.settings);
    ringFs = cfg.sampleRate;
    ringChannels = cfg.channelCount;
    allocRing(cfg.channelCount, ringLenFor(cfg.sampleRate, get(windowS), cfg.channelCount));
    ringRev = 0;

    try {
      // Route through the acquire store's active provider (Web Audio or the
      // serve bridge). Read at start() time so a provider swap is picked up.
      const h = await acquire.provider.startMonitor(
        {
          deviceId: cfg.deviceId || undefined,
          sampleRate: cfg.sampleRate,
          channelCount: cfg.channelCount,
          echoCancellation: cfg.echoCancellation,
          noiseSuppression: cfg.noiseSuppression,
          autoGainControl: cfg.autoGainControl,
          latency: cfg.latency,
        },
        ondata,
      );
      // stop()/cancel bumped the generation while we awaited — this start was
      // superseded/cancelled. Tear the just-opened stream down and bail
      // without reviving the monitor the user already stopped (I2).
      if (gen !== startGen) { h.stop(); return; }
      handle = h;
      // Update ring config from actual hardware values (fs and channel
      // count may differ from what we requested) and re-allocate to match.
      ringFs = handle.fs;
      ringChannels = handle.nChannels;
      allocRing(handle.nChannels, ringLenFor(handle.fs, get(windowS), handle.nChannels));
      status.set('streaming');
    } catch (e) {
      if (gen !== startGen) return;   // cancelled while awaiting — leave the newer state alone
      const msg = e instanceof Error ? e.message : String(e);
      clearRing();                    // no stale zero traces behind the error
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
    clearRing();           // clear the trace so a stopped scope shows its prompt
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

  /**
   * Set the viewed time window (seconds).  Clamped to `[MIN_WINDOW_S,
   * currentMaxWindowS()]` — the upper bound is the memory-safe max for the
   * current fs/channels (round-5 item 8), so a longer window is honoured up to
   * the 30 s ceiling on modest configs but bounded to ~64 MiB of ring on heavy
   * ones.  When streaming the ring buffer is re-allocated live so the trace +
   * FFT immediately reflect the new span (the old history is dropped — a
   * longer/shorter window is a fresh view, not a resample).
   */
  function setWindow(seconds: number): void {
    const clamped = Math.min(currentMaxWindowS(), Math.max(MIN_WINDOW_S, seconds));
    windowS.set(clamped);
    if (ringBuf.length > 0) {
      allocRing(ringChannels, ringLenFor(ringFs, clamped, ringChannels));
      ringRev++;
      ringRevision.set(ringRev);
    }
  }

  /**
   * Set the FFT max-frequency zoom (Hz), or `null` for "full" (Nyquist).
   * A finite value is clamped to ≥ {@link MIN_FMAX_HZ}; the upper clamp to
   * Nyquist happens at draw time where the sample rate is known.
   */
  function setFftFMax(hz: number | null): void {
    if (hz == null || !isFinite(hz)) { fftFMax.set(null); return; }
    fftFMax.set(Math.max(MIN_FMAX_HZ, hz));
  }

  /**
   * Set the FFT MIN-frequency zoom (Hz), or `null` for the band's natural
   * lower edge.  A finite value is clamped to ≥ 0; the draw path further
   * clamps it below the displayed max so an inverted band never renders.
   */
  function setFftFMin(hz: number | null): void {
    if (hz == null || !isFinite(hz)) { fftFMin.set(null); return; }
    fftFMin.set(Math.max(0, hz));
  }

  /**
   * Set the FFT frequency-axis mode.  `'full'` also resets fmin/fmax to
   * `null` (the natural edges) so leaving "range" reliably restores the whole
   * span; `'range'` leaves the current fmin/fmax in place (blank ⇒ edge).
   */
  function setFftFreqMode(mode: 'full' | 'range'): void {
    if (mode === 'full') { fftFMin.set(null); fftFMax.set(null); fftFreqMode.set('full'); }
    else fftFreqMode.set('range');
  }

  /** Switch the FFT pane between instantaneous and averaged-PSD modes. */
  function setSpectrumMode(mode: SpectrumMode): void {
    spectrumMode.set(mode === 'psd' ? 'psd' : 'instant');
  }

  /** Set the Welch averaging segment count (clamped ≥ 1, integer). */
  function setPsdSegments(n: number): void {
    psdSegments.set(Math.max(1, Math.floor(n) || 1));
  }

  /** Set the PSD temporal-smoothing factor (clamped to [0, MAX]). */
  function setPsdSmoothing(a: number): void {
    if (!isFinite(a)) { psdSmoothing.set(0); return; }
    psdSmoothing.set(Math.max(0, Math.min(MAX_PSD_SMOOTHING, a)));
  }

  /** Clear the latching clip flag (called when the user clicks a CLIP pill). */
  function resetClip(): void {
    clipLatched.set(false);
  }

  /** Toggle one Live-scope pane (time / freq / levels). */
  function togglePane(which: keyof PaneState): void {
    panes.update((p) => ({ ...p, [which]: !p[which] }));
  }

  return {
    status,
    errorMsg,
    stacked,
    autoscaleY,
    levels,
    clipLatched,
    windowS,
    fftYLog,
    fftXLog,
    fftFMax,
    fftFMin,
    fftFreqMode,
    spectrumMode,
    psdSegments,
    psdSmoothing,
    panes,
    /** Revision counter — subscribe to get notified on new ring data. */
    ringRevision,

    start,
    stop,
    pause,
    resume,
    togglePause,
    setWindow,
    /** Memory-safe max viewed window (s) for the current fs/channels (item 8). */
    maxWindowS: currentMaxWindowS,
    setFftFMax,
    setFftFMin,
    setFftFreqMode,
    setSpectrumMode,
    setPsdSegments,
    setPsdSmoothing,
    resetClip,
    togglePane,

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
      for (let ch = 0; ch < ringChannels && ch < ringBuf.length; ch++) {
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
