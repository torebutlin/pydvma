/**
 * Tests for the browser pretrigger assembly (src/lib/audio/pretrig.ts) — the
 * pure port of pydvma's `log_data` pretrigger windowing.  Verifies threshold
 * crossing → buffer stitching (crossing sits at index `pretrigSamples`), the
 * left zero-pad when the crossing precedes enough history, the timeout /
 * forced-trigger fallback, and that the streaming assembler matches the
 * whole-stream reference.
 */
import { expect, test } from 'vitest';
import {
  PretrigAssembler,
  assembleFromStream,
  findFirstCrossing,
  clampPretrigSamples,
  type PretrigParams,
} from '../../src/lib/audio/pretrig';

/** Build an interleaved (N, nCh) stream from a per-sample value function. */
function stream(n: number, nCh: number, val: (i: number, ch: number) => number): Float64Array {
  const s = new Float64Array(n * nCh);
  for (let i = 0; i < n; i++) for (let ch = 0; ch < nCh; ch++) s[i * nCh + ch] = val(i, ch);
  return s;
}

/** Feed a stream into a fresh assembler in fixed-size chunks. */
function feed(a: PretrigAssembler, s: Float64Array, nCh: number, chunk: number): void {
  const n = Math.floor(s.length / nCh);
  for (let off = 0; off < n && !a.done; off += chunk) {
    const m = Math.min(chunk, n - off);
    a.push(s.subarray(off * nCh, (off + m) * nCh), m);
  }
}

// ---- clampPretrigSamples ----

test('clampPretrigSamples keeps 0 ≤ p ≤ min(total−1, cap)', () => {
  expect(clampPretrigSamples(100, 88200)).toBe(100);
  expect(clampPretrigSamples(-5, 1000)).toBe(0);
  expect(clampPretrigSamples(NaN, 1000)).toBe(0);
  expect(clampPretrigSamples(5000, 10)).toBe(9);          // < totalSamples
  expect(clampPretrigSamples(1_000_000, 1_000_000, 48000)).toBe(48000); // capped
});

// ---- findFirstCrossing ----

test('findFirstCrossing returns the first |x| > threshold on the given channel', () => {
  const s = stream(10, 2, (i, ch) => (ch === 1 && i === 4 ? 0.9 : 0.1));
  expect(findFirstCrossing(s, 2, 1, 0.5)).toBe(4);   // channel 1 crosses at 4
  expect(findFirstCrossing(s, 2, 0, 0.5)).toBe(-1);  // channel 0 never crosses
  expect(findFirstCrossing(s, 2, 1, 0.95)).toBe(-1); // strict > : 0.9 does not exceed 0.95
});

// ---- assembleFromStream (reference stitching) ----

test('assembleFromStream places the crossing at index pretrigSamples', () => {
  // Single channel; crossing (1.0) at sample 5, everything else 0.1.
  const s = stream(20, 1, (i) => (i === 5 ? 1.0 : 0.1));
  const params: PretrigParams = {
    nChannels: 1, pretrigChannel: 0, threshold: 0.5, pretrigSamples: 3, totalSamples: 10,
  };
  const { data, triggered, triggerIndex } = assembleFromStream(s, params);
  expect(triggered).toBe(true);
  expect(triggerIndex).toBe(5);
  expect(data[3]).toBeCloseTo(1.0, 12);              // crossing at index pretrigSamples
  // window[0:3) = pre-context = stream[2,3,4]; window[3:] = stream[5:12].
  expect(Array.from(data.subarray(0, 3))).toEqual([0.1, 0.1, 0.1]);
  expect(data).toHaveLength(10);
});

test('assembleFromStream zero-pads the left when the crossing precedes pretrigSamples', () => {
  const s = stream(20, 1, (i) => (i === 1 ? 1.0 : 0.2));
  const { data } = assembleFromStream(s, {
    nChannels: 1, pretrigChannel: 0, threshold: 0.5, pretrigSamples: 3, totalSamples: 6,
  });
  // startIndex = 1 − 3 = −2 → two zeros, then stream[0], then the crossing.
  expect(data[0]).toBe(0);
  expect(data[1]).toBe(0);
  expect(data[2]).toBeCloseTo(0.2, 12); // stream[0]
  expect(data[3]).toBeCloseTo(1.0, 12); // crossing at index pretrigSamples
});

