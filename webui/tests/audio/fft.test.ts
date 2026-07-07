/**
 * Tests for the Live-scope FFT (src/lib/audio/fft.ts).
 * Verifies: pow2 helpers, radix-2 correctness against known signals
 * (pure sine bin, DC), Parseval energy conservation, and the one-sided
 * amplitude-spectrum helper's peak location + normalisation.
 */
import { expect, test } from 'vitest';
import {
  prevPow2, nextPow2, hannWindow, fftRadix2, magnitudeSpectrum,
} from '../../src/lib/audio/fft';

test('prevPow2 / nextPow2 bracket a value correctly', () => {
  expect(prevPow2(1)).toBe(1);
  expect(prevPow2(5)).toBe(4);
  expect(prevPow2(8)).toBe(8);
  expect(prevPow2(4095)).toBe(2048);
  expect(prevPow2(0)).toBe(1);
  expect(nextPow2(1)).toBe(1);
  expect(nextPow2(5)).toBe(8);
  expect(nextPow2(1024)).toBe(1024);
});

test('hannWindow is zero at the ends and 1 in the middle', () => {
  const w = hannWindow(9);
  expect(w[0]).toBeCloseTo(0, 12);
  expect(w[8]).toBeCloseTo(0, 12);
  expect(w[4]).toBeCloseTo(1, 12);
});

test('fftRadix2 throws on non-power-of-two length', () => {
  expect(() => fftRadix2(new Float64Array(6), new Float64Array(6))).toThrow(/power of two/);
});

test('fftRadix2 of a real DC signal puts all energy in bin 0', () => {
  const N = 8;
  const re = new Float64Array(N).fill(1);
  const im = new Float64Array(N);
  fftRadix2(re, im);
  expect(re[0]).toBeCloseTo(N, 10);
  for (let k = 1; k < N; k++) {
    expect(Math.hypot(re[k], im[k])).toBeCloseTo(0, 10);
  }
});

test('fftRadix2 of a pure sine has a single peak at its bin', () => {
  const N = 64;
  const bin = 4;
  const re = new Float64Array(N);
  const im = new Float64Array(N);
  for (let n = 0; n < N; n++) re[n] = Math.sin((2 * Math.PI * bin * n) / N);
  fftRadix2(re, im);
  // A real sine → conjugate pair at ±bin, each magnitude N/2.
  expect(Math.hypot(re[bin], im[bin])).toBeCloseTo(N / 2, 6);
  expect(Math.hypot(re[N - bin], im[N - bin])).toBeCloseTo(N / 2, 6);
  // Every other bin is ≈ 0.
  for (let k = 0; k < N; k++) {
    if (k === bin || k === N - bin) continue;
    expect(Math.hypot(re[k], im[k])).toBeCloseTo(0, 6);
  }
});

test('fftRadix2 conserves energy (Parseval)', () => {
  const N = 16;
  const re = new Float64Array(N);
  const im = new Float64Array(N);
  let timeEnergy = 0;
  for (let n = 0; n < N; n++) {
    re[n] = Math.sin(n) + 0.4 * Math.cos(3 * n) - 0.2 * n;
    timeEnergy += re[n] * re[n];
  }
  fftRadix2(re, im);
  let freqEnergy = 0;
  for (let k = 0; k < N; k++) freqEnergy += re[k] * re[k] + im[k] * im[k];
  // Σ|x|² == (1/N) Σ|X|²
  expect(freqEnergy / N).toBeCloseTo(timeEnergy, 8);
});

test('magnitudeSpectrum locates a tone at the right bin with unit amplitude', () => {
  const N = 256;
  const bin = 20;                       // frequency = bin/N of fs
  const x = new Float64Array(N);
  for (let n = 0; n < N; n++) x[n] = Math.sin((2 * Math.PI * bin * n) / N);
  const { mag, size } = magnitudeSpectrum(x, false); // no window → exact bin
  expect(size).toBe(N);
  // One-sided spectrum length = N/2 + 1.
  expect(mag.length).toBe(N / 2 + 1);
  // argmax is the tone's bin.
  let argmax = 0;
  for (let k = 1; k < mag.length; k++) if (mag[k] > mag[argmax]) argmax = k;
  expect(argmax).toBe(bin);
  // Amplitude ≈ 1 (interior bins carry the ×2 one-sided factor).
  expect(mag[bin]).toBeCloseTo(1, 3);
});

test('magnitudeSpectrum puts a DC signal at bin 0 with amplitude 1', () => {
  const x = new Float64Array(64).fill(1);
  const { mag } = magnitudeSpectrum(x, false);
  expect(mag[0]).toBeCloseTo(1, 6);
  for (let k = 1; k < mag.length; k++) expect(mag[k]).toBeCloseTo(0, 6);
});

test('magnitudeSpectrum uses the largest power-of-two window ≤ length', () => {
  const x = new Float64Array(300); // 300 → 256-point FFT on the most recent samples
  const { size, mag } = magnitudeSpectrum(x);
  expect(size).toBe(256);
  expect(mag.length).toBe(129);
});

test('magnitudeSpectrum returns an empty spectrum for tiny inputs', () => {
  expect(magnitudeSpectrum(new Float64Array(1)).size).toBe(1);
  expect(magnitudeSpectrum([]).mag.length).toBe(1);
});
