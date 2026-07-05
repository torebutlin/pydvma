/**
 * Pure logic behind `ResolutionControl.svelte` (Stage-2 Plan 1.5, Task R2).
 *
 * The resolution control couples four quantities through
 * `resolution.ts` — N_frames ↔ frame length ↔ nFFT ↔ Δf — and pairs a
 * single slider (drag = coarse) with per-quantity text boxes (type =
 * precise). This module holds the parts that are pure functions of the
 * set metadata (fs, duration) so they can be unit-tested without a DOM:
 *
 *   - `defaultFrameRange` — a sensible slider range derived from the set,
 *     NOT a hard-coded 1..30 (see R2 point 4);
 *   - `sliderPosition` — where the slider thumb sits for a given value.
 *     The TEXT BOX is the source of truth and accepts values OUTSIDE the
 *     slider range; the slider simply CLAMPS to its end-stops and never
 *     fights a typed value (R2 point 3);
 *   - `resolveFrom` — one dispatcher over the four coupled quantities,
 *     delegating to `resolution.ts` so the component and its tests share
 *     a single coupling entry point;
 *   - `shouldDeferLive` / `PRECOMPUTE_SAMPLE_CAP` — the precompute gate
 *     (R2 point 5): small sets update live (the maths is closed-form and
 *     cheap, so dragging feels instant), large sets defer to release.
 */
import { fromNFrames, fromFrameLength, fromNFft, type Resolution } from './resolution';

/** An inclusive integer slider range for the frame count. */
export interface FrameRange { min: number; max: number; }

/**
 * A sensible default slider range for the frame count, derived from the
 * set's duration and sample rate — NOT a fixed 1..30 (R2 point 4).
 *
 * `min` is always 1 (one averaging frame). `max` is capped so the slider
 * covers a useful spread without demanding sub-sample frames: we allow
 * frames down to ~32 samples (a floor where an FFT is still meaningful)
 * but never exceed the physical ceiling of one frame per sample. A
 * default ceiling of 128 keeps the slider ergonomic on typical captures;
 * short records fall below it, long/high-fs records rise toward it. Text
 * entry still reaches beyond `max` — the slider just clamps there.
 *
 * Degenerate inputs (non-finite or ≤0 fs/duration) collapse to [1, 1],
 * never NaN, so the control stays usable before real data arrives.
 */
export function defaultFrameRange(durationS: number, fs: number): FrameRange {
  const totalSamples = Math.round(durationS * fs);
  if (!Number.isFinite(totalSamples) || totalSamples < 1) return { min: 1, max: 1 };
  // Smallest frame we let the slider reach (samples). Below this an FFT
  // is too coarse to be useful, so we don't waste slider travel on it.
  const MIN_FRAME_SAMPLES = 32;
  // Frames such that each frame is >= MIN_FRAME_SAMPLES samples. With 50%
  // overlap the frame count roughly tracks totalSamples / frameSamples, so
  // this is a conservative, monotonic ceiling that grows with the record.
  const byFrameFloor = Math.max(1, Math.floor(totalSamples / MIN_FRAME_SAMPLES));
  // Ergonomic default cap so the slider stays readable on ordinary data;
  // long/high-fs records climb toward it, short ones sit below.
  const ERGONOMIC_CAP = 128;
  const max = Math.min(byFrameFloor, ERGONOMIC_CAP, Math.max(1, totalSamples));
  return { min: 1, max: Math.max(1, max) };
}

/**
 * Where the slider thumb should sit for a (possibly out-of-range) value.
 *
 * The number box is the source of truth and may hold values OUTSIDE the
 * slider's range; the slider must not fight that — it simply pins to the
 * nearest end-stop (R2 point 3). In-range values pass through unchanged.
 */
export function sliderPosition(value: number, range: FrameRange): number {
  if (!Number.isFinite(value)) return range.min;
  return Math.min(range.max, Math.max(range.min, value));
}

/** The four coupled resolution quantities the control can edit. */
export type ResolutionQuantity = 'frames' | 'frameLength' | 'nFft' | 'dF';

/**
 * Resolve a full {nFrames, frameLengthS, nFft, dF} snapshot from ANY one
 * of the four coupled quantities, delegating to `resolution.ts`. This is
 * the single coupling entry point the component and its tests share, so
 * editing any box (or dragging the slider) routes through one place.
 *
 * `dF` is inverted to a frame length (Δf = 1 / frameLength) before the
 * shared frame-length mapping runs, keeping it consistent with the other
 * three. Preconditions match `resolution.ts`: fs > 0, durationS > 0.
 */
export function resolveFrom(
  quantity: ResolutionQuantity,
  value: number,
  durationS: number,
  fs: number,
): Resolution {
  switch (quantity) {
    case 'frames':
      return fromNFrames(value, durationS, fs);
    case 'frameLength':
      return fromFrameLength(value, durationS, fs);
    case 'nFft':
      return fromNFft(value, durationS, fs);
    case 'dF':
      // Δf = fs / nFft = 1 / frameLength, so a requested Δf maps to a
      // frame length of 1/Δf; guard a non-positive Δf to the max frame.
      return fromFrameLength(value > 0 ? 1 / value : durationS, durationS, fs);
  }
}

/**
 * Precompute gate (R2 point 5). The resolution maths is closed-form and
 * cheap (`resolution.ts`, no worker call), so "precompute" here means:
 * for SMALL sets, update the coupled read-outs live on every slider
 * `input` — dragging feels instant. For LARGE sets, defer the live
 * re-read/recompute to slider release so a heavy record never stutters
 * mid-drag.
 *
 * The cap is on SAMPLE COUNT (durationS * fs). 500k samples is a few MB
 * of Float64 per channel — comfortably instant to re-map on every drag
 * frame, while anything larger is deferred to release. The threshold is
 * deliberately generous because the mapping itself is O(1); the cap
 * guards against the surrounding reactive re-render cost on big records,
 * not the arithmetic.
 */
export const PRECOMPUTE_SAMPLE_CAP = 500_000;

/** True when live updates should defer to slider release (large sets). */
export function shouldDeferLive(nSamples: number): boolean {
  return nSamples > PRECOMPUTE_SAMPLE_CAP;
}
