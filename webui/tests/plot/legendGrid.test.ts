import { expect, test } from 'vitest';
import { legendGrid, legendWrapColumns } from '../../src/lib/plot/legendGrid';
import type { LegendEntry } from '../../src/lib/stores/selection';

/** Build a legend entry the way `selection.legendRows` does. */
const entry = (setId: number, ch: number, over: Partial<LegendEntry> = {}): LegendEntry => ({
  setId, ch, label: `set${setId} · ch_${ch}`, color: `#00${setId}${ch}00`, state: 'on', ...over,
});

// ---- full-mode column wrapping ----

test('legendWrapColumns: 1 column up to 10 entries, 2 to 20, capped at 3', () => {
  expect(legendWrapColumns(0)).toBe(1);
  expect(legendWrapColumns(1)).toBe(1);
  expect(legendWrapColumns(10)).toBe(1);   // classic single column up to 10
  expect(legendWrapColumns(11)).toBe(2);   // wrap threshold
  expect(legendWrapColumns(20)).toBe(2);
  expect(legendWrapColumns(21)).toBe(3);   // cap
  expect(legendWrapColumns(64)).toBe(3);
});

// ---- compact-mode dot grid ----

test('legendGrid: one row per set (entry order), one column per channel', () => {
  // Two 2-ch data sets + a 3-ch set — the legendRows order (per set,
  // channels ascending).
  const rows = [
    entry(3, 0), entry(3, 1),
    entry(7, 0), entry(7, 1), entry(7, 2),
    entry(9, 0), entry(9, 1),
  ];
  const g = legendGrid(rows);
  expect(g.nRows).toBe(3);                 // three distinct sets
  expect(g.nCols).toBe(3);                 // widest set has 3 channels
  // Row index follows first appearance; column index is the channel.
  expect(g.cells.map(c => [c.setId, c.ch, c.row, c.col])).toEqual([
    [3, 0, 0, 0], [3, 1, 0, 1],
    [7, 0, 1, 0], [7, 1, 1, 1], [7, 2, 1, 2],
    [9, 0, 2, 0], [9, 1, 2, 1],
  ]);
});

test('legendGrid: fit pseudo-set rows (listed last) form their own trailing row', () => {
  const rows = [
    entry(1, 0), entry(1, 1),
    // The modal-fit pseudo-set gets its own id and is appended after
    // every data set by legendRows — so it must land on its own row.
    entry(42, 0, { label: 'Fit · recon ch_0' }), entry(42, 1, { label: 'Fit · recon ch_1' }),
  ];
  const g = legendGrid(rows);
  expect(g.nRows).toBe(2);
  const fitCells = g.cells.filter(c => c.setId === 42);
  expect(fitCells.every(c => c.row === 1)).toBe(true);   // trailing row of its own
  expect(fitCells.map(c => c.col)).toEqual([0, 1]);
});

test('legendGrid: cells pass label/colour/tri-state through unchanged', () => {
  const g = legendGrid([
    entry(2, 0, { state: 'on' }),
    entry(2, 1, { state: 'fade' }),
    entry(2, 2, { state: 'off', label: 'run 2 · accel', color: '#a1b2c3' }),
  ]);
  expect(g.cells[1].state).toBe('fade');
  expect(g.cells[2]).toMatchObject({
    state: 'off', label: 'run 2 · accel', color: '#a1b2c3', row: 0, col: 2,
  });
});

test('legendGrid: non-contiguous channels keep channel-index alignment (gap columns)', () => {
  // The TF view's override entries drop the input channel: a set may
  // list ch 1 and 2 only. Columns stay keyed by channel index so the
  // same channel aligns vertically across sets — col 0 is just empty.
  const g = legendGrid([entry(5, 1), entry(5, 2)]);
  expect(g.nRows).toBe(1);
  expect(g.nCols).toBe(3);                        // max ch + 1, gap at col 0
  expect(g.cells.map(c => c.col)).toEqual([1, 2]);
});

test('legendGrid: empty input yields an empty grid', () => {
  expect(legendGrid([])).toEqual({ nRows: 0, nCols: 0, cells: [] });
});
