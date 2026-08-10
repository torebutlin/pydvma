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
  generateMultisine,
  type MultisineSpec,
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

// ---- multisine generator (Schoukens BLA excitation) ----------------------
//
// TS twin of pydvma's `multisine_generator` (`pydvma/acquisition.py:609`).
// The PRNG differs deliberately (mulberry32 vs numpy's default_rng) — only
// the signal LAW must match: flat line amplitudes, uniform-phase draw order,
// the experiment-rotation sign convention, and exact periodicity.

function baseMultisineSpec(overrides: Partial<MultisineSpec> = {}): MultisineSpec {
  return {
    nSamples: 64,
    k1: 3,
    k2: 5,
    pPeriods: 2,
    tPeriods: 1,
    seed: 12345,
    m: 0,
    e: 0,
    nExc: 2,
    ampRms: 0.1,
    ...overrides,
  };
}

/**
 * Naive DFT of one period: the complex amplitude at bin `k` for a signal
 * built from `A*cos(2*pi*k0*n/N + phi)` terms at distinct integer bins is
 * recovered EXACTLY (no leakage) by `(2/N) * sum_n y[n] * exp(-i*2*pi*k*n/N)`
 * — orthogonality holds exactly over one integer period.
 */
function dftBin(y: ArrayLike<number>, k: number, N: number): { re: number; im: number } {
  let re = 0, im = 0;
  for (let n = 0; n < N; n++) {
    const theta = (2 * Math.PI * k * n) / N;
    re += y[n] * Math.cos(theta);
    im -= y[n] * Math.sin(theta);
  }
  return { re: (2 / N) * re, im: (2 / N) * im };
}

function complexMul(a: { re: number; im: number }, b: { re: number; im: number }) {
  return { re: a.re * b.re - a.im * b.im, im: a.re * b.im + a.im * b.re };
}

test('generateMultisine: every period is an exact repeat of period 0 (nExc=2)', () => {
  const spec = baseMultisineSpec({ nExc: 2, e: 0, tPeriods: 1, pPeriods: 2 });
  const channels = generateMultisine(spec, 8000);
  expect(channels).toHaveLength(2);
  const N = spec.nSamples;
  const nPeriodsTotal = spec.tPeriods + spec.pPeriods;
  for (const y of channels) {
    expect(y).toHaveLength(nPeriodsTotal * N);
    for (let p = 1; p < nPeriodsTotal; p++) {
      for (let n = 0; n < N; n++) {
        expect(y[p * N + n]).toBe(y[n]); // bit-exact repeat, not just close
      }
    }
  }
});

test('flat line amplitudes: DFT at the 3 excited bins agree within 1e-9 rel; an out-of-band bin is ~0', () => {
  const spec = baseMultisineSpec({ nExc: 1, e: 0, tPeriods: 0, pPeriods: 1 });
  const [y] = generateMultisine(spec, 8000);
  const N = spec.nSamples;
  const nLines = spec.k2 - spec.k1 + 1;
  const A = spec.ampRms * Math.sqrt(2 / nLines);

  const mags: number[] = [];
  for (let k = spec.k1; k <= spec.k2; k++) {
    const { re, im } = dftBin(y, k, N);
    mags.push(Math.hypot(re, im));
  }
  expect(mags).toHaveLength(3);
  for (const mag of mags) {
    expect(Math.abs(mag - A) / A).toBeLessThan(1e-9);
  }

  const outOfBand = dftBin(y, spec.k2 + 3, N); // well clear of the excited band
  expect(Math.hypot(outOfBand.re, outOfBand.im)).toBeLessThan(1e-9);
});

test('RMS of the full tiled signal equals ampRms exactly (integer-period orthogonality, not statistical)', () => {
  const spec = baseMultisineSpec({ nExc: 1, e: 0, tPeriods: 1, pPeriods: 3, ampRms: 0.25 });
  const [y] = generateMultisine(spec, 8000);
  expect(Math.abs(rms(y) - spec.ampRms) / spec.ampRms).toBeLessThan(1e-9);
});

test('seed determinism: same spec twice -> identical arrays; a different m -> different arrays', () => {
  const spec = baseMultisineSpec();
  const a = generateMultisine(spec, 8000);
  const aAgain = generateMultisine({ ...spec }, 8000);
  for (let q = 0; q < spec.nExc; q++) {
    expect(Array.from(a[q])).toEqual(Array.from(aAgain[q]));
  }

  const differentM = generateMultisine({ ...spec, m: spec.m + 1 }, 8000);
  expect(Array.from(a[0])).not.toEqual(Array.from(differentM[0]));
});

