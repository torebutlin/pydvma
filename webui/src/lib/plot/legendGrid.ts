/**
 * Legend layout maths (post-release feedback: "many lines" legends).
 * Pure functions consumed by `Legend.svelte`, unit-tested in
 * `tests/plot/legendGrid.test.ts`.
 *
 * Two independent concerns live here:
 *
 * 1. `legendWrapColumns` — how many COLUMNS the full (labelled-rows)
 *    legend should wrap into once it has too many entries to stand as
 *    one tall column. Entries keep reading top-to-bottom then across
 *    (`grid-auto-flow: column` in the component), so late-appended
 *    rows — e.g. the modal-fit pseudo-set's recon lines, which
 *    `legendRows` lists after every data set — naturally flow into the
 *    later column(s).
 *
 * 2. `legendGrid` — the COMPACT (dot-grid) legend's arrangement: one
 *    grid ROW per set and one COLUMN per channel index, so channel k
 *    lines up vertically across sets and each set reads as a row of
 *    coloured dots. Fit pseudo-sets have their own `setId`, so they
 *    form their own row(s) below the data sets.
 */
import type { LegendEntry } from '../stores/selection';

/**
 * Column count for the full (labelled-rows) legend: 1 column up to 10
 * entries (identical to the classic single-column legend), 2 columns
 * for 11–20, capped at 3 columns beyond that. Balancing across the
 * columns (row count = ceil(n / columns)) is the component's job.
 */
export function legendWrapColumns(n: number): 1 | 2 | 3 {
  return n > 20 ? 3 : n > 10 ? 2 : 1;
}

/** A legend entry placed at 0-based (row, col) grid coordinates. */
export type LegendGridCell = LegendEntry & { row: number; col: number };

/** The compact legend's dot-grid model (see `legendGrid`). */
export interface LegendGridModel {
  /** Number of grid rows = number of distinct sets, in entry order. */
  nRows: number;
  /** Number of grid columns = max channel index + 1 (0 when empty). */
  nCols: number;
  cells: LegendGridCell[];
}

/**
 * Arrange legend entries into the compact legend's dot grid: one ROW
 * per distinct `setId` (rows ordered by each set's first appearance in
 * `entries`, which matches `selection.legendRows` set order — fit
 * pseudo-sets therefore land on their own trailing rows) and one
 * COLUMN per channel index (`col = ch`), so the same channel aligns
 * vertically across sets.
 *
 * Entries with non-contiguous channels (e.g. the TF view's override
 * rows, which drop the input channel) simply leave that column's cell
 * empty for the set — alignment by channel index is preserved. Each
 * cell carries the source entry's label/colour/tri-state unchanged, so
 * the component can render state (hollow off dots, faded fade dots)
 * and tooltips straight from the cell.
 */
export function legendGrid(entries: readonly LegendEntry[]): LegendGridModel {
  const rowOf = new Map<number, number>();
  const cells: LegendGridCell[] = [];
  let nCols = 0;
  for (const e of entries) {
    let row = rowOf.get(e.setId);
    if (row === undefined) {
      row = rowOf.size;
      rowOf.set(e.setId, row);
    }
    nCols = Math.max(nCols, e.ch + 1);
    cells.push({ ...e, row, col: e.ch });
  }
  return { nRows: rowOf.size, nCols, cells };
}
