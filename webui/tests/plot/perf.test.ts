import { expect, test } from 'vitest';
import { buildPlot } from '../../src/lib/plot/build';

test('24 lines x 200k samples decimates + builds in < 250 ms', () => {
  const lines = Array.from({ length: 24 }, () => ({
    x: Float64Array.from({ length: 200_000 }, (_, i) => i),
    y: Float64Array.from({ length: 200_000 }, () => Math.random()),
    color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left' as const,
  }));
  const t0 = performance.now();
  buildPlot({ lines, xLabel: '', yLabel: '', xRange: null, yRange: null }, 1200, 500);
  expect(performance.now() - t0).toBeLessThan(250);
});
