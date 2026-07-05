import { expect, test } from 'vitest';
import {
  defaultFrameRange,
  sliderPosition,
  PRECOMPUTE_SAMPLE_CAP,
  shouldDeferLive,
  resolveFrom,
} from '../../src/lib/analysis/resolutionControl';
import { fromNFrames } from '../../src/lib/analysis/resolution';

// --- default slider range derives from the set (fs, duration) --------------

test('defaultFrameRange spans 1 .. a sane max for the record', () => {
  // 30 s at 44.1 kHz: min is always 1; max is bounded and > 1.
  const r = defaultFrameRange(30, 44100);
  expect(r.min).toBe(1);
  expect(r.max).toBeGreaterThan(1);
  // The max must not exceed the physical ceiling (one frame per sample).
  expect(r.max).toBeLessThanOrEqual(Math.round(30 * 44100));
});

test('defaultFrameRange is NOT the old hard-coded 1..30 regardless of data', () => {
  // A long, high-fs record admits many more frames than 30; a tiny record
  // fewer. The range must respond to the data, not sit fixed at 1..30.
  const big = defaultFrameRange(600, 48000);
  const small = defaultFrameRange(0.05, 8000);   // 400 samples
  expect(big.max).toBeGreaterThan(30);
  expect(small.max).toBeLessThan(big.max);
});

test('defaultFrameRange degrades gracefully for tiny / degenerate records', () => {
  // A record shorter than one frame still yields a usable [1, >=1] range.
  const r = defaultFrameRange(0.001, 1000);       // ~1 sample
  expect(r.min).toBe(1);
  expect(r.max).toBeGreaterThanOrEqual(1);
  // Non-finite inputs collapse to the trivial [1, 1] range, never NaN.
  const bad = defaultFrameRange(NaN, 44100);
  expect(Number.isFinite(bad.min)).toBe(true);
  expect(Number.isFinite(bad.max)).toBe(true);
});

// --- slider clamps to its end-stops; the typed value is NOT clamped --------

test('sliderPosition pins to the range end-stops for out-of-range values', () => {
  const range = { min: 1, max: 30 };
  // A typed value above the range pins the SLIDER to max (value unchanged
  // elsewhere — this fn only returns where the thumb sits).
  expect(sliderPosition(100, range)).toBe(30);
  // Below the range pins to min.
  expect(sliderPosition(-5, range)).toBe(1);
  // In-range passes through unchanged.
  expect(sliderPosition(12, range)).toBe(12);
});

test('sliderPosition never fights an in-range fractional value', () => {
  const range = { min: 1, max: 30 };
  // The slider position mirrors the value when it is inside the range;
  // it is the number box that is the source of truth, not the slider.
  expect(sliderPosition(1, range)).toBe(1);
  expect(sliderPosition(30, range)).toBe(30);
});

// --- coupled mapping matches resolution.ts ground truth --------------------

test('resolveFrom(frames,...) matches resolution.ts (30 s, N=10 -> 5.4545 s)', () => {
  const r = resolveFrom('frames', 10, 30, 44100);
  expect(r.frameLengthS).toBeCloseTo(5.4545, 3);
  expect(r).toEqual(fromNFrames(10, 30, 44100));
});

test('resolveFrom dispatches to the right resolution.ts mapper per quantity', () => {
  const durationS = 30, fs = 44100;
  // Each quantity round-trips through the shared coupling to the same
  // consistent Resolution the corresponding resolution.ts fn produces.
  const byFrames = resolveFrom('frames', 8, durationS, fs);
  expect(resolveFrom('frameLength', byFrames.frameLengthS, durationS, fs).nFrames).toBe(byFrames.nFrames);
  expect(resolveFrom('nFft', byFrames.nFft, durationS, fs).nFrames).toBe(byFrames.nFrames);
  // dF is the inverse of frame length, so seeding by dF recovers the frames.
  expect(resolveFrom('dF', byFrames.dF, durationS, fs).nFrames).toBe(byFrames.nFrames);
});

test('resolveFrom(dF,...) inverts to frame length (dF = 1/frameLength)', () => {
  // A requested Δf of 2 Hz means a 0.5 s frame; the mapping must honour that.
  const r = resolveFrom('dF', 2, 30, 44100);
  expect(r.frameLengthS).toBeCloseTo(0.5, 2);
});

// --- precompute gate: small = live, large = defer --------------------------

test('shouldDeferLive gates on sample count around PRECOMPUTE_SAMPLE_CAP', () => {
  expect(PRECOMPUTE_SAMPLE_CAP).toBeGreaterThan(0);
  // At or below the cap: cheap, update live (no defer).
  expect(shouldDeferLive(PRECOMPUTE_SAMPLE_CAP)).toBe(false);
  expect(shouldDeferLive(1000)).toBe(false);
  // Above the cap: defer live re-issues to keep dragging smooth.
  expect(shouldDeferLive(PRECOMPUTE_SAMPLE_CAP + 1)).toBe(true);
});
