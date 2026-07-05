import { expect, test } from 'vitest';
import { buildPlot } from '../../src/lib/plot/build';

const line = (yAxis: 'left' | 'right' = 'left') => ({
  x: Float64Array.from({ length: 1000 }, (_, i) => i / 500),
  y: Float64Array.from({ length: 1000 }, (_, i) => Math.sin(i / 50)),
  color: '#2563eb', opacity: 1, width: 1.6, dashed: false, yAxis,
});

/** Extract the x px coordinate of every point in an SVG path `d` string. */
const pathXs = (d: string): number[] =>
  [...d.matchAll(/[ML](-?[\d.]+),/g)].map(m => Number(m[1]));

test('builds paths and ticks', () => {
  const b = buildPlot({ lines: [line()], xLabel: 't', yLabel: 'V', xRange: null, yRange: null }, 800, 400);
  expect(b.paths[0].d.startsWith('M')).toBe(true);
  expect(b.xTicks.length).toBeGreaterThan(3);
});

test('square aspect equalises domains (Nyquist)', () => {
  const b = buildPlot({
    lines: [line()], xLabel: 'Re', yLabel: 'Im',
    squareAspect: true, xRange: [-2, 2], yRange: [-1, 1],
  }, 400, 400);
  expect(b.xDomain[1] - b.xDomain[0]).toBeCloseTo(b.yDomain[1] - b.yDomain[0], 9);
});

test('right-axis lines scale against y2Range', () => {
  const b = buildPlot({
    lines: [line('right')], xLabel: '', yLabel: '', y2Range: [0, 1],
    xRange: null, yRange: [-5, 5],
  }, 800, 400);
  expect(b.y2Ticks.length).toBeGreaterThan(0);
});