test('rotation law (nExc=3): channel q at experiment e equals e=0 rotated by exp(-2*pi*i*q*e/nExc)', () => {
  const N = 128;
  const spec0 = baseMultisineSpec({
    nSamples: N, k1: 3, k2: 3, nExc: 3, e: 0, tPeriods: 0, pPeriods: 1, seed: 999, m: 2,
  });
  const base = generateMultisine(spec0, 8000); // 3 channels, e=0
  const k = spec0.k1;

  for (const e of [1, 2]) {
    const rotated = generateMultisine({ ...spec0, e }, 8000);
    for (let q = 0; q < 3; q++) {
      const s0 = dftBin(base[q], k, N);
      const sE = dftBin(rotated[q], k, N);
      const theta = (2 * Math.PI * q * e) / 3; // rotator = exp(-i*theta)
      const expected = complexMul(s0, { re: Math.cos(theta), im: -Math.sin(theta) });
      expect(sE.re).toBeCloseTo(expected.re, 9);
      expect(sE.im).toBeCloseTo(expected.im, 9);
    }
  }
});

test('SISO (nExc=1) shape and RMS', () => {
  const spec = baseMultisineSpec({ nExc: 1, e: 0, ampRms: 0.15, tPeriods: 1, pPeriods: 2 });
  const channels = generateMultisine(spec, 8000);
  expect(channels).toHaveLength(1);
  expect(channels[0]).toHaveLength((spec.tPeriods + spec.pPeriods) * spec.nSamples);
  expect(Math.abs(rms(channels[0]) - spec.ampRms) / spec.ampRms).toBeLessThan(1e-9);
});

test('peak guard throws for an illegal ampRms, naming the peak and the limit; a legal call is not rescaled', () => {
  // Single line k=4: A = ampRms*sqrt(2); ampRms=1 -> A ≈ 1.414 > limit=1.
  const illegal = baseMultisineSpec({ nExc: 1, k1: 4, k2: 4, ampRms: 1, tPeriods: 0, pPeriods: 1 });
  expect(() => generateMultisine(illegal, 8000)).toThrow(/peak/i);
  try {
    generateMultisine(illegal, 8000);
    throw new Error('expected generateMultisine to throw');
  } catch (err) {
    const msg = (err as Error).message;
    // Peak is close to (not necessarily exactly) A = ampRms*sqrt(2) ≈ 1.414:
    // discrete N=64 samples at a random phase need not land on the
    // continuous cosine's exact maximum.
    const peakMatch = msg.match(/peak\s+([\d.]+)/i);
    expect(peakMatch).not.toBeNull();
    expect(Number(peakMatch![1])).toBeGreaterThan(1); // above the limit it violates
    expect(Number(peakMatch![1])).toBeLessThanOrEqual(Math.SQRT2 + 1e-6);
    expect(msg).toMatch(/limit/i);
    expect(msg).toContain('±1'); // the limit value
  }

  // Legal, low-amplitude call: NOT silently rescaled -- the DFT amplitude
  // stays exactly analytic (A), never clamped toward `limit`.
  const legal = baseMultisineSpec({ nExc: 1, k1: 4, k2: 4, ampRms: 0.5, tPeriods: 0, pPeriods: 1 });
  const [y] = generateMultisine(legal, 8000);
  const A = legal.ampRms * Math.sqrt(2);
  const { re, im } = dftBin(y, 4, legal.nSamples);
  expect(Math.hypot(re, im)).toBeCloseTo(A, 9);
});

test('validation: k1/k2 must be integers within 1 <= k1 <= k2 <= floor((N-1)/2)', () => {
  expect(() => generateMultisine(baseMultisineSpec({ k1: 1.5 }), 8000)).toThrow();
  expect(() => generateMultisine(baseMultisineSpec({ k1: 5, k2: 3 }), 8000)).toThrow(); // k1 > k2
  expect(() => generateMultisine(baseMultisineSpec({ k1: 0, k2: 3 }), 8000)).toThrow(); // k1 < 1
  // N=64 -> floor((64-1)/2) = 31; k2=32 is one past the Nyquist-adjacent bound.
  expect(() => generateMultisine(baseMultisineSpec({ nSamples: 64, k1: 1, k2: 32 }), 8000)).toThrow();
});

test('validation: nExc must be an integer >= 1', () => {
  expect(() => generateMultisine(baseMultisineSpec({ nExc: 0 }), 8000)).toThrow();
  expect(() => generateMultisine(baseMultisineSpec({ nExc: 1.5 }), 8000)).toThrow();
});

test('validation: e must satisfy 0 <= e < nExc', () => {
  expect(() => generateMultisine(baseMultisineSpec({ nExc: 2, e: 2 }), 8000)).toThrow();
  expect(() => generateMultisine(baseMultisineSpec({ nExc: 2, e: -1 }), 8000)).toThrow();
});

test('validation: tPeriods + pPeriods must be >= 1', () => {
  expect(() => generateMultisine(baseMultisineSpec({ tPeriods: 0, pPeriods: 0 }), 8000)).toThrow();
});

test('validation: m must be a non-negative integer', () => {
  expect(() => generateMultisine(baseMultisineSpec({ m: -1 }), 8000)).toThrow();
});

test('validation: seed must be a finite number', () => {
  expect(() => generateMultisine(baseMultisineSpec({ seed: NaN }), 8000)).toThrow();
  expect(() => generateMultisine(baseMultisineSpec({ seed: Infinity }), 8000)).toThrow();
});
