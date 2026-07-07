/**
 * Web Audio acquisition layer (Plan 2 — browser soundcard input).
 *
 * Wraps the Web Audio API to provide device enumeration, stream opening,
 * and fixed-duration recording.  The design mirrors pydvma's Python
 * `Recorder` enough that the same data model (TimeData as a flat
 * row-major Float64Array) drops straight into the existing `actions`
 * pipeline.
 *
 * Key constraints:
 * - `getUserMedia` needs user gesture + permission; we handle the
 *   PermissionDenied path with a clear error.
 * - Channel count is device-dependent; we request `channelCount` but
 *   the browser may give fewer — the actual count is read after the
 *   stream opens.
 * - Sample rates are AudioContext-determined; we create the context
 *   with a requested rate but the hardware may override it — the actual
 *   rate is read after construction.
 * - ScriptProcessorNode is deprecated but universally supported;
 *   AudioWorklet is the successor but adds async complexity and requires
 *   a separate module URL.  We use ScriptProcessorNode for MVP and mark
 *   the AudioWorklet upgrade as a TODO.
 */

// ---- types ----

/** A discovered audio input device. */
export interface AudioInputDevice {
  deviceId: string;
  label: string;        // human-readable; a synthetic fallback until permission granted
  groupId: string;
  /** True when the browser gave a REAL label (i.e. mic permission granted). */
  hasLabel: boolean;
}

/** Configuration for a recording session. */
export interface RecordConfig {
  deviceId?: string;    // omit or '' for browser default
  sampleRate: number;   // requested; actual may differ
  channelCount: number; // requested; actual may differ
  durationS: number;    // seconds to record
  /**
   * getUserMedia processing constraints.  ALL DEFAULT TO `false` — see
   * {@link buildAudioConstraints}.  The browser turns these ON by
   * default (they are tuned for voice chat), but each one non-linearly
   * distorts a measurement signal: `echoCancellation` subtracts a filtered
   * copy of the output, `noiseSuppression` gates/spectrally-subtracts, and
   * `autoGainControl` applies a slow time-varying gain.  For vibration /
   * acoustics measurement they must be off, so pydvma opts out unless the
   * user explicitly re-enables one.
   */
  echoCancellation?: boolean;
  noiseSuppression?: boolean;
  autoGainControl?: boolean;
}

/**
 * Build the getUserMedia audio track constraints from a config.
 *
 * The three DSP flags default to `false`: browsers enable
 * echoCancellation / noiseSuppression / autoGainControl by default for
 * voice use, but every one of them corrupts a measurement signal
 * (echo-cancellation subtracts a copy of the output, noise-suppression
 * spectrally gates, auto-gain applies a time-varying gain).  We opt out
 * unless the caller passes `true`.
 */
function buildAudioConstraints(cfg: Omit<RecordConfig, 'durationS'>): MediaTrackConstraints {
  return {
    ...(cfg.deviceId ? { deviceId: { exact: cfg.deviceId } } : {}),
    channelCount: { ideal: cfg.channelCount },
    sampleRate: { ideal: cfg.sampleRate },
    echoCancellation: cfg.echoCancellation ?? false,
    noiseSuppression: cfg.noiseSuppression ?? false,
    autoGainControl: cfg.autoGainControl ?? false,
  };
}

/** Result of a completed recording. */
export interface Recording {
  /** Row-major (N_samples, N_channels) float64 time-series data. */
  data: Float64Array;
  /** Time axis in seconds, length N_samples. */
  timeAxis: Float64Array;
  /** Actual sample rate the hardware delivered. */
  fs: number;
  /** Actual number of channels captured. */
  nChannels: number;
  /** Total samples per channel. */
  nSamples: number;
}

/** Lifecycle handle returned by `startRecording`. */
export interface RecordingHandle {
  /** Resolves when the recording completes (or rejects on error/cancel). */
  promise: Promise<Recording>;
  /** Cancel a recording in progress.  The promise rejects with 'cancelled'. */
  cancel: () => void;
  /** Elapsed seconds (updated each audio callback). */
  elapsed: () => number;
}

// ---- monitor (continuous streaming) types ----

/**
 * A chunk of interleaved audio data delivered to the monitor callback.
 * `data` is row-major (nSamples, nChannels) Float32Array (kept at f32
 * for real-time performance — the oscilloscope doesn't need f64).
 */
export interface MonitorChunk {
  data: Float32Array;
  nSamples: number;
  nChannels: number;
  fs: number;
}

