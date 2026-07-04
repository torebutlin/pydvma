/**
 * Zoom/pan controller maths for plot interaction (design spec §6):
 * rubber-band rectangle → data range, data-bounds clamping with an
 * elastic 5% margin, and pixel-delta panning.
 *
 * Pure functions — no DOM, no Svelte, no store access. The pointer
 * wiring in `PlotSurface.svelte` translates gestures into these calls
 * and commits results to the view-state store; unit-tested in
 * `tests/plot/zoom.test.ts`.
 */

/** Pixel-space drag rectangle, plot-area relative ((0,0) = top-left). */
export interface PxRect { x0: number; y0: number; x1: number; y1: number; }
/** Axis ranges; `null` means "auto-fit to data" (mirrors viewstate's Range). */
export interface Dom { x: [number, number] | null; y: [number, number] | null; }
interface Px { width: number; height: number; }

/** Drags smaller than this (px, either axis) are treated as clicks. */
const MIN_DRAG_PX = 6;
/** Elastic overshoot allowed past the data bounds (fraction of span). */
const CLAMP_MARGIN = 0.05;

/**
 * Convert a rubber-band drag rectangle (plot-area pixels) into a data
 * range against the currently displayed domains `dom` and the plot
 * area's pixel size `px`.
 *
 * The rect may be dragged in any direction — corners are normalised.
 * The y pixel axis points down, so the returned y range is inverted
 * relative to the pixel rect. Drags under 6 px on EITHER axis return
 * `null`: the caller must treat those as plain clicks, not zooms.
 */
export function rubberBandToRange(r: PxRect, dom: { x: [number, number]; y: [number, number] }, px: Px): Dom | null {
  if (Math.abs(r.x1 - r.x0) < MIN_DRAG_PX || Math.abs(r.y1 - r.y0) < MIN_DRAG_PX) return null;
  const fx = (p: number) => dom.x[0] + (p / px.width) * (dom.x[1] - dom.x[0]);
  const fy = (p: number) => dom.y[1] - (p / px.height) * (dom.y[1] - dom.y[0]);
  return {
    x: [fx(Math.min(r.x0, r.x1)), fx(Math.max(r.x0, r.x1))],
    y: [fy(Math.max(r.y0, r.y1)), fy(Math.min(r.y0, r.y1))],
  };
}

/**
 * Clamp a wanted window so it cannot leave the data (spec §6
 * guardrail): each axis is kept inside the data extent plus a 5%
 * elastic margin each side. The window WIDTH is preserved (the window
 * slides back inside) unless it exceeds data-plus-margins entirely,
 * in which case it shrinks to the full allowed span. `null` axes
 * (auto-fit) pass through untouched.
 */
export function clampToData(want: Dom, data: { x: [number, number]; y: [number, number] }): Dom {
  const clampAxis = (w: [number, number], d: [number, number]): [number, number] => {
    const margin = (d[1] - d[0]) * CLAMP_MARGIN;
    const lo = d[0] - margin, hi = d[1] + margin;
    const width = Math.min(w[1] - w[0], hi - lo);
    let a = w[0];
    if (a < lo) a = lo;
    if (a + width > hi) a = hi - width;
    return [a, a + width];
  };
  return {
    x: want.x ? clampAxis(want.x, data.x) : null,
    y: want.y ? clampAxis(want.y, data.y) : null,
  };
}

/**
 * Shift the displayed domains by a pointer delta in plot-area pixels,
 * keeping both spans constant. Sign convention matches "drag the
 * content": moving the pointer right (`dxPx > 0`) drags the data
 * right, so the window moves LEFT in data space; moving it down
 * (`dyPx > 0`, pixel y grows downward) drags the data down, so the
 * window moves UP in data space.
 */
export function panBy(dom: { x: [number, number]; y: [number, number] },
  d: { dxPx: number; dyPx: number }, px: Px): Dom {
  const dx = (d.dxPx / px.width) * (dom.x[1] - dom.x[0]);
  const dy = (d.dyPx / px.height) * (dom.y[1] - dom.y[0]);
  return { x: [dom.x[0] - dx, dom.x[1] - dx], y: [dom.y[0] + dy, dom.y[1] + dy] };
}
