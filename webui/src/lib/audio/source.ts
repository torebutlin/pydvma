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
 *
 * Capture node — AudioWorklet (primary) with a ScriptProcessorNode
 * fallback:
 * - The PRIMARY path is an {@link AudioWorkletNode} running
 *   `capture.worklet.js` on the dedicated audio render thread.  It does
 *   not drop blocks under UI load (the deprecated ScriptProcessorNode
 *   runs on the main thread and does), so the oscilloscope stays smooth
 *   and a recording has no holes.  The worklet accumulates the 128-frame
 *   render quanta up to the old BUFFER_SIZE cadence before posting an
 *   interleaved chunk back — see the worklet's docstring for the
 *   accumulation/interleaving contract.  Its module is loaded via
 *   `audioContext.audioWorklet.addModule(<url>)`, where the url is a Vite
 *   asset built from `new URL('./capture.worklet.js', import.meta.url)`
 *   (emitted verbatim in both dev and `vite build`).
 * - The FALLBACK path is the old {@link ScriptProcessorNode}, used only
 *   when `audioContext.audioWorklet` is unavailable (e.g. older Safari).
 *   Both paths funnel their interleaved (nSamples, nChannels) Float32
 *   chunks through the same downstream consumer, so cadence, levels and
 *   ring-buffer behaviour are identical whichever node is chosen.
 *
 * Output stimulus + pretrigger (round-5 item 10 — browser parity):
 * `startRecording` optionally plays a generated stimulus through the audio
 * OUTPUT during the capture (`RecordConfig.output`, an `AudioBufferSourceNode`
 * filled from {@link generateStimulus}) and/or runs an ARMED capture that waits
 * for a threshold crossing before assembling a pretrigger window
 * (`RecordConfig.pretrig`, via {@link PretrigAssembler}).  Both are Web-Audio-
 * only optional extensions to the shared `RecordConfig`; the bridge provider
 * ignores them (it maps its own `BridgeConfig` to server-side pydvma settings).
 */
import { generateStimulus } from './signal';
import { PretrigAssembler, clampPretrigSamples } from './pretrig';

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
  /**
   * Preferred input latency HINT in seconds (getUserMedia `latency`
   * constraint).  Optional — omit to let the browser pick.  A lower value
   * favours responsiveness (smaller device buffers) at the cost of more
   * xrun risk; the browser treats it as `ideal`, so it is best-effort only.
   * Surfaced in Setup's "full" panel because it becomes relevant for the
   * NI-DAQ path (hardware buffer sizing) later.
   */
  latency?: number;
  /**
   * Digital low-pass toggle (round-9). Web Audio: record at the context's
   * NATIVE rate (the `sampleRate` request is not pinned onto the
   * AudioContext, avoiding the browser's own opaque resampler) so the
   * engine can come down to `sampleRate` behind a proper anti-alias FIR
   * afterwards — the CALLER does that post-capture step; this module only
   * skips the context-rate pin. Bridge: the server handles the whole
   * chain (`MySettings.lpf_on`).
   */
  lpfOn?: boolean;
  /**
   * Optional OUTPUT stimulus played through the speakers/AO during the capture
   * (round-5 item 10).  Web-Audio-only; the bridge provider ignores it.  See
   * {@link OutputStimulusConfig}.
   */
  output?: OutputStimulusConfig;
  /**
   * Optional ARMED-capture pretrigger (round-5 item 10).  When present, the
   * capture waits for a threshold crossing and returns a window straddling it.
   * Web-Audio-only; the bridge provider ignores it.  See {@link PretrigRecordOptions}.
   */
  pretrig?: PretrigRecordOptions;
}

/** Pretrigger lifecycle event surfaced during an armed Web Audio capture. */
export type CaptureStatusEvent = 'armed' | 'triggered' | 'timeout';

