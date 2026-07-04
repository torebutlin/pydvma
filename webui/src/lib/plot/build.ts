/**
 * Plot builder: turns a `PlotModel` (lines + axis config) into a
 * `BuiltPlot` (SVG path strings + tick positions) for a given pixel
 * box. All geometry lives here so `PlotSurface.svelte` stays a dumb
 * renderer; unit-tested in `tests/plot/build.test.ts` and budgeted by
 * `tests/plot/perf.test.ts`.
 */
import { niceTicks, scaleLinear } from './scales';
import { minMaxDecimate } from './decimate';

/**
 * One renderable line. Colour/opacity arrive pre-resolved from the
 * selection store (tri-state fade → opacity mapping happens in the
 * model assembly, not here). `yAxis: 'right'` scales against
 * `PlotModel.y2Range` (coherence overlay).
 */
export interface PlotLine {
  x: ArrayLike<number>; y: ArrayLike<number>;
  color: string; opacity: number; width: number; dashed: boolean;
  yAxis: 'left' | 'right';                        // right = coherence
  /**
   * Whether `x` is known to be sorted non-decreasing. Set `true` for
   * time/frequency axes (model assembly knows this a priori) to skip
   * the O(n) per-build monotonicity scan; set `false` to force the
   * parametric fallback without scanning. Absent → scan as before.
   * Only consulted when a zoom window (`xRange`) is active.
   */
  xMonotonic?: boolean;
}

/**
 * Declarative description of everything on the plot. `xRange` /
 * `yRange` of `null` mean autoscale to the data extent;
 * `squareAspect` marks Nyquist-style parametric views (equalised
 * domains, no window-slicing, no decimation below 8k points).
 */
export interface PlotModel {
  lines: PlotLine[];
  xLabel: string; yLabel: string; y2Label?: string;
  squareAspect?: boolean;                          // Nyquist
  xRange: [number, number] | null; yRange: [number, number] | null;
  y2Range?: [number, number];
}

/**
 * Render-ready output: tick positions in px, one SVG path descriptor
 * per line, and the resolved domains (for zoom/pan bookkeeping).
 */
export interface BuiltPlot {
  xTicks: Array<{ v: number; px: number }>;
  yTicks: Array<{ v: number; px: number }>;
  y2Ticks: Array<{ v: number; px: number }>;
  paths: Array<{ d: string; color: string; opacity: number; width: number; dashed: boolean }>;
  xDomain: [number, number]; yDomain: [number, number];
}

/** Nyquist lines shorter than this render every point, undecimated. */
const NYQUIST_DECIMATE_THRESHOLD = 8000;

function dataExtent(lines: PlotLine[], axis: 'x' | 'y', which: 'left' | 'right' | 'any')
  : [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const l of lines) {
    if (which !== 'any' && l.yAxis !== which) continue;
    const arr = axis === 'x' ? l.x : l.y;
    for (let i = 0; i < arr.length; i++) {
      const v = arr[i];
      if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    }
  }
  if (lo === Infinity) return [0, 1];
  if (lo === hi) return [lo - 1, hi + 1];
  return [lo, hi];
}

/** True if `x` never decreases (time/frequency axes always qualify). */
function isMonotonicNonDecreasing(x: ArrayLike<number>): boolean {
  for (let i = 1; i < x.length; i++) if (x[i] < x[i - 1]) return false;
  return true;
}

/** First index with `x[i] >= v` (x must be sorted non-decreasing). */
function lowerBound(x: ArrayLike<number>, v: number): number {
  let lo = 0, hi = x.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (x[mid] < v) lo = mid + 1; else hi = mid; }
  return lo;
}

/** Last index with `x[i] <= v` (x must be sorted non-decreasing). */
function upperBound(x: ArrayLike<number>, v: number): number {
  let lo = 0, hi = x.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (x[mid] <= v) lo = mid + 1; else hi = mid; }
  return lo - 1;
}