test('zoomed xRange decimates only the visible window (path stays on-screen)', () => {
  const n = 100_000;
  const x = Float64Array.from({ length: n }, (_, i) => i / 1000);          // 0 .. ~100
  const y = Float64Array.from({ length: n }, (_, i) => Math.sin(i / 30));
  y[0] = 500; y[n - 1] = -500;                                             // far off-screen extremes
  const width = 800;
  const b = buildPlot({
    lines: [{ x, y, color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left' }],
    xLabel: '', yLabel: '', xRange: [40, 41], yRange: [-2, 2],
  }, width, 400);
  const xs = pathXs(b.paths[0].d);
  expect(xs.length).toBeGreaterThan(100);            // real content, not a stub
  for (const X of xs) {                              // one-sample margin allowed each side
    expect(X).toBeGreaterThanOrEqual(-5);
    expect(X).toBeLessThanOrEqual(width + 5);
  }
});

test('non-monotonic x with a zoom window falls back to the full range', () => {
  // Parametric-ish curve (x doubles back) but NOT flagged squareAspect:
  // the monotonic check must reject window-slicing, keeping all points.
  const m = 200;
  const x = Float64Array.from({ length: m }, (_, i) => Math.cos(i / 10));
  const y = Float64Array.from({ length: m }, (_, i) => Math.sin(i / 10));
  const b = buildPlot({
    lines: [{ x, y, color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left' }],
    xLabel: '', yLabel: '', xRange: [-0.5, 0.5], yRange: [-1, 1],
  }, 400, 400);
  expect(pathXs(b.paths[0].d).length).toBe(m);
});

test('zoom window entirely outside the data emits an empty path', () => {
  const mk = (xRange: [number, number]) => buildPlot({
    lines: [{
      x: Float64Array.from({ length: 100 }, (_, i) => i),        // 0 .. 99
      y: new Float64Array(100), color: '#000', opacity: 1, width: 1, dashed: false,
      yAxis: 'left' as const,
    }],
    xLabel: '', yLabel: '', xRange, yRange: [-1, 1],
  }, 400, 200);
  expect(mk([200, 300]).paths[0].d).toBe('');       // right of all data
  expect(mk([-50, -10]).paths[0].d).toBe('');       // left of all data
});

test('zoom window between two adjacent samples keeps the bridging segment', () => {
  // xRange (0.4, 0.6) contains NO sample (ub < lb) but must NOT be
  // treated as off-screen: the ±1-sample margins bridge across it.
  const b = buildPlot({
    lines: [{
      x: Float64Array.from([0, 1, 2, 3]), y: Float64Array.from([0, 1, 0, 1]),
      color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left',
    }],
    xLabel: '', yLabel: '', xRange: [0.4, 0.6], yRange: [-1, 2],
  }, 400, 200);
  expect(pathXs(b.paths[0].d).length).toBe(2);      // exactly the two bridging samples
});

test('xMonotonic flag bypasses the scan in both directions', () => {
  const x = Float64Array.from({ length: 100 }, (_, i) => i);
  const y = new Float64Array(100);
  const mk = (xMonotonic: boolean) => buildPlot({
    lines: [{ x, y, color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left', xMonotonic }],
    xLabel: '', yLabel: '', xRange: [200, 300], yRange: [-1, 1],
  }, 400, 200);
  // true → window-sliced (off-screen → empty), no scan needed
  expect(mk(true).paths[0].d).toBe('');
  // false → parametric fallback: full range rendered despite monotonic x
  expect(pathXs(mk(false).paths[0].d).length).toBe(100);
});

test('xScale "log": ticks are decades and mapping is log10', () => {
  // A line spanning 1 .. 1000 Hz; explicit log-x domain.
  const n = 2000;
  const x = Float64Array.from({ length: n }, (_, i) => 1 + i * (1000 / (n - 1)));
  const y = Float64Array.from({ length: n }, () => 1);
  const width = 300;
  const b = buildPlot({
    lines: [{ x, y, color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left', xMonotonic: true }],
    xLabel: 'Frequency (Hz)', yLabel: '|H|', xScale: 'log', xRange: [1, 1000], yRange: [0, 2],
  }, width, 300);
  // Decade ticks, and each decade is width/3 px apart (log 1→1000 over 300px).
  expect(b.xTicks.map(t => t.v)).toEqual([1, 10, 100, 1000]);
  expect(b.xTicks[0].px).toBeCloseTo(0, 6);
  expect(b.xTicks[1].px).toBeCloseTo(100, 6);
  expect(b.xTicks[2].px).toBeCloseTo(200, 6);
  expect(b.xTicks[3].px).toBeCloseTo(300, 6);
});

test('xScale "log": a DC (x=0) sample is dropped, not thrown, and domain clamps positive', () => {
  // Autoscale (xRange null) with a leading f=0 bin. The log domain must
  // clamp its lower bound to the first positive frequency, and the f=0
  // sample must not emit a point (log10(0) = -Inf → non-finite → skipped).
  const x = Float64Array.from([0, 1, 10, 100]);
  const y = Float64Array.from([5, 1, 1, 1]);
  const b = buildPlot({
    lines: [{ x, y, color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left', xMonotonic: true }],
    xLabel: 'Frequency (Hz)', yLabel: '|H|', xScale: 'log', xRange: null, yRange: [0, 6],
  }, 300, 300);
  // Domain lower bound clamped to the first positive datum (1), not 0.
  expect(b.xDomain[0]).toBeCloseTo(1, 9);
  expect(b.xDomain[1]).toBeCloseTo(100, 9);
  // Ticks are decades within [1,100].
  expect(b.xTicks.map(t => t.v)).toEqual([1, 10, 100]);
  // The path has 3 finite points (f=0 dropped), all within the pixel box.
  const xs = pathXs(b.paths[0].d);
  expect(xs.length).toBe(3);
  for (const X of xs) { expect(X).toBeGreaterThanOrEqual(-0.5); expect(X).toBeLessThanOrEqual(300.5); }
});

test('xScale absent/"lin" keeps the linear path exactly as before', () => {
  const b = buildPlot({
    lines: [line()], xLabel: 't', yLabel: 'V', xRange: [0, 2], yRange: null,
  }, 800, 400);
  const bLin = buildPlot({
    lines: [line()], xLabel: 't', yLabel: 'V', xScale: 'lin', xRange: [0, 2], yRange: null,
  }, 800, 400);
  expect(b.xTicks.map(t => t.v)).toEqual(bLin.xTicks.map(t => t.v));
  expect(b.paths[0].d).toBe(bLin.paths[0].d);
});

test('short Nyquist lines skip decimation entirely', () => {
  const m = 5000;                                    // < 8k threshold, > 2*columns
  const x = Float64Array.from({ length: m }, (_, i) => Math.cos(i / 100));
  const y = Float64Array.from({ length: m }, (_, i) => Math.sin(i / 100));
  const b = buildPlot({
    lines: [{ x, y, color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left' }],
    xLabel: 'Re', yLabel: 'Im', squareAspect: true, xRange: null, yRange: null,
  }, 200, 200);                                      // 200 columns → decimation would drop points
  expect(pathXs(b.paths[0].d).length).toBe(m);
});