/** Callback invoked for each audio processing block. */
export type MonitorCallback = (chunk: MonitorChunk) => void;

/**
 * Lifecycle handle returned by `startMonitor`. The monitor streams
 * continuously until `stop()` is called.
 */
export interface MonitorHandle {
  /** Stop the monitor and release all resources. */
  stop: () => void;
  /** Actual sample rate the hardware delivered. */
  fs: number;
  /** Actual channel count. */
  nChannels: number;
}

// ---- device enumeration ----

/**
 * Enumerate audio INPUT devices.  On first call the labels are empty
 * until the user grants microphone permission — call after a successful
 * `getUserMedia` to get real labels.
 */
export async function enumerateInputDevices(): Promise<AudioInputDevice[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const all = await navigator.mediaDevices.enumerateDevices();
  return all
    .filter((d) => d.kind === 'audioinput')
    .map((d) => ({
      deviceId: d.deviceId,
      label: d.label || `Input ${d.deviceId.slice(0, 6) || 'default'}`,
      groupId: d.groupId,
      hasLabel: !!d.label,
    }));
}

// ---- recording ----

/**
 * Start a fixed-duration recording.  Returns a handle with a promise
 * that resolves when `durationS` seconds have been captured, and a
 * `cancel()` to abort early.
 *
 * The caller must have already been triggered by a user gesture (click)
 * for `getUserMedia` to succeed on most browsers.
 */
export function startRecording(cfg: RecordConfig): RecordingHandle {
  let cancelled = false;
  let elapsedS = 0;

  // Buffer size for ScriptProcessorNode — 4096 is a good balance
  // between latency and callback frequency.
  const BUFFER_SIZE = 4096;

  const promise = (async (): Promise<Recording> => {
    // 1. Open the microphone stream.
    const constraints: MediaStreamConstraints = { audio: buildAudioConstraints(cfg) };

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia(constraints);
    } catch (e) {
      if (e instanceof DOMException && e.name === 'NotAllowedError') {
        throw new Error('Microphone permission denied — please allow access and try again.');
      }
      throw new Error(`Could not open audio input: ${e instanceof Error ? e.message : e}`);
    }

    if (cancelled) {
      stream.getTracks().forEach((t) => t.stop());
      throw new Error('cancelled');
    }

    // 2. Create AudioContext + nodes. The mic is now open, so any throw here
    // (unsupported sample rate, too many channels, or an OOM on the
    // pre-allocated buffer at extreme settings) must release the stream
    // before rethrowing — else the mic stays live with no handle (C2).
    // TODO: migrate ScriptProcessorNode → AudioWorklet (lower latency, no jank).
    let ctx: AudioContext | undefined;
    let actualFs!: number;
    let source!: MediaStreamAudioSourceNode;
    let actualChannels!: number;
    let totalSamples!: number;
    let buf!: Float64Array;
    let processor!: ScriptProcessorNode;
    try {
      ctx = new AudioContext({ sampleRate: cfg.sampleRate });
      actualFs = ctx.sampleRate;
      source = ctx.createMediaStreamSource(stream);
      // Actual channel count — the stream may give fewer than requested.
      actualChannels = Math.min(
        cfg.channelCount,
        source.channelCount || stream.getAudioTracks()[0]?.getSettings?.()?.channelCount || 1,
      );
      totalSamples = Math.ceil(actualFs * cfg.durationS);
      // Pre-allocate interleaved buffer: (totalSamples, actualChannels) row-major.
      buf = new Float64Array(totalSamples * actualChannels);
      processor = ctx.createScriptProcessor(BUFFER_SIZE, actualChannels, actualChannels);
    } catch (e) {
      try { ctx?.close(); } catch { /* */ }
      stream.getTracks().forEach((t) => t.stop());
      throw new Error(`Could not start audio capture: ${e instanceof Error ? e.message : e}`);
    }
    let writePos = 0; // next sample index (per channel)

    return new Promise<Recording>((resolve, reject) => {
      function cleanup() {
        try { processor.disconnect(); } catch { /* */ }
        try { source.disconnect(); } catch { /* */ }
        try { ctx?.close(); } catch { /* */ }
        stream.getTracks().forEach((t) => t.stop());
      }

      processor.onaudioprocess = (ev: AudioProcessingEvent) => {
        if (cancelled) {
          cleanup();
          reject(new Error('cancelled'));
          return;
        }

        const remaining = totalSamples - writePos;
        if (remaining <= 0) return; // already done

        const n = Math.min(ev.inputBuffer.length, remaining);
        // Copy each channel into the interleaved buffer.
        for (let ch = 0; ch < actualChannels; ch++) {
          const chData = ev.inputBuffer.getChannelData(ch);
          for (let i = 0; i < n; i++) {
            buf[(writePos + i) * actualChannels + ch] = chData[i];
          }
        }
        writePos += n;
        elapsedS = writePos / actualFs;

        if (writePos >= totalSamples) {
          cleanup();

          // Build the time axis.
          const timeAxis = new Float64Array(totalSamples);
          for (let i = 0; i < totalSamples; i++) timeAxis[i] = i / actualFs;

          resolve({
            data: buf,
            timeAxis,
            fs: actualFs,
            nChannels: actualChannels,
            nSamples: totalSamples,
          });
        }
      };

      // Wire the graph: source → processor → destination (must connect to
      // destination for onaudioprocess to fire on most browsers).
      source.connect(processor);
      processor.connect(ctx.destination);
    });
  })();

  return {
    promise,
    cancel: () => { cancelled = true; },
    elapsed: () => elapsedS,
  };
}

