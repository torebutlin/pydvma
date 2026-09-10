import { expect, test } from 'vitest';
import { IMPULSE_TAIL_MAX, impulseTailFraction, looksLikeImpulse } from '../../src/lib/analysis/impulse';

// Round-15 item 4 (3C6 lab, 2026-09-10): Clean Impulse is offered only
// where the input channel looks like an impulse. The lab's 6 s hammer
// taps put 0–1 % of their energy in the second half of the record; its
// 30 s random-noise captures 46–55 %.

function interleave(...channels: number[][]): Float64Array {
  const n = channels[0].length;
  const out = new Float64Array(n * channels.length);
  for (let i = 0; i < n; i++) for (let c = 0; c < channels.length; c++) out[i * channels.length + c] = channels[c][i];
  return out;
}

test('a front-loaded decay is an impulse; broadband noise is not', () => {
  const n = 2000;
  const tap = Array.from({ length: n }, (_, i) => Math.exp(-i / 100) * Math.cos(i / 3));
  let seed = 7;
  const noise = Array.from({ length: n }, () => { seed = (seed * 48271) % 2147483647; return seed / 2147483647 - 0.5; });
  const data = interleave(tap, noise);
  const tapTail = impulseTailFraction(data, 2, 0)!;
  const noiseTail = impulseTailFraction(data, 2, 1)!;
  expect(tapTail).toBeLessThan(0.01);
  expect(noiseTail).toBeGreaterThan(0.4);
  expect(noiseTail).toBeLessThan(0.6);
  expect(looksLikeImpulse(tapTail)).toBe(true);
  expect(looksLikeImpulse(noiseTail)).toBe(false);
});

test('the gate is conservative: a ringing tap keeps its button', () => {
  // Slow decay: a fifth of the energy after the midpoint still passes.
  const n = 1000;
  const slow = Array.from({ length: n }, (_, i) => Math.exp(-i / 600));
  const f = impulseTailFraction(Float64Array.from(slow), 1, 0)!;
  expect(f).toBeGreaterThan(0.1);
  expect(f).toBeLessThanOrEqual(IMPULSE_TAIL_MAX);
  expect(looksLikeImpulse(f)).toBe(true);
});

test('silent, missing or out-of-range channels give null (no button, no crash)', () => {
  expect(impulseTailFraction(new Float64Array(200), 2, 0)).toBeNull();     // silent
  expect(impulseTailFraction(new Float64Array(200), 2, 5)).toBeNull();     // no such channel
  expect(impulseTailFraction(new Float64Array(0), 1, 0)).toBeNull();       // empty
  expect(looksLikeImpulse(null)).toBe(false);
});

test('channels are read interleaved, sample-major', () => {
  // ch0 all in the first half, ch1 all in the second half.
  const a = [1, 1, 1, 1, 0, 0, 0, 0];
  const b = [0, 0, 0, 0, 1, 1, 1, 1];
  const data = interleave(a, b);
  expect(impulseTailFraction(data, 2, 0)).toBe(0);
  expect(impulseTailFraction(data, 2, 1)).toBe(1);
});
