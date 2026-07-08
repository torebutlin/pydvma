/**
 * Tests for the browser output-stimulus generator (src/lib/audio/signal.ts) —
 * the TS port of pydvma's `signal_generator`.  Verifies the sweep law
 * (instantaneous-frequency endpoints + exact chirp samples), amplitude bounds,
 * the raised-cosine window, the zero-phase Butterworth filtering, and the RMS
 * of the noise families (the properties the round-5 task calls out).
 */
import { expect, test } from 'vitest';
import {
  generateStimulus,
  stimulusLength,
  instantaneousFreqLinear,
  linearChirpSample,
  linearChirp,
  raisedCosineWindow,
  butterLowpass,
  filtfiltBiquad,
  rms,
} from '../../src/lib/audio/signal';

/** Deterministic uniform[0,1) source so the noise paths are reproducible. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function maxAbs(x: ArrayLike<number>): number {
  let m = 0;
  for (let i = 0; i < x.length; i++) m = Math.max(m, Math.abs(x[i]));
  return m;
}

/** RMS of the flat central 60% (outside the raised-cosine ramps, window ≈ 1). */
function centralRms(y: Float64Array): number {
  const a = Math.floor(y.length * 0.2);
  const b = Math.floor(y.length * 0.8);
  return rms(y.subarray(a, b));
}

// ---- length ----

test('stimulusLength matches numpy arange(0, T, 1/fs)', () => {
  expect(stimulusLength(8000, 1)).toBe(8000);     // exactly divisible
  expect(stimulusLength(8000, 0.05)).toBe(400);
  expect(stimulusLength(44100, 2)).toBe(88200);
});

// ---- sweep (linear chirp) ----

test('instantaneousFreqLinear hits the sweep endpoints exactly', () => {
  const T = 2;
  expect(instantaneousFreqLinear(0, 10, 500, T)).toBeCloseTo(10, 12);   // f0 at t=0
  expect(instantaneousFreqLinear(T, 10, 500, T)).toBeCloseTo(500, 12);  // f1 at t=T
  expect(instantaneousFreqLinear(T / 2, 10, 500, T)).toBeCloseTo(255, 12); // linear midpoint
});

test('linearChirpSample matches cos(2π(f0·t + ½·(f1−f0)/T·t²))', () => {
  const f0 = 10, f1 = 500, T = 2;
  for (const t of [0, 0.13, 0.5, 1.7]) {
    const phase = 2 * Math.PI * (f0 * t + (0.5 * (f1 - f0) / T) * t * t);
    expect(linearChirpSample(t, f0, f1, T)).toBeCloseTo(Math.cos(phase), 12);
  }
  expect(linearChirpSample(0, f0, f1, T)).toBeCloseTo(1, 12); // cos(0)
});

test('linearChirp fills a unit-amplitude cos array starting at 1', () => {
  const y = linearChirp(1000, 8000, 20, 200, 1000 / 8000);
  expect(y).toHaveLength(1000);
  expect(y[0]).toBeCloseTo(1, 12);
  expect(maxAbs(y)).toBeLessThanOrEqual(1 + 1e-12);
});

test('generateStimulus sweep is bounded by amp and starts/ends near zero (window)', () => {
  const amp = 0.3;
  const { y } = generateStimulus({ type: 'sweep', fs: 8000, durationS: 1, amp, band: [10, 500] });
  expect(maxAbs(y)).toBeLessThanOrEqual(amp + 1e-9);   // amplitude bound
  expect(centralRms(y)).toBeGreaterThan(0.1);          // not silent
  expect(Math.abs(y[0])).toBeLessThan(1e-9);           // faded in (win[0] == 0)
  expect(Math.abs(y[y.length - 1])).toBeLessThan(1e-5);// faded out (win end ≈ 4e-6·amp)
});

// ---- window ----

test('raisedCosineWindow is ~0 at the ends, 1 in the middle, ramps = min(T/10,0.1)', () => {
  const fs = 8000, T = 1;
  const win = raisedCosineWindow(stimulusLength(fs, T), fs, T);
  expect(win[0]).toBe(0);                              // win[0] == 0 exactly
  // Faithful to pydvma's int(N_ramp) ramp: the very last sample is ≈4e-6, not
  // machine-zero (the ramp reaches 0 only just past the array end).
  expect(win[win.length - 1]).toBeLessThan(1e-5);
  expect(win[Math.floor(win.length / 2)]).toBeCloseTo(1, 12);
  // Ramp width = int(min(1/10, 0.1)·8000) = 800 samples; index 800 back to 1.
  expect(win[800]).toBeCloseTo(1, 6);
});

// ---- Butterworth zero-phase filtering ----

test('filtfiltBiquad low-pass has unity DC gain and zero phase (constant → constant)', () => {
  const q = butterLowpass(1000, 8000);
  const ones = new Float64Array(2000).fill(1);
  const out = filtfiltBiquad(q, ones);
  expect(out[1000]).toBeCloseTo(1, 6);                 // DC passes, mid steady state
});

test('filtfiltBiquad low-pass attenuates an above-cutoff sine', () => {
  const fs = 8000;
  const q = butterLowpass(500, fs);
  const N = 4000;
  const x = new Float64Array(N);
  for (let n = 0; n < N; n++) x[n] = Math.sin((2 * Math.PI * 3000 * n) / fs); // 3 kHz ≫ 500 Hz
  const out = filtfiltBiquad(q, x);
  // Compare central amplitudes (avoid transient ends).
  const inAmp = maxAbs(x.subarray(1000, 3000));
  const outAmp = maxAbs(out.subarray(1000, 3000));
  expect(outAmp).toBeLessThan(inAmp * 0.2);            // strongly attenuated
});

// ---- noise RMS ----

test('unbanded uniform noise has RMS ≈ amp/√3 and stays within ±amp', () => {
  const amp = 0.5;
  const { y } = generateStimulus({
    type: 'uniform', fs: 8000, durationS: 2, amp, band: null, rng: mulberry32(42),
  });
  expect(maxAbs(y)).toBeLessThanOrEqual(amp + 1e-9);
  expect(centralRms(y)).toBeCloseTo(amp / Math.sqrt(3), 1); // 0.289 ± 0.05
});

test('band-limited uniform noise is renormalised so RMS ≈ amp', () => {
  const amp = 0.4;
  const { y } = generateStimulus({
    type: 'uniform', fs: 8000, durationS: 2, amp, band: [100, 800], rng: mulberry32(7),
  });
  // Renormalisation sets the pre-window RMS to amp; the flat central region
  // therefore reads ≈ amp (within band-limited statistical spread).
  expect(centralRms(y)).toBeGreaterThan(amp * 0.7);
  expect(centralRms(y)).toBeLessThan(amp * 1.3);
});

test('band-limited gaussian noise is renormalised to RMS ≈ amp and clamped to limit', () => {
  const amp = 0.3;
  const limit = 1;
  const { y } = generateStimulus({
    type: 'gaussian', fs: 8000, durationS: 2, amp, band: [100, 800], limit, rng: mulberry32(99),
  });
  expect(maxAbs(y)).toBeLessThanOrEqual(limit + 1e-9);
  expect(centralRms(y)).toBeGreaterThan(amp * 0.6);
  expect(centralRms(y)).toBeLessThan(amp * 1.4);
});

test('final safety clamp keeps |y| ≤ limit even for a large amp request', () => {
  const { y } = generateStimulus({ type: 'sweep', fs: 8000, durationS: 0.5, amp: 5, band: [10, 500], limit: 1 });
  expect(maxAbs(y)).toBeLessThanOrEqual(1 + 1e-9);
});