/**
 * Build the renderable plot for a `width` x `height` px drawing area.
 *
 * Domains: explicit ranges win; otherwise autoscale to finite data
 * (left-axis lines only for y). `squareAspect` then equalises both
 * domain spans around their centres (spec §5: Nyquist square).
 *
 * Decimation strategy per line:
 * - Nyquist (`squareAspect`): x is parametric, so min-max decimation
 *   by index is only safe as a last resort — lines under 8k points
 *   render every sample; longer ones decimate over the full range.
 * - Zoomed (`xRange` set) monotonic lines (`xMonotonic`, or a scan
 *   when the flag is absent): binary-search the visible index window
 *   (one sample of margin each side) and decimate only that, so
 *   off-screen samples cost nothing and never render. A window that
 *   falls entirely outside the data produces an EMPTY path; a window
 *   between two adjacent samples keeps the bridging segment via the
 *   ±1-sample margins.
 * - Everything else: min-max decimate the full range at ~1 column
 *   per px (floor 64).
 *
 * Non-finite samples (NaN gaps) are skipped, splitting nothing:
 * decimation seeds each pixel column's min/max from the column's
 * first FINITE sample (all-NaN columns emit no points), and the path
 * builder bridges across any non-finite point that remains.
 */
export function buildPlot(model: PlotModel, width: number, height: number): BuiltPlot {
  let xDomain = model.xRange ?? dataExtent(model.lines, 'x', 'any');
  let yDomain = model.yRange ?? dataExtent(model.lines, 'y', 'left');

  if (model.squareAspect) {                        // spec §5: Nyquist square, fit data
    const xs = xDomain[1] - xDomain[0], ys = yDomain[1] - yDomain[0];
    const span = Math.max(xs, ys);
    const xc = (xDomain[0] + xDomain[1]) / 2, yc = (yDomain[0] + yDomain[1]) / 2;
    xDomain = [xc - span / 2, xc + span / 2];
    yDomain = [yc - span / 2, yc + span / 2];
  }

  const sx = scaleLinear(xDomain[0], xDomain[1], 0, width);
  const sy = scaleLinear(yDomain[0], yDomain[1], height, 0);
  const sy2 = scaleLinear(model.y2Range?.[0] ?? 0, model.y2Range?.[1] ?? 1, height, 0);
  const columns = Math.max(64, Math.floor(width));

  const paths = model.lines.map(line => {
    const scaleY = line.yAxis === 'right' ? sy2 : sy;
    const len = line.x.length;
    let pts: Array<[number, number]>;
    if (model.squareAspect && len < NYQUIST_DECIMATE_THRESHOLD) {
      // Parametric curve, small enough: render every point verbatim.
      pts = Array.from({ length: len }, (_, k) => [k, line.y[k]] as [number, number]);
    } else {
      let i0 = 0, i1 = len - 1;
      if (!model.squareAspect && model.xRange
        && (line.xMonotonic ?? isMonotonicNonDecreasing(line.x))) {
        const lb = lowerBound(line.x, xDomain[0]);
        const ub = upperBound(line.x, xDomain[1]);
        if (lb >= len || ub < 0) {
          i0 = 0; i1 = -1;                          // window entirely outside the data → empty path
        } else {
          // Zoom window: decimate only the visible slice (+1 sample
          // margin each side). NOTE: a window BETWEEN two adjacent
          // samples has ub === lb - 1 — that is NOT empty; the margins
          // keep the bridging segment across the window alive.
          i0 = Math.max(0, lb - 1);
          i1 = Math.min(len - 1, ub + 1);
        }
      }
      pts = minMaxDecimate(line.y, i0, i1, columns);
    }
    let d = '';
    for (const [i, v] of pts) {
      const X = sx(line.x[i]), Y = scaleY(v);
      if (!Number.isFinite(X) || !Number.isFinite(Y)) continue;
      d += (d ? 'L' : 'M') + X.toFixed(1) + ',' + Y.toFixed(1);
    }
    return { d, color: line.color, opacity: line.opacity, width: line.width, dashed: line.dashed };
  });

  return {
    paths, xDomain, yDomain,
    xTicks: niceTicks(xDomain[0], xDomain[1]).map(v => ({ v, px: sx(v) })),
    yTicks: niceTicks(yDomain[0], yDomain[1]).map(v => ({ v, px: sy(v) })),
    y2Ticks: model.y2Range ? niceTicks(model.y2Range[0], model.y2Range[1], 4).map(v => ({ v, px: sy2(v) })) : [],
  };
}
