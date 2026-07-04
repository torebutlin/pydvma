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
