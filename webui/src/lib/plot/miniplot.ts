/**
 * Tiny pure helpers for the DampingPanel's mini SVG plots (round-7).
 *
 * Deliberately NOT PlotSurface: the panel draws two small, self-contained
 * charts (start-slice spectrum, decay fits / band EDCs) whose axes never
 * interact with the view-state store, history, gestures or export. A dumb
 * value→pixel mapping plus `niceTicks` is the whole requirement; wiring
 * PlotSurface's store contract in here would be pure overhead.
 */

export interface MiniDomain {
  x: [number, number];
  y: [number, number];
}

/** Finite min/max of one or more series, with a degenerate-span guard. */
export function seriesExtent(series: ArrayLike<number>[]): [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const s of series) {
    for (let i = 0; i < s.length; i++) {
      const v = s[i];
      if (!Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (lo === Infinity) return [0, 1];
  if (lo === hi) return [lo - 0.5, hi + 0.5];
  return [lo, hi];
}

/** Pad a domain by `frac` of its span each side (plot breathing room). */
export function padDomain(d: [number, number], frac = 0.05): [number, number] {
  const m = (d[1] - d[0]) * frac;
  return [d[0] - m, d[1] + m];
}

/** Data x → pixel x over `w` pixels. */
export function pxX(v: number, dom: MiniDomain, w: number): number {
  return ((v - dom.x[0]) / (dom.x[1] - dom.x[0])) * w;
}

/** Data y → pixel y over `h` pixels (pixel y grows DOWN). */
export function pxY(v: number, dom: MiniDomain, h: number): number {
  return h - ((v - dom.y[0]) / (dom.y[1] - dom.y[0])) * h;
}

/**
 * SVG `points` string for a polyline, skipping non-finite samples (NaN gaps
 * split visually because adjacent points collapse — acceptable for these
 * small diagnostic charts).
 */
export function polylinePoints(
  x: ArrayLike<number>, y: ArrayLike<number>, dom: MiniDomain,
  w: number, h: number,
): string {
  const parts: string[] = [];
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(x[i]) || !Number.isFinite(y[i])) continue;
    parts.push(`${pxX(x[i], dom, w).toFixed(1)},${pxY(y[i], dom, h).toFixed(1)}`);
  }
  return parts.join(' ');
}

/**
 * Indices of at most `maxMarkers` evenly-spaced samples — the decay plot
 * draws its measured data as sparse × markers (the Qt plot's style) without
 * flooding the SVG at full sample rate.
 */
export function markerIndices(length: number, maxMarkers = 60): number[] {
  if (length <= maxMarkers) return Array.from({ length }, (_, i) => i);
  const step = (length - 1) / (maxMarkers - 1);
  const out: number[] = [];
  for (let k = 0; k < maxMarkers; k++) out.push(Math.round(k * step));
  return out;
}