/**
 * A Web Audio OUTPUT stimulus to play during a recording — the browser
 * analogue of pydvma's `Output_Signal_Settings` / `signal_generator`.  The
 * waveform is generated by {@link generateStimulus} and played through an
 * `AudioBufferSourceNode`, started together with the capture; it lasts
 * `min(durationS, captureDuration)`.  IMPORTANT: an output during capture is
 * only measurable when the getUserMedia DSP flags are OFF — `startRecording`
 * forces `echoCancellation` / `noiseSuppression` / `autoGainControl` off
 * whenever an `output` is present (echo cancellation would subtract the very
 * signal being measured).
 */
export interface OutputStimulusConfig {
  /** Signal family — `signal_generator` tokens ('uniform' shows as "white"). */
  type: 'sweep' | 'uniform' | 'gaussian';
  /**
   * Peak amplitude as a NORMALISED gain (0..1) — the browser DAC has no
   * calibrated volts.  Clamped to `[0, 1]` at play time.
   */
  amp: number;
  /** Sweep start / noise low corner (Hz). */
  f1: number;
  /** Sweep end / noise high corner (Hz). */
  f2: number;
  /** Duration (s); defaults to (and is capped at) the capture duration. */
  durationS?: number;
  /**
   * Output device id for `AudioContext.setSinkId` (feature-detected).  Ignored
   * where `setSinkId` is unavailable (Safari/Firefox) — output goes to the
   * default device.
   */
  deviceId?: string;
  /** Output channel count (default 1); the same waveform is written to each. */
  channels?: number;
}

/**
 * Armed-capture pretrigger options (Web Audio).  Mirrors pydvma's
 * `MySettings.pretrig_*`: the capture waits up to `timeoutS` for `|x|` on
 * `channel` to exceed `threshold`, then returns a window with `pretrigSamples`
 * of pre-trigger context (see {@link PretrigAssembler}).  On timeout it falls
 * back to an ordinary capture (no raise), mirroring `acquisition.log_data`.
 */
export interface PretrigRecordOptions {
  /** Channel the threshold is watched on. */
  channel: number;
  /** Absolute threshold on |x| (normalised units), strict `>`. */
  threshold: number;
  /** Samples of pre-trigger context (clamped to a sane cap `< totalSamples`). */
  pretrigSamples: number;
  /** Timeout (s) before falling back to an ordinary capture. */
  timeoutS: number;
  /** Lifecycle sink: `armed` → `triggered` / `timeout`. */
  onStatus?: (event: CaptureStatusEvent) => void;
}

/**
 * Build the getUserMedia audio track constraints from a config.
 *
 * The three DSP flags default to `false`: browsers enable
 * echoCancellation / noiseSuppression / autoGainControl by default for
 * voice use, but every one of them corrupts a measurement signal
 * (echo-cancellation subtracts a copy of the output, noise-suppression
 * spectrally gates, auto-gain applies a time-varying gain).  We opt out
 * unless the caller passes `true`.  A `latency` hint is passed through only
 * when the caller supplies a finite positive value (else the browser picks).
 */
function buildAudioConstraints(cfg: Omit<RecordConfig, 'durationS'>): MediaTrackConstraints {
  return {
    ...(cfg.deviceId ? { deviceId: { exact: cfg.deviceId } } : {}),
    channelCount: { ideal: cfg.channelCount },
    sampleRate: { ideal: cfg.sampleRate },
    echoCancellation: cfg.echoCancellation ?? false,
    noiseSuppression: cfg.noiseSuppression ?? false,
    autoGainControl: cfg.autoGainControl ?? false,
    ...(typeof cfg.latency === 'number' && cfg.latency > 0
      ? { latency: { ideal: cfg.latency } }
      : {}),
  };
}

// ---- capture worklet plumbing (shared by monitor + recording) ----

/** The `registerProcessor` name inside `capture.worklet.js`. */
const CAPTURE_PROCESSOR_NAME = 'pydvma-capture';

