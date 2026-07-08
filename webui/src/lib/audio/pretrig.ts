/**
 * Pretrigger capture assembly (browser / Web Audio path).
 *
 * A pure, unit-testable port of pydvma's pretrigger windowing semantics
 * (`acquisition.log_data`, `pydvma/acquisition.py:163`, and the
 * `streams.Recorder` state-machine docstring).  Used by the Web Audio provider
 * (round-5 item 10) so an "armed" browser capture waits for a threshold
 * crossing and returns a window straddling it, exactly like the Qt /
 * `pydvma serve` app.
 *
 * ── pydvma semantics being reproduced ─────────────────────────────────────
 * On a successful trigger, pydvma returns a `number_samples =
 * round(stored_time·fs)` window in which the FIRST sample whose magnitude
 * exceeds `pretrig_threshold` (on `pretrig_channel`) sits at exactly index
 * `pretrig_samples`.  Concretely (log_data):
 *
 *     detected_sample = <index of first |x| > threshold>
 *     start_index     = detected_sample − pretrig_samples
 *     window          = buffer[start_index : start_index + number_samples]
 *
 * So `window[0 : pretrig_samples)` is the pre-trigger context (the
 * `pretrig_samples` samples strictly BEFORE the crossing), `window[pretrig_
 * samples]` is the crossing sample, and the remainder is post-trigger data.
 * pydvma's `stored_time_data` starts zeroed, so when fewer than
 * `pretrig_samples` real samples precede the crossing the context is
 * zero-padded on the left — this port reproduces that with a zeroed rolling
 * ring.  The crossing test is a strict `> threshold` on the absolute value.
 *
 * On **timeout** pydvma does not raise: it returns the tail of the buffer with
 * `trigger_detected = False`.  This port's {@link PretrigAssembler.forceTrigger}
 * is the browser analogue — it synthesises a trigger at the current position
 * (window straddles the timeout instant, `triggered` stays `false`), reusing
 * the identical stitching so the returned set is always full length.  (pydvma
 * returns the plain buffer tail; the browser keeps only `pretrig_samples` of
 * rolling history rather than the whole pre-trigger buffer, so the fallback
 * window is anchored at the timeout instant instead — a benign difference for
 * an un-triggered capture, documented so axes are never misread.)
 *
 * ── Per-sample vs pydvma's chunk-granular detect ──────────────────────────
 * pydvma commits the trigger by scanning the "second-oldest chunk" of its ring
 * (`chunk_size`-granular), which is why it caps `pretrig_samples ≤ chunk_size`.
 * This port checks every sample, so the documented invariant (crossing at
 * index `pretrig_samples`) holds exactly and more precisely; `pretrigSamples`
 * is still clamped to a sane cap (< `totalSamples`, see {@link clampPretrigSamples}).
 */

/** Interleaved sample block: row-major `(nSamples, nChannels)`. */
export type SampleBlock = Float32Array | Float64Array;

/** Assembled pretrigger window. */
export interface PretrigResult {
  /** Row-major `(totalSamples, nChannels)` float64. */
  data: Float64Array;
  /** Whether a real threshold crossing fired it (false on a forced/timeout finish). */
  triggered: boolean;
  /** Global stream sample index of the crossing (or the forced instant); −1 if never. */
  triggerIndex: number;
}

/** Configuration for {@link PretrigAssembler} / {@link assembleFromStream}. */
export interface PretrigParams {
  nChannels: number;
  /** Channel the threshold is watched on (clamped into range). */
  pretrigChannel: number;
  /** Absolute threshold on |x| (strict `>`). */
  threshold: number;
  /** Samples of pre-trigger context (window index of the crossing). */
  pretrigSamples: number;
  /** Total returned length per channel (`round(durationS·fs)`). */
  totalSamples: number;
}

/**
 * Clamp a requested pre-trigger context length to a sane, self-consistent
 * range: `[0, min(totalSamples − 1, cap)]`.  It must be strictly less than the
 * total window (there has to be at least one post-trigger sample) and is
 * additionally capped (default 48000 ≈ 1 s at 48 kHz) so a rolling pre-buffer
 * can never balloon while waiting for a trigger.
 */
