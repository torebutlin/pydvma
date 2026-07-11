import { expect, test } from 'vitest';
import { detectPeaks, stepWindow } from '../../src/lib/plot/peaks';

/** Synthetic |H|(f)-in-dB line: three Lorentzian-ish peaks + mild ripple. */
function threePeakLine(): { x: Float64Array; y: Float64Array } {
  const N = 2000;
  const x = new Float64Array(N), y = new Float64Array(N);
  const modes = [{ fn: 120, a: 40 }, { fn: 470, a: 55 }, { fn: 810, a: 35 }];
  for (let i = 0; i < N; i++) {
    const f = (i / (N - 1)) * 1000;                    // 0..1000 Hz
    let v = 0;
    for (const m of modes) v += m.a / (1 + ((f - m.fn) / 12) ** 2);
    x[i] = f;
    // Ripple prominence ≈ 2·amp = 2.0, safely below the 5% gate (~2.9 of the
    // ~58 span) — decisive, not marginal.
    y[i] = v + 1.0 * Math.sin(f / 3);
  }
  return { x, y };
}

test('detectPeaks finds the three synthetic modes (and nothing else)', () => {
  const peaks = detectPeaks([threePeakLine()], [0, 1000]);
  expect(peaks.length).toBe(3);
  expect(Math.abs(peaks[0] - 120)).toBeLessThan(5);
  expect(Math.abs(peaks[1] - 470)).toBeLessThan(5);
  expect(Math.abs(peaks[2] - 810)).toBeLessThan(5);
});

test('detectPeaks respects the scope (only peaks inside it)', () => {
  const peaks = detectPeaks([threePeakLine()], [300, 700]);
  expect(peaks.length).toBe(1);
  expect(Math.abs(peaks[0] - 470)).toBeLessThan(5);
});

test('detectPeaks: composite max-envelope across lines', () => {
  const a = threePeakLine();
  // Second line with one big extra peak at 650 Hz.
  const N = a.x.length;
  const y2 = new Float64Array(N);
  for (let i = 0; i < N; i++) y2[i] = 60 / (1 + ((a.x[i] - 650) / 10) ** 2);
  const peaks = detectPeaks([a, { x: a.x, y: y2 }], [0, 1000]);
  expect(peaks.some((p) => Math.abs(p - 650) < 5)).toBe(true);
  expect(peaks.some((p) => Math.abs(p - 470) < 5)).toBe(true);
});

test('detectPeaks: degenerate input → []', () => {
  expect(detectPeaks([], [0, 1000])).toEqual([]);
  expect(detectPeaks([threePeakLine()], [500, 500])).toEqual([]);
  const flat = { x: new Float64Array([0, 1, 2]), y: new Float64Array([1, 1, 1]) };
  expect(detectPeaks([flat], [0, 2])).toEqual([]);
});

test('stepWindow: keep-width, centred on the next peak beyond the centre', () => {
  const peaks = [120, 470, 810];
  const next = stepWindow(peaks, [100, 300], [0, 1000], 1);   // centre 200, width 200
  expect(next).not.toBeNull();
  expect(next![1] - next![0]).toBeCloseTo(200, 6);
  expect((next![0] + next![1]) / 2).toBeCloseTo(470, 6);
  const prev = stepWindow(peaks, [400, 540], [0, 1000], -1);  // centre 470 → back to 120
  expect((prev![0] + prev![1]) / 2).toBeCloseTo(120, 6);
});

test('stepWindow clamps into the scope (hugs the edge, width kept)', () => {
  const next = stepWindow([950], [500, 900], [0, 1000], 1);   // centred window would overhang
  expect(next).toEqual([600, 1000]);
});

test('stepWindow: no further peak → null (disable the button)', () => {
  expect(stepWindow([120, 470], [400, 540], [0, 1000], 1)).toBeNull();   // centre 470, none beyond
  expect(stepWindow([470], [400, 540], [0, 1000], -1)).toBeNull();
  expect(stepWindow([], [0, 100], [0, 1000], 1)).toBeNull();
});

test('stepWindow: a clamped-at-edge window skips to a genuinely different window', () => {
  // Window already hugging the hi edge, its centre (800) below the only peak (950):
  // re-targeting 950 reproduces the same clamped window → must return null, not loop.
  expect(stepWindow([950], [600, 1000], [0, 1000], 1)).toBeNull();
});

test('stepWindow: window ≥90% of scope steps at scope/10 width (the "home" rule)', () => {
  // Window [0,900] spans exactly 90% ⇒ home rule; its centre (450) is below
  // the peak (470), so › targets it at the reduced width.
  const next = stepWindow([470], [0, 900], [0, 1000], 1);
  expect(next![1] - next![0]).toBeCloseTo(100, 6);
  expect((next![0] + next![1]) / 2).toBeCloseTo(470, 6);
});

test('stepWindow log mode preserves width as a RATIO (brush translate semantics)', () => {
  const next = stepWindow([100, 400], [80, 125], [10, 1000], 1, true);  // ratio 125/80
  expect(next).not.toBeNull();
  expect(next![1] / next![0]).toBeCloseTo(125 / 80, 6);
  expect(Math.sqrt(next![0] * next![1])).toBeCloseTo(400, 4);           // log-centred on the peak
});

test('detectPeaks log mode: log10 binning recovers peaks on a log axis', () => {
  // Two modes an octave-ish apart on a 10–1000 Hz log axis.
  const N = 4000;
  const x = new Float64Array(N), y = new Float64Array(N);
  for (let i = 0; i < N; i++) {
    const f = 10 ** (1 + (i / (N - 1)) * 2);           // 10..1000 Hz, log-spaced
    let v = 0;
    for (const m of [{ fn: 100, a: 40 }, { fn: 400, a: 50 }]) {
      v += m.a / (1 + ((f - m.fn) / (m.fn * 0.05)) ** 2);   // ~5% fractional width
    }
    x[i] = f; y[i] = v;
  }
  const peaks = detectPeaks([{ x, y }], [10, 1000], true);
  expect(peaks.length).toBe(2);
  expect(Math.abs(peaks[0] - 100) / 100).toBeLessThan(0.05);   // within 5% (bin-centre error)
  expect(Math.abs(peaks[1] - 400) / 400).toBeLessThan(0.05);
});

test('detectPeaks tolerates NaN gaps in the input lines', () => {
  const l = threePeakLine();
  for (let i = 200; i < 260; i++) l.y[i] = NaN;        // punch a hole near 115 Hz... keep away from peaks
  for (let i = 1200; i < 1240; i++) l.y[i] = NaN;
  const peaks = detectPeaks([l], [0, 1000]);
  expect(peaks.some((p) => Math.abs(p - 470) < 5)).toBe(true);
  expect(peaks.some((p) => Math.abs(p - 810) < 5)).toBe(true);
});

test('stepWindow keeps width just BELOW the 90% home threshold', () => {
  const next = stepWindow([470], [0, 899], [0, 1000], 1);   // 89.9% span → keep-width applies
  expect(next).not.toBeNull();
  expect(next![1] - next![0]).toBeCloseTo(899, 6);
});
