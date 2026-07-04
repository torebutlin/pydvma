import { expect, test } from 'vitest';
import { presetToXY, clampLegend, type LegendPreset } from '../../src/lib/plot/legendPos';

test('presets map to fractional positions', () => {
  expect(presetToXY('ne')).toEqual({ x: 0.98, y: 0.02 });
  expect(presetToXY('sw')).toEqual({ x: 0.02, y: 0.98 });
  expect(presetToXY('outside-right')).toEqual({ x: 1.02, y: 0.02 });
});

test('drag position is clamped so the legend stays reachable', () => {
  const c = clampLegend({ x: 5, y: -3 });
  expect(c.x).toBeLessThanOrEqual(1.05);
  expect(c.y).toBeGreaterThanOrEqual(0);
});

test('every preset round-trips to a distinct in-range point', () => {
  const presets: LegendPreset[] = ['ne', 'nw', 'se', 'sw', 'outside-right'];
  const seen = new Set<string>();
  for (const p of presets) {
    const { x, y } = presetToXY(p);
    // In-range for the panel maths: x within [0, 1.05], y within [0, 1].
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x).toBeLessThanOrEqual(1.05);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(y).toBeLessThanOrEqual(1);
    seen.add(`${x},${y}`);
  }
  expect(seen.size).toBe(presets.length); // all five map to distinct positions
});

test('presetToXY returns a fresh object (no shared mutable state)', () => {
  const a = presetToXY('ne');
  a.x = 42;
  expect(presetToXY('ne')).toEqual({ x: 0.98, y: 0.02 });
});

test('clampLegend leaves an in-range point untouched', () => {
  expect(clampLegend({ x: 0.5, y: 0.5 })).toEqual({ x: 0.5, y: 0.5 });
  expect(clampLegend({ x: 1.02, y: 0.02 })).toEqual({ x: 1.02, y: 0.02 });
});