/**
 * URL of the compiled capture worklet module.  Built through Vite's
 * `new URL(<literal>, import.meta.url)` asset pattern so the file is emitted
 * (hashed) in `vite build` and served correctly by the dev server — the
 * worklet ships as a standalone script for `audioWorklet.addModule()`.  It is
 * plain JS (no imports) so Vite copies it verbatim into the audio realm.
 */
function captureWorkletUrl(): string {
  return new URL('./capture.worklet.js', import.meta.url).href;
}

/**
 * Whether this AudioContext can run the AudioWorklet capture path.  False on
 * browsers without `AudioWorklet` (older Safari) — the caller then falls back
 * to a ScriptProcessorNode.  Also guards test/JSDOM environments that stub a
 * bare AudioContext without a worklet surface.
 */
function canUseWorklet(ctx: AudioContext): boolean {
  return (
    typeof AudioWorkletNode !== 'undefined' &&
    !!ctx.audioWorklet &&
    typeof ctx.audioWorklet.addModule === 'function'
  );
}

/**
 * Shape of one interleaved chunk the capture worklet posts back on its port.
 * `data` is row-major (nSamples, nChannels) Float32; `nSamples` is the
 * per-channel frame count.  (source.ts stamps `fs` before handing it on.)
 */
interface WorkletChunkMessage {
  data: Float32Array;
  nSamples: number;
  nChannels: number;
}

/**
 * Interleave one ScriptProcessorNode input buffer (planar per-channel) into a
 * fresh row-major (nSamples, nChannels) Float32Array — the same layout the
 * worklet posts, so both capture paths feed one downstream consumer.  Only
 * used on the fallback path.
 */
function interleaveScriptBuffer(
  inputBuffer: AudioBuffer,
  nChannels: number,
): { data: Float32Array; nSamples: number } {
  const nSamples = inputBuffer.length;
  const data = new Float32Array(nSamples * nChannels);
  for (let ch = 0; ch < nChannels; ch++) {
    const chData = inputBuffer.getChannelData(ch);
    for (let i = 0; i < nSamples; i++) {
      data[i * nChannels + ch] = chData[i];
    }
  }
  return { data, nSamples };
}

/**
 * Construct the capture AudioWorkletNode with an EXPLICIT, DISCRETE channel
 * count so the worklet's planar input has exactly `nChannels` channels (no
 * speaker up/down-mix of measurement data).  `chunkFrames` sets the posted
 * chunk cadence (the old ScriptProcessorNode BUFFER_SIZE).  The module must
 * already be added to `ctx.audioWorklet`.
 */