// ---- continuous monitor (oscilloscope feed) ----

/**
 * Start a continuous audio monitor (oscilloscope feed).  Unlike
 * `startRecording`, this does not accumulate — it calls `ondata` with
 * each ScriptProcessorNode buffer and runs until `stop()` is called.
 *
 * Returns a promise that resolves with the `MonitorHandle` once the
 * stream is open and wired (rejects on permission error or if the
 * browser lacks support). The caller must call `handle.stop()` when
 * done.
 */
export async function startMonitor(
  cfg: Omit<RecordConfig, 'durationS'>,
  ondata: MonitorCallback,
): Promise<MonitorHandle> {
  const BUFFER_SIZE = 2048; // smaller than recording for lower latency

  const constraints: MediaStreamConstraints = { audio: buildAudioConstraints(cfg) };

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(constraints);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'NotAllowedError') {
      throw new Error('Microphone permission denied — please allow access and try again.');
    }
    throw new Error(`Could not open audio input: ${e instanceof Error ? e.message : e}`);
  }

  // The mic is now open. If any of the AudioContext/node construction below
  // throws (e.g. an unsupported sample rate on Safari, or too many channels
  // for createScriptProcessor), release the stream before rethrowing —
  // otherwise the mic stays live with no handle to stop it (C2).
  let ctx: AudioContext | undefined;
  let actualFs!: number;
  let source!: MediaStreamAudioSourceNode;
  let actualChannels!: number;
  let processor!: ScriptProcessorNode;
  try {
    ctx = new AudioContext({ sampleRate: cfg.sampleRate });
    actualFs = ctx.sampleRate;
    source = ctx.createMediaStreamSource(stream);
    actualChannels = Math.min(
      cfg.channelCount,
      source.channelCount || stream.getAudioTracks()[0]?.getSettings?.()?.channelCount || 1,
    );
    processor = ctx.createScriptProcessor(BUFFER_SIZE, actualChannels, actualChannels);
  } catch (e) {
    try { ctx?.close(); } catch { /* */ }
    stream.getTracks().forEach((t) => t.stop());
    throw new Error(`Could not start audio monitor: ${e instanceof Error ? e.message : e}`);
  }
  let stopped = false;

  processor.onaudioprocess = (ev: AudioProcessingEvent) => {
    if (stopped) return;
    const n = ev.inputBuffer.length;
    // Build interleaved (n, nChannels) Float32Array for the callback.
    const buf = new Float32Array(n * actualChannels);
    for (let ch = 0; ch < actualChannels; ch++) {
      const chData = ev.inputBuffer.getChannelData(ch);
      for (let i = 0; i < n; i++) {
        buf[i * actualChannels + ch] = chData[i];
      }
    }
    ondata({ data: buf, nSamples: n, nChannels: actualChannels, fs: actualFs });
  };

  source.connect(processor);
  processor.connect(ctx.destination);

  function stop() {
    if (stopped) return;
    stopped = true;
    try { processor.disconnect(); } catch { /* */ }
    try { source.disconnect(); } catch { /* */ }
    try { ctx?.close(); } catch { /* */ }
    stream.getTracks().forEach((t) => t.stop());
  }

  return { stop, fs: actualFs, nChannels: actualChannels };
}
