/**
 * Legend placement maths (design spec §6). Pure functions shared by
 * `Legend.svelte` (drag clamping) and `ZoomToolbar.svelte` (corner
 * presets), unit-tested in `tests/plot/legendPos.test.ts`.
 *
 * Positions are FRACTIONAL: `x`/`y` in `[0, 1]` map across the plot's
 * inner drawing area, with `(0, 0)` = top-left and `(1, 1)` =
 * bottom-right (matplotlib `loc`/`bbox_to_anchor` convention). Values
 * slightly past 1 (e.g. `outside-right` at `x = 1.02`) intentionally
 * park the card just outside the axes.
 */

/** The five one-click corner/edge presets exposed on the toolbar. */
export type LegendPreset = 'ne' | 'nw' | 'se' | 'sw' | 'outside-right';

const PRESETS: Record<LegendPreset, { x: number; y: number }> = {
  ne: { x: 0.98, y: 0.02 }, nw: { x: 0.02, y: 0.02 },
  se: { x: 0.98, y: 0.98 }, sw: { x: 0.02, y: 0.98 },
  'outside-right': { x: 1.02, y: 0.02 },
};

/**
 * Fractional `{x, y}` for a named preset. Returns a FRESH object each
 * call, so callers may mutate the result without corrupting the shared
 * preset table.
 */
export const presetToXY = (p: LegendPreset) => ({ ...PRESETS[p] });

/**
 * Clamp a free-dragged fractional position so the legend card stays
 * reachable: `x` in `[0, 1.05]` (a little slack past the right axis so
 * the card can nudge just outside, matching `outside-right`), `y` in
 * `[0, 1.0]`. Points already in range pass through unchanged.
 */
export const clampLegend = (pos: { x: number; y: number }) => ({
  x: Math.min(1.05, Math.max(0, pos.x)),
  y: Math.min(1.0, Math.max(0, pos.y)),
});