function makeCaptureNode(
  ctx: AudioContext,
  nChannels: number,
  chunkFrames: number,
): AudioWorkletNode {
  return new AudioWorkletNode(ctx, CAPTURE_PROCESSOR_NAME, {
    numberOfInputs: 1,
    numberOfOutputs: 1,
    channelCount: nChannels,
    channelCountMode: 'explicit',
    channelInterpretation: 'discrete',
    outputChannelCount: [nChannels],
    processorOptions: { chunkFrames, nChannels },
  });
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

/** A discovered audio OUTPUT device (for the stimulus sink select). */
export interface AudioOutputDevice {
  deviceId: string;
  label: string;
}

/**
 * Whether this browser can route an AudioContext to a chosen output device via
 * `AudioContext.prototype.setSinkId` (Chromium 110+).  Safari and Firefox lack
 * it on AudioContext, so the output-device select degrades to "default output
 * only".  Feature-detected so the UI can hide the select where it would be dead.
 */
export function supportsOutputDeviceSelection(): boolean {
  return (
    typeof AudioContext !== 'undefined' &&
    typeof (AudioContext.prototype as { setSinkId?: unknown }).setSinkId === 'function'
  );
}

/**
 * Enumerate audio OUTPUT devices for the stimulus sink select.  Returns `[]`
 * where `mediaDevices` is unavailable OR the browser cannot select an output
 * (no `setSinkId`) — the caller then plays to the default device only.  Labels
 * are hidden until microphone permission is granted (same as inputs).
 */
export async function enumerateOutputDevices(): Promise<AudioOutputDevice[]> {
  if (!navigator.mediaDevices?.enumerateDevices || !supportsOutputDeviceSelection()) return [];
  const all = await navigator.mediaDevices.enumerateDevices();
  return all
    .filter((d) => d.kind === 'audiooutput')
    .map((d) => ({
      deviceId: d.deviceId,
      label: d.label || `Output ${d.deviceId.slice(0, 6) || 'default'}`,
    }));
}

// ---- recording ----

/**
 * Build the output-stimulus `AudioBufferSourceNode` for a capture.  Generates
 * the waveform ({@link generateStimulus}, normalised ±1) for
 * `min(output.durationS, captureDurationS)` seconds, writes it to every output
 * channel, connects it to the context destination, and (best-effort, feature-
 * detected) routes the context to `output.deviceId` via `setSinkId` where
 * supported (Chromium; Safari/Firefox fall back to the default device).  The
 * node is returned un-started so the caller can start it in sync with the
 * capture.
 */
async function buildStimulusNode(
  ctx: AudioContext,
  fs: number,
  captureDurationS: number,
  output: OutputStimulusConfig,
): Promise<AudioBufferSourceNode> {
  const sink = (ctx as unknown as { setSinkId?: (id: string) => Promise<void> }).setSinkId;
  if (output.deviceId && typeof sink === 'function') {
    try { await sink.call(ctx, output.deviceId); } catch { /* fall back to default output */ }
  }
  const outDur = output.durationS != null && output.durationS > 0
    ? Math.min(output.durationS, captureDurationS)
    : captureDurationS;
  const amp = Math.min(Math.max(output.amp, 0), 1); // normalised peak, clamp to [0, 1]
  const { y } = generateStimulus({
    type: output.type, fs, durationS: outDur, amp, band: [output.f1, output.f2], limit: 1,
  });
  const y32 = Float32Array.from(y);
  const channels = Math.max(1, Math.floor(output.channels ?? 1));
  const buffer = ctx.createBuffer(channels, Math.max(1, y32.length), fs);
  for (let ch = 0; ch < channels; ch++) buffer.getChannelData(ch).set(y32); // same waveform per ch
  const node = ctx.createBufferSource();
  node.buffer = buffer;
  node.connect(ctx.destination);
  return node;
}

/**
 * Start a fixed-duration recording.  Returns a handle with a promise
 * that resolves when `durationS` seconds have been captured, and a
 * `cancel()` to abort early.
 *
 * The caller must have already been triggered by a user gesture (click)
 * for `getUserMedia` to succeed on most browsers.
 *
 * Two Web-Audio-only extensions (round-5 item 10) light up when
 * `cfg.output` / `cfg.pretrig` are set:
 * - `cfg.output` plays a generated stimulus through the speakers/AO during
 *   the capture (started in sync with it).  The DSP flags are forced OFF while
 *   an output plays (echo cancellation would subtract the measured signal).
 * - `cfg.pretrig` runs an ARMED capture: the returned promise resolves only
 *   once a threshold crossing has been seen (or `timeoutS` elapses, falling
 *   back to an ordinary capture), with `pretrig.onStatus` surfacing the
 *   `armed → triggered / timeout` lifecycle.  See {@link PretrigAssembler}.
 */
export function startRecording(cfg: RecordConfig): RecordingHandle {
  let cancelled = false;
  let elapsedS = 0;

  // Posted-chunk size — 4096 matches the historical ScriptProcessorNode
  // BUFFER_SIZE (a good balance of latency vs callback frequency); the
  // worklet accumulates its 128-frame quanta up to this before posting.
  const BUFFER_SIZE = 4096;

  const armed = !!cfg.pretrig;
  const hasOutput = !!cfg.output;
  const onStatus = cfg.pretrig?.onStatus;

  const promise = (async (): Promise<Recording> => {
    // 1. Open the microphone stream.  An output stimulus is only measurable
    // with the getUserMedia DSP flags OFF — echo cancellation would subtract
    // the very signal being played — so force them off whenever output plays.
    const captureCfg: RecordConfig = hasOutput
      ? { ...cfg, echoCancellation: false, noiseSuppression: false, autoGainControl: false }
      : cfg;
    const constraints: MediaStreamConstraints = { audio: buildAudioConstraints(captureCfg) };

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

    // 2. Create AudioContext + capture node + (optional) output node. The mic
    // is now open, so any throw here — an unsupported sample rate, too many
    // channels, an OOM on the pre-allocated buffer, a REJECTED
    // `audioWorklet.addModule()`, OR an output-buffer / setSinkId failure —
    // must release the stream (and any output node) before rethrowing, else
    // the mic stays live with no handle (C2).  The async awaits (addModule,
    // setSinkId) sit inside this same guard.
    let ctx: AudioContext | undefined;
    let actualFs!: number;
    let source!: MediaStreamAudioSourceNode;
    let actualChannels!: number;
    let totalSamples!: number;
    let buf!: Float64Array;
    let workletNode: AudioWorkletNode | undefined;
    let scriptNode: ScriptProcessorNode | undefined;
    let stimulusNode: AudioBufferSourceNode | undefined;
    let assembler: PretrigAssembler | undefined;
    try {
      // Round-9 low-pass: leave the context at its NATIVE rate (usually the
      // device maximum) — the anti-alias resample to cfg.sampleRate happens
      // in the engine afterwards. Otherwise pin the requested rate as before.
      ctx = cfg.lpfOn ? new AudioContext() : new AudioContext({ sampleRate: cfg.sampleRate });
      actualFs = ctx.sampleRate;
      source = ctx.createMediaStreamSource(stream);
      // Actual channel count — the stream may give fewer than requested.
      actualChannels = Math.min(
        cfg.channelCount,
        source.channelCount || stream.getAudioTracks()[0]?.getSettings?.()?.channelCount || 1,
      );
      totalSamples = Math.ceil(actualFs * cfg.durationS);
      if (armed) {
        // Armed capture builds its window incrementally via the assembler — no
        // flat pre-buffer; only a rolling `pretrigSamples`-deep pre-history.
        const p = clampPretrigSamples(cfg.pretrig!.pretrigSamples, totalSamples);
        assembler = new PretrigAssembler({
          nChannels: actualChannels,
          pretrigChannel: cfg.pretrig!.channel,
          threshold: cfg.pretrig!.threshold,
          pretrigSamples: p,
          totalSamples,
        });
      } else {
        // Pre-allocate interleaved buffer: (totalSamples, actualChannels) row-major.
        buf = new Float64Array(totalSamples * actualChannels);
      }
      if (canUseWorklet(ctx)) {
        await ctx.audioWorklet.addModule(captureWorkletUrl());
        workletNode = makeCaptureNode(ctx, actualChannels, BUFFER_SIZE);
      } else {
        // Fallback for browsers without AudioWorklet (older Safari).
        scriptNode = ctx.createScriptProcessor(BUFFER_SIZE, actualChannels, actualChannels);
      }
      if (hasOutput) {
        stimulusNode = await buildStimulusNode(ctx, actualFs, cfg.durationS, cfg.output!);
      }
    } catch (e) {
      try { stimulusNode?.disconnect(); } catch { /* */ }
      try { ctx?.close(); } catch { /* */ }
      stream.getTracks().forEach((t) => t.stop());
      throw new Error(`Could not start audio capture: ${e instanceof Error ? e.message : e}`);
    }
    let writePos = 0; // next sample index (per channel) — plain path only

    return new Promise<Recording>((resolve, reject) => {
      let timeoutTimer: ReturnType<typeof setTimeout> | null = null;

      function cleanup() {
        if (timeoutTimer) { clearTimeout(timeoutTimer); timeoutTimer = null; }
        try { stimulusNode?.stop(); } catch { /* already ended */ }
        try { stimulusNode?.disconnect(); } catch { /* */ }
        try { workletNode?.disconnect(); } catch { /* */ }
        try { scriptNode?.disconnect(); } catch { /* */ }
        try { source.disconnect(); } catch { /* */ }
        try { ctx?.close(); } catch { /* */ }
        stream.getTracks().forEach((t) => t.stop());
      }

      /** Resolve an armed capture from the assembler's stitched window. */
      function finishArmed() {
        cleanup();
        const res = assembler!.result()!;
        const timeAxis = new Float64Array(totalSamples);
        for (let i = 0; i < totalSamples; i++) timeAxis[i] = i / actualFs;
        resolve({
          data: res.data, timeAxis, fs: actualFs,
          nChannels: actualChannels, nSamples: totalSamples,
        });
      }

      // One consumer for both capture paths: an armed capture feeds the
      // pretrigger assembler, an ordinary one fills the pre-allocated buffer.
      function consume(chunk: Float32Array, nSamples: number) {
        if (cancelled) {
          cleanup();
          reject(new Error('cancelled'));
          return;
        }

        if (assembler) {
          const wasTriggered = assembler.triggered;
          assembler.push(chunk, nSamples);
          if (!wasTriggered && assembler.triggered) {
            if (timeoutTimer) { clearTimeout(timeoutTimer); timeoutTimer = null; }
            onStatus?.('triggered');
          }
          elapsedS = assembler.collected / actualFs;
          if (assembler.done) finishArmed();
          return;
        }

        const remaining = totalSamples - writePos;
        if (remaining <= 0) return; // already done — ignore trailing chunks

        const n = Math.min(nSamples, remaining);
        for (let i = 0; i < n; i++) {
          const srcBase = i * actualChannels;
          const dstBase = (writePos + i) * actualChannels;
          for (let ch = 0; ch < actualChannels; ch++) {
            buf[dstBase + ch] = chunk[srcBase + ch];
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
      }

      if (workletNode) {
        // PRIMARY: worklet posts accumulated interleaved chunks on its port.
        workletNode.port.onmessage = (ev: MessageEvent<WorkletChunkMessage>) => {
          consume(ev.data.data, ev.data.nSamples);
        };
        source.connect(workletNode);
        workletNode.connect(ctx!.destination);
      } else {
        // FALLBACK: ScriptProcessorNode delivers each buffer on the main thread.
        scriptNode!.onaudioprocess = (ev: AudioProcessingEvent) => {
          if (cancelled) {
            cleanup();
            reject(new Error('cancelled'));
            return;
          }
          const { data, nSamples } = interleaveScriptBuffer(ev.inputBuffer, actualChannels);
          consume(data, nSamples);
        };
        // Must connect to destination for onaudioprocess to fire on most browsers.
        source.connect(scriptNode!);
        scriptNode!.connect(ctx!.destination);
      }

      // Start the output stimulus in sync with the now-wired capture graph.
      if (stimulusNode) { try { stimulusNode.start(); } catch { /* */ } }

      // Arm the pretrigger: announce 'armed' and start the timeout fallback.
      // On timeout with no crossing, force a synthetic trigger at the current
      // instant (ordinary-capture fallback — matches log_data's no-raise path).
      if (assembler) {
        onStatus?.('armed');
        const timeoutMs = Math.max(0, (cfg.pretrig!.timeoutS || 0) * 1000);
        timeoutTimer = setTimeout(() => {
          timeoutTimer = null;
          if (assembler && !assembler.triggered && !assembler.done) {
            onStatus?.('timeout');
            assembler.forceTrigger();
            if (assembler.done) finishArmed();
          }
        }, timeoutMs);
      }
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
 * `startRecording`, this does not accumulate a fixed-length buffer — it
 * calls `ondata` with each interleaved capture chunk and runs until
 * `stop()` is called.
 *
 * The PRIMARY capture path is an AudioWorkletNode (glitch-free, off the
 * main thread); it posts chunks accumulated to the ~2048-frame cadence the
 * oscilloscope/levels/ring buffer expect.  A ScriptProcessorNode FALLBACK
 * is used only where `audioWorklet` is unavailable (older Safari); it
 * delivers the same interleaved chunk shape.
 *
 * Returns a promise that resolves with the `MonitorHandle` once the stream
 * is open and the capture node is wired (rejects on permission error, if
 * the browser lacks support, or if the worklet module fails to load). The
 * caller must call `handle.stop()` when done.
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

  // The mic is now open. If anything below throws — an unsupported sample rate
  // on Safari, too many channels, OR a REJECTED `audioWorklet.addModule()`
  // (fetch failure / worklet syntax error) — release the stream before
  // rethrowing, otherwise the mic stays live with no handle to stop it (C2).
  // addModule is async, so it is awaited inside this same guard.
  let ctx: AudioContext | undefined;
  let actualFs!: number;
  let source!: MediaStreamAudioSourceNode;
  let actualChannels!: number;
  let workletNode: AudioWorkletNode | undefined;
  let scriptNode: ScriptProcessorNode | undefined;
  try {
    ctx = new AudioContext({ sampleRate: cfg.sampleRate });
    actualFs = ctx.sampleRate;
    source = ctx.createMediaStreamSource(stream);
    actualChannels = Math.min(
      cfg.channelCount,
      source.channelCount || stream.getAudioTracks()[0]?.getSettings?.()?.channelCount || 1,
    );
    if (canUseWorklet(ctx)) {
      await ctx.audioWorklet.addModule(captureWorkletUrl());
      workletNode = makeCaptureNode(ctx, actualChannels, BUFFER_SIZE);
    } else {
      scriptNode = ctx.createScriptProcessor(BUFFER_SIZE, actualChannels, actualChannels);
    }
  } catch (e) {
    try { ctx?.close(); } catch { /* */ }
    stream.getTracks().forEach((t) => t.stop());
    throw new Error(`Could not start audio monitor: ${e instanceof Error ? e.message : e}`);
  }
  let stopped = false;

  // One consumer for both paths: forward an interleaved (nSamples, nChannels)
  // chunk to the monitor callback (dropped once stopped).
  function emit(data: Float32Array, nSamples: number) {
    if (stopped) return;
    ondata({ data, nSamples, nChannels: actualChannels, fs: actualFs });
  }

  if (workletNode) {
    // PRIMARY: worklet posts accumulated interleaved chunks on its port.
    workletNode.port.onmessage = (ev: MessageEvent<WorkletChunkMessage>) => {
      emit(ev.data.data, ev.data.nSamples);
    };
    source.connect(workletNode);
    workletNode.connect(ctx.destination);
  } else {
    // FALLBACK: ScriptProcessorNode delivers each buffer on the main thread.
    scriptNode!.onaudioprocess = (ev: AudioProcessingEvent) => {
      if (stopped) return;
      const { data, nSamples } = interleaveScriptBuffer(ev.inputBuffer, actualChannels);
      emit(data, nSamples);
    };
    source.connect(scriptNode!);
    scriptNode!.connect(ctx.destination);
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    try { workletNode?.disconnect(); } catch { /* */ }
    try { scriptNode?.disconnect(); } catch { /* */ }
    try { source.disconnect(); } catch { /* */ }
    try { ctx?.close(); } catch { /* */ }
    stream.getTracks().forEach((t) => t.stop());
  }

  return { stop, fs: actualFs, nChannels: actualChannels };
}