export function clampPretrigSamples(pretrigSamples: number, totalSamples: number, cap = 48000): number {
  const hi = Math.max(0, Math.min(totalSamples - 1, cap));
  if (!Number.isFinite(pretrigSamples) || pretrigSamples < 0) return 0;
  return Math.min(Math.floor(pretrigSamples), hi);
}

/**
 * Find the global sample index of the first `|x| > threshold` on `channel` in
 * an interleaved `(N, nChannels)` stream, or −1 if none crosses.
 */
export function findFirstCrossing(
  stream: SampleBlock,
  nChannels: number,
  channel: number,
  threshold: number,
): number {
  const ch = Math.max(0, Math.min(channel, nChannels - 1));
  const n = Math.floor(stream.length / nChannels);
  for (let i = 0; i < n; i++) {
    if (Math.abs(stream[i * nChannels + ch]) > threshold) return i;
  }
  return -1;
}

/**
 * Stitch a pretrigger window out of a fully-materialised interleaved stream —
 * the pure reference for the streaming {@link PretrigAssembler}.  Locates the
 * first crossing, places it at output index `pretrigSamples`, and zero-pads the
 * left when the crossing occurs before `pretrigSamples` samples exist.  When no
 * crossing is found, falls back to the leading `totalSamples` (an ordinary
 * capture), `triggered = false`.
 */
export function assembleFromStream(stream: SampleBlock, params: PretrigParams): PretrigResult {
  const { nChannels, pretrigChannel, threshold, pretrigSamples, totalSamples } = params;
  const out = new Float64Array(totalSamples * nChannels);
  const cross = findFirstCrossing(stream, nChannels, pretrigChannel, threshold);
  const nStream = Math.floor(stream.length / nChannels);

  if (cross < 0) {
    // Timeout analogue: leading window, no trigger.
    const n = Math.min(totalSamples, nStream);
    for (let i = 0; i < n * nChannels; i++) out[i] = stream[i];
    return { data: out, triggered: false, triggerIndex: -1 };
  }

  const startIndex = cross - pretrigSamples; // may be negative → left zero-pad
  for (let i = 0; i < totalSamples; i++) {
    const srcIdx = startIndex + i;
    if (srcIdx < 0 || srcIdx >= nStream) continue; // leave zeros
    for (let ch = 0; ch < nChannels; ch++) {
      out[i * nChannels + ch] = stream[srcIdx * nChannels + ch];
    }
  }
  return { data: out, triggered: true, triggerIndex: cross };
}

/**
 * Streaming pretrigger assembler for the live capture path.  Feed interleaved
 * capture chunks via {@link push}; it keeps a zeroed rolling ring of the most
 * recent `pretrigSamples` samples until the trigger channel crosses the
 * threshold, then emits a `totalSamples`-long window with the crossing at index
 * `pretrigSamples` (see the module docstring).  {@link forceTrigger} handles the
 * timeout fallback.  Once {@link done}, {@link result} returns the window.
 */
export class PretrigAssembler {
  readonly nChannels: number;
  readonly pretrigChannel: number;
  readonly threshold: number;
  readonly pretrigSamples: number;
  readonly totalSamples: number;

  private out: Float64Array;
  private ring: Float64Array;    // rolling pre-trigger history, (pretrigSamples, nCh)
  private ringPushed = 0;        // total samples pushed to the ring (monotonic)
  private _triggered = false;
  private _done = false;
  private writePos = 0;          // per-channel samples written to `out`
  private globalIndex = 0;       // per-channel samples seen across the stream
  private _triggerIndex = -1;

  constructor(params: PretrigParams) {
    this.nChannels = Math.max(1, params.nChannels);
    this.pretrigChannel = Math.max(0, Math.min(params.pretrigChannel, this.nChannels - 1));
    this.threshold = params.threshold;
    this.pretrigSamples = Math.max(0, Math.min(params.pretrigSamples, params.totalSamples));
    this.totalSamples = params.totalSamples;
    this.out = new Float64Array(this.totalSamples * this.nChannels);
    this.ring = new Float64Array(Math.max(1, this.pretrigSamples) * this.nChannels);
  }

