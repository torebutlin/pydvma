// @ts-nocheck
/*
 * capture.worklet.js — AudioWorklet processor for the pydvma browser
 * capture path (both the continuous monitor and the fixed-duration
 * recording).  This is the successor to the deprecated ScriptProcessorNode
 * that `source.ts` used before (see `startMonitor` / `startRecording`).
 *
 * WHY A WORKLET.  ScriptProcessorNode runs its `onaudioprocess` on the
 * main (UI) thread and is deprecated across browsers; under UI load it
 * drops audio blocks — which glitches the oscilloscope and, worse, punches
 * holes in a measurement *recording*.  AudioWorkletProcessor.process()
 * runs on the dedicated real-time audio render thread at a fixed 128-frame
 * render quantum, so capture stays glitch-free regardless of what the UI
 * thread is doing.
 *
 * @ts-nocheck / .js (not .ts): this file executes inside
 * `AudioWorkletGlobalScope`, a separate JS realm from the DOM window.  Its
 * globals (`AudioWorkletProcessor`, `registerProcessor`, `sampleRate`,
 * `currentFrame`, …) are NOT in TypeScript's DOM lib, so type-checking it
 * against those libs is meaningless — hence `@ts-nocheck`.  It is authored
 * in plain ES2022 JS (no imports/exports) so Vite emits it VERBATIM as a
 * hashed asset for `audioWorklet.addModule()`; a `.ts` file referenced by
 * `new URL(...)` would ship untranspiled and blow up in the worklet scope.
 *
 * ── ACCUMULATION (the load-bearing contract) ──────────────────────────
 * The worklet render quantum is 128 frames.  The downstream consumers
 * (oscilloscope draw, level meters, the ring buffer, the recording
 * accumulator) were all tuned around the ~2048-sample cadence that the old
 * ScriptProcessorNode delivered (BUFFER_SIZE 2048 for the monitor, 4096 for
 * recording).  To keep that cadence — and therefore keep every consumer's
 * behaviour equivalent — this processor does NOT post every 128-frame
 * quantum.  Instead it ACCUMULATES successive quanta into an interleaved
 * (chunkFrames, nChannels) Float32 buffer and only posts to the main thread
 * once `chunkFrames` frames have been gathered.  `chunkFrames` is supplied
 * per node via `processorOptions.chunkFrames` (2048 for the monitor, 4096
 * for recording).  A chunkFrames that is a multiple of 128 fills exactly;
 * the fill loop nonetheless handles the general case (a partial fill is
 * simply carried into the next quantum), so nothing breaks if the quantum
 * or chunk size ever changes.
 *
 * ── INTERLEAVING ──────────────────────────────────────────────────────
 * `process(inputs)` receives `inputs[0]` = an array of nChannels PLANAR
 * Float32Arrays (one per channel, each 128 frames).  We interleave them
 * into the accumulator as row-major (frame, channel): acc[frame*nCh + ch].
 * This is byte-for-byte the layout the old ScriptProcessorNode path built
 * and exactly the `MonitorChunk.data` contract in source.ts, so consumers
 * are unchanged.  The node is constructed by source.ts with an EXPLICIT,
 * DISCRETE channel count equal to nChannels, so the planar input always has
 * exactly nChannels channels (no speaker up/down-mix of measurement data).
 *
 * ── ZERO-COPY POST ────────────────────────────────────────────────────
 * Each full chunk's underlying ArrayBuffer is TRANSFERRED to the main
 * thread (second arg to postMessage), so the audio render thread never
 * blocks copying, then a fresh accumulator is allocated for the next chunk.
 *
 * Message shape posted to the port:
 *   { data: Float32Array, nSamples: number, nChannels: number }
 * where `data` is interleaved (nSamples, nChannels) and `nSamples` is the
 * PER-CHANNEL frame count (== chunkFrames).  source.ts stamps `fs` on it.
 */

const DEFAULT_CHUNK_FRAMES = 2048;

class PydvmaCaptureProcessor extends AudioWorkletProcessor {
  /**
   * @param {AudioWorkletNodeOptions} options — `processorOptions.chunkFrames`
   *   sets the posted-chunk size (frames); `processorOptions.nChannels` sets
   *   the fixed interleave width.  Both mirror the node's explicit channel
   *   count and the old ScriptProcessorNode BUFFER_SIZE.
   */
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    // Frames per posted chunk — matches the old ScriptProcessorNode BUFFER_SIZE.
    this.chunkFrames =
      opts.chunkFrames > 0 ? Math.floor(opts.chunkFrames) : DEFAULT_CHUNK_FRAMES;
    // Interleave width — fixed for the life of the node (explicit/discrete).
    this.nChannels = opts.nChannels > 0 ? Math.floor(opts.nChannels) : 1;
    this.acc = new Float32Array(this.chunkFrames * this.nChannels);
    this.filled = 0; // frames currently held in the accumulator
  }

  /**
   * Interleave each 128-frame quantum into the accumulator and post a chunk
   * whenever it fills.  Returns true to keep the processor alive across the
   * silent/idle gaps between captures.
   *
   * @param {Float32Array[][]} inputs — inputs[0] is the connected input's
   *   planar per-channel data (each entry length == render quantum, 128).
   * @returns {boolean} always true (never let the node be GC'd mid-session).
   */
  process(inputs) {
    const input = inputs[0];
    // No connected input this render (or the graph handed us nothing): stay
    // alive but accumulate nothing.
    if (!input || input.length === 0) return true;

    const nCh = this.nChannels;
    const chunkFrames = this.chunkFrames;
    const frames = input[0] ? input[0].length : 0;

    for (let i = 0; i < frames; i++) {
      const base = this.filled * nCh;
      for (let ch = 0; ch < nCh; ch++) {
        const chData = input[ch];
        // Guard the (defensive) case of fewer supplied channels than nCh.
        this.acc[base + ch] = chData ? chData[i] : 0;
      }
      this.filled++;

      if (this.filled === chunkFrames) {
        // Transfer the buffer (zero-copy) and start a fresh accumulator.
        this.port.postMessage(
          { data: this.acc, nSamples: chunkFrames, nChannels: nCh },
          [this.acc.buffer],
        );
        this.acc = new Float32Array(chunkFrames * nCh);
        this.filled = 0;
      }
    }

    return true;
  }
}

registerProcessor('pydvma-capture', PydvmaCaptureProcessor);