test('assembleFromStream with no crossing returns the leading window, untriggered', () => {
  const s = stream(20, 1, () => 0.1);
  const { data, triggered, triggerIndex } = assembleFromStream(s, {
    nChannels: 1, pretrigChannel: 0, threshold: 0.5, pretrigSamples: 3, totalSamples: 8,
  });
  expect(triggered).toBe(false);
  expect(triggerIndex).toBe(-1);
  expect(data).toHaveLength(8);
  expect(Array.from(data)).toEqual(new Array(8).fill(0.1));
});

test('assembleFromStream handles multi-channel windows', () => {
  // ch0 = i, ch1 = trigger (crosses at i=6).
  const s = stream(20, 2, (i, ch) => (ch === 0 ? i : (i === 6 ? 1.0 : 0.0)));
  const { data } = assembleFromStream(s, {
    nChannels: 2, pretrigChannel: 1, threshold: 0.5, pretrigSamples: 2, totalSamples: 5,
  });
  // startIndex = 6 − 2 = 4 → window ch0 = [4,5,6,7,8].
  expect(Array.from([data[0], data[2], data[4], data[6], data[8]])).toEqual([4, 5, 6, 7, 8]);
  expect(data[5]).toBeCloseTo(1.0, 12); // crossing on ch1 at window index pretrigSamples(2)
});

// ---- streaming assembler ----

test('streaming assembler matches the whole-stream reference', () => {
  const s = stream(60, 1, (i) => (i === 22 ? 0.8 : 0.05));
  const params: PretrigParams = {
    nChannels: 1, pretrigChannel: 0, threshold: 0.5, pretrigSamples: 4, totalSamples: 30,
  };
  const a = new PretrigAssembler(params);
  feed(a, s, 1, 7); // odd chunk size straddles the crossing mid-chunk
  expect(a.done).toBe(true);
  expect(a.triggered).toBe(true);
  expect(a.triggerIndex).toBe(22);
  const ref = assembleFromStream(s, params);
  expect(Array.from(a.result()!.data)).toEqual(Array.from(ref.data));
});

test('streaming assembler surfaces triggered only after the crossing', () => {
  const s = stream(40, 1, (i) => (i === 10 ? 0.9 : 0.05));
  const a = new PretrigAssembler({
    nChannels: 1, pretrigChannel: 0, threshold: 0.5, pretrigSamples: 3, totalSamples: 20,
  });
  a.push(s.subarray(0, 5), 5);      // samples 0..4, no crossing
  expect(a.triggered).toBe(false);
  expect(a.collected).toBe(0);      // nothing collected while waiting
  a.push(s.subarray(5 * 1, 40), 35); // includes the crossing at 10
  expect(a.triggered).toBe(true);
});

test('forceTrigger (timeout fallback) straddles the current instant, untriggered', () => {
  // Values 0..9 fed with a never-crossing threshold, then a forced finish.
  const s = stream(20, 1, (i) => i);
  const a = new PretrigAssembler({
    nChannels: 1, pretrigChannel: 0, threshold: 100, pretrigSamples: 3, totalSamples: 6,
  });
  a.push(s.subarray(0, 5), 5);   // ring now holds [2,3,4]; globalIndex = 5
  expect(a.triggered).toBe(false);
  a.forceTrigger();              // synthesise a trigger "now"
  expect(a.triggered).toBe(false); // still not a real crossing
  a.push(s.subarray(5, 8), 3);   // append 5,6,7 → window fills
  expect(a.done).toBe(true);
  // Pre-context = last 3 pre-force samples [2,3,4]; then the post samples.
  expect(Array.from(a.result()!.data)).toEqual([2, 3, 4, 5, 6, 7]);
});

test('pretrigSamples = 0 puts the crossing at the window start', () => {
  const s = stream(20, 1, (i) => (i === 5 ? 1.0 : 0.1));
  const { data } = assembleFromStream(s, {
    nChannels: 1, pretrigChannel: 0, threshold: 0.5, pretrigSamples: 0, totalSamples: 4,
  });
  expect(data[0]).toBeCloseTo(1.0, 12); // crossing at index 0
});
