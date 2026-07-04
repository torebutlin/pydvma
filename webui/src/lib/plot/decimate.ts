/**
 * Min-max decimation for plot rendering: reduce a sample window to at
 * most two points per pixel column while guaranteeing every local
 * extreme (spikes included) stays visible.
 *
 * Pure function — no DOM, no Svelte. Unit-tested in
 * `tests/plot/decimate.test.ts`; the throughput budget is enforced by
 * `tests/plot/perf.test.ts`.
 */

/**
 * Decimate `y[i0..i1]` (inclusive) to at most `2 * columns` points by
 * keeping the min and max sample of each pixel column, ordered by
 * index so the resulting polyline never doubles back.
 *
 * Returns `[index, value]` pairs — indices into the ORIGINAL array,
 * so the caller can look up the matching x value. Windows short
 * enough to draw directly (`n <= 2 * columns`) are passed through
 * untouched, one point per sample.
 *
 * Assumes samples are ordered by x along the index axis (true for
 * time and frequency data). Not meaningful for parametric curves
 * such as Nyquist loci — the caller must skip decimation there.
 */
export function minMaxDecimate(
  y: ArrayLike<number>, i0: number, i1: number, columns: number,
): Array<[number, number]> {
  const n = i1 - i0 + 1;
  if (n <= columns * 2) {
    return Array.from({ length: Math.max(0, n) }, (_, k) => [i0 + k, y[i0 + k]] as [number, number]);
  }
  const out: Array<[number, number]> = [];
  for (let c = 0; c < columns; c++) {
    const a = i0 + Math.floor((c * n) / columns);
    const b = i0 + Math.floor(((c + 1) * n) / columns) - 1;
    let lo = y[a], hi = y[a], loI = a, hiI = a;
    for (let i = a + 1; i <= b; i++) {
      if (y[i] < lo) { lo = y[i]; loI = i; }
      if (y[i] > hi) { hi = y[i]; hiI = i; }
    }
    out.push(loI <= hiI ? [loI, lo] : [hiI, hi]);
    if (loI !== hiI) out.push(loI <= hiI ? [hiI, hi] : [loI, lo]);
  }
  return out;
}
