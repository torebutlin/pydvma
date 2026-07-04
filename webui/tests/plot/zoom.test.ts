import { expect, test } from 'vitest';
import { rubberBandToRange, clampToData, panBy } from '../../src/lib/plot/zoom';

const px = { width: 800, height: 400 };
const dom = { x: [0, 500] as [number, number], y: [-60, 40] as [number, number] };

test('rubber band pixel rect -> data range', () => {
  const r = rubberBandToRange({ x0: 200, y0: 100, x1: 400, y1: 300 }, dom, px);
  expect(r!.x![0]).toBeCloseTo(125); expect(r!.x![1]).toBeCloseTo(250);
  expect(r!.y![0]).toBeCloseTo(-35); expect(r!.y![1]).toBeCloseTo(15);   // y inverted
});

test('tiny drags (<6 px) are rejected as clicks', () => {
  expect(rubberBandToRange({ x0: 10, y0: 10, x1: 13, y1: 12 }, dom, px)).toBeNull();
});

test('rubber band accepts reversed drag directions', () => {
  // Dragging up-left must give the same window as down-right.
  const fwd = rubberBandToRange({ x0: 200, y0: 100, x1: 400, y1: 300 }, dom, px)!;
  const rev = rubberBandToRange({ x0: 400, y0: 300, x1: 200, y1: 100 }, dom, px)!;
  expect(rev.x).toEqual(fwd.x);
  expect(rev.y).toEqual(fwd.y);
});

test('clamp keeps the window inside data bounds + 5% margin (guardrail, spec §6)', () => {
  const c = clampToData({ x: [-900, -400], y: [0, 100] }, { x: [0, 500], y: [-60, 40] });
  expect(c.x![0]).toBeGreaterThanOrEqual(0 - 500 * 0.05);
  expect(c.x![1] - c.x![0]).toBeCloseTo(500);              // width preserved
});

test('clampToData passes null axes through and leaves in-bounds windows alone', () => {
  const c = clampToData({ x: null, y: [0, 10] }, { x: [0, 500], y: [-60, 40] });
  expect(c.x).toBeNull();                                  // auto-fit axis untouched
  expect(c.y![0]).toBeCloseTo(0);                          // already inside → unchanged
  expect(c.y![1]).toBeCloseTo(10);
});

test('clampToData shrinks windows wider than data + margin', () => {
  const c = clampToData({ x: [-1000, 2000], y: null }, { x: [0, 500], y: [-60, 40] });
  expect(c.x![0]).toBeCloseTo(-25);                        // 5% elastic margin each side
  expect(c.x![1]).toBeCloseTo(525);
});

test('pan shifts the window by pixel delta', () => {
  const p = panBy(dom, { dxPx: -80, dyPx: 0 }, px);
  expect(p.x![0]).toBeCloseTo(50); expect(p.x![1]).toBeCloseTo(550);
});

test('pan y-inversion: dragging down (positive dyPx) moves the window up in data space', () => {
  // 100 px of a 400 px surface = 25% of the 100-unit y span = +25 units.
  const p = panBy(dom, { dxPx: 0, dyPx: 100 }, px);
  expect(p.y![0]).toBeCloseTo(-35);
  expect(p.y![1]).toBeCloseTo(65);
  expect(p.x![0]).toBeCloseTo(0);                          // x untouched
  expect(p.x![1]).toBeCloseTo(500);
});
