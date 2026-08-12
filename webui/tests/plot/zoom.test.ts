import { expect, test } from 'vitest';
import {
  rubberBandToRange, clampToData, panBy, boxTouchesAxis, panTouchesAxis,
} from '../../src/lib/plot/zoom';

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

// ── Round-11 P5: a gesture commits only the axes it MEANT ───────────────────
// The rules PlotSurface applies per axis on release. An axis judged untouched
// keeps its previous stored value — `null` (auto) included — so an x-only box
// zoom no longer freezes a y axis that was following the data.

test('boxTouchesAxis: a band narrowing the axis targets it; a full-span band does not', () => {
  const d: [number, number] = [0, 100];
  expect(boxTouchesAxis([20, 60], d)).toBe(true);          // 40% — a real zoom
  expect(boxTouchesAxis([0, 94], d)).toBe(true);           // 94% — just under the keep line
  expect(boxTouchesAxis([0, 95], d)).toBe(false);          // 95% — edge-to-edge drag
  expect(boxTouchesAxis([-20, 130], d)).toBe(false);       // overspilled past both edges
  expect(boxTouchesAxis(null, d)).toBe(false);             // unconstrained axis
});

test('boxTouchesAxis: an x-only drag preserves y while still zooming x', () => {
  // Full plot height, a fifth of its width — the classic "select a frequency
  // band" gesture that used to pin the y axis.
  const xDom: [number, number] = [0, 500];
  const yDom: [number, number] = [-60, 40];
  expect(boxTouchesAxis([100, 200], xDom)).toBe(true);
  expect(boxTouchesAxis([-62, 42], yDom)).toBe(false);
});

test('boxTouchesAxis: a degenerate domain cannot be judged and counts as targeted', () => {
  expect(boxTouchesAxis([1, 1], [5, 5])).toBe(true);
  expect(boxTouchesAxis([0, 1], [10, 0])).toBe(true);      // inverted → not judgeable
});

test('panTouchesAxis: sub-1% displacement leaves the axis alone', () => {
  const from: [number, number] = [0, 100];
  expect(panTouchesAxis([0.5, 100.5], from)).toBe(false);  // 0.5% — pointer wobble
  expect(panTouchesAxis([1, 101], from)).toBe(true);       // 1% — a real move
  expect(panTouchesAxis([-30, 70], from)).toBe(true);
  expect(panTouchesAxis(from, from)).toBe(false);          // clamped: never moved
  expect(panTouchesAxis(null, from)).toBe(false);
});

test('panTouchesAxis: a horizontal drag moves x only', () => {
  const xFrom: [number, number] = [0, 500];
  const yFrom: [number, number] = [-60, 40];
  const p = panBy({ x: xFrom, y: yFrom }, { dxPx: -80, dyPx: 0 }, px);
  expect(panTouchesAxis(p.x, xFrom)).toBe(true);
  expect(panTouchesAxis(p.y, yFrom)).toBe(false);          // y keeps its previous value
});

test('panTouchesAxis: a degenerate domain counts as moved', () => {
  expect(panTouchesAxis([1, 2], [5, 5])).toBe(true);
});