  /** True once a real threshold crossing has fired (not a forced/timeout finish). */
  get triggered(): boolean { return this._triggered; }
  /** True once the full window has been assembled. */
  get done(): boolean { return this._done; }
  /** Global stream index of the crossing (or forced instant); −1 until then. */
  get triggerIndex(): number { return this._triggerIndex; }
  /** Per-channel samples committed to the output so far (progress). */
  get collected(): number { return this.writePos; }

  /**
   * Feed one interleaved `(nSamples, nChannels)` capture chunk.  No-op once
   * done.  Detects the first crossing, seeds the output with the ring's
   * pre-context, and fills forward until `totalSamples` are gathered.
   */
  push(chunk: SampleBlock, nSamples: number): void {
    if (this._done) return;
    const nCh = this.nChannels;
    for (let i = 0; i < nSamples; i++) {
      const base = i * nCh;
      if (!this.armedCollecting()) {
        // Waiting: test this sample, then roll it into the pre-history ring.
        const v = chunk[base + this.pretrigChannel];
        if (Math.abs(v) > this.threshold) {
          this.beginCollecting(this.globalIndex, chunk, base, true);
        } else {
          this.pushRing(chunk, base);
          this.globalIndex++;
        }
      } else {
        // Collecting: append the sample straight into the output window.
        this.appendOut(chunk, base);
        this.globalIndex++;
        if (this._done) return;
      }
    }
  }

  /**
   * Timeout fallback: synthesise a trigger at the current position so the
   * returned window straddles "now" with `pretrigSamples` of real history.
   * `triggered` stays false (no genuine crossing).  No-op if already
   * triggered/done.
   */
  forceTrigger(): void {
    if (this._triggered || this._done) return;
    this.beginCollecting(this.globalIndex, null, 0, false);
  }

  /** The assembled window, or `null` until {@link done}. */
  result(): PretrigResult | null {
    if (!this._done) return null;
    return { data: this.out, triggered: this._triggered, triggerIndex: this._triggerIndex };
  }

  // ---- internals ----

  private armedCollecting(): boolean {
    return this._triggerIndex >= 0;
  }

  /**
   * Seed the output with the ring's pre-context and (optionally) the crossing
   * sample, switching into collecting mode.  `real` distinguishes a genuine
   * crossing from a forced/timeout finish.
   */
  private beginCollecting(
    index: number,
    chunk: SampleBlock | null,
    base: number,
    real: boolean,
  ): void {
    this._triggered = real;
    this._triggerIndex = index;
    this.writePos = 0;
    // Copy the last `pretrigSamples` samples (chronological, left zero-padded)
    // into the head of the output window.
    const nCh = this.nChannels;
    const P = this.pretrigSamples;
    const have = Math.min(this.ringPushed, P);
    for (let j = 0; j < have; j++) {
      const ringPos = ((this.ringPushed - have + j) % P + P) % P;
      const dst = (P - have + j) * nCh;
      const src = ringPos * nCh;
      for (let ch = 0; ch < nCh; ch++) this.out[dst + ch] = this.ring[src + ch];
    }
    this.writePos = P;
    if (this.writePos >= this.totalSamples) { this._done = true; return; }
    // On a real crossing, the crossing sample itself is the first post-context
    // sample (output index P). A forced finish has no such sample.
    if (chunk) {
      this.appendOut(chunk, base);
      this.globalIndex++;
    }
  }

  private appendOut(chunk: SampleBlock, base: number): void {
    const nCh = this.nChannels;
    const dst = this.writePos * nCh;
    for (let ch = 0; ch < nCh; ch++) this.out[dst + ch] = chunk[base + ch];
    this.writePos++;
    if (this.writePos >= this.totalSamples) this._done = true;
  }

  private pushRing(chunk: SampleBlock, base: number): void {
    const P = this.pretrigSamples;
    if (P <= 0) { this.ringPushed++; return; }
    const nCh = this.nChannels;
    const pos = (this.ringPushed % P) * nCh;
    for (let ch = 0; ch < nCh; ch++) this.ring[pos + ch] = chunk[base + ch];
    this.ringPushed++;
  }
}
