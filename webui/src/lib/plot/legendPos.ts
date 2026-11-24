/**
 * Legend placement maths (design spec §6). Pure functions shared by
 * `Legend.svelte` (drag clamping) and `ZoomToolbar.svelte` (corner
 * presets), unit-tested in `tests/plot/legendPos.test.ts`.
 *
 * Positions are FRACTIONAL: `x`/`y` in `[0, 1]` map across the axes
 * frame (PlotSurface's data rect, see `FrameInsets`), with `(0, 0)` =
 * top-left and `(1, 1)` = bottom-right (matplotlib `loc`/`bbox_to_anchor`
 * convention). The printed figure (`lib/export/legendOverlay.ts`) reads
 * the same fractions across its own frame. Values slightly past 1 (e.g.
 * `outside-right` at `x = 1.02`) intentionally park the card just outside
 * the axes; a free drag may also store fractions a little below 0 or
 * past 1, where the card sits over the plot's margins.
 */

/**
 * Where the axes frame sits inside its plot host: px from each edge of the
 * host (PlotSurface's own box) to the matching edge of the data rect, so
 * `left`/`top` are the frame's origin and `right`/`bottom` the margins
 * beyond it. PlotSurface publishes it through its bindable `frame` prop
 * (margins L58/T16/B42, R18 or 56 with a right axis; Nyquist's centred
 * square adds its centring offsets). `Legend.svelte` lays its card out in
 * a box at these insets, so its fractions and presets refer to the frame.
 */
export interface FrameInsets { left: number; top: number; right: number; bottom: number }

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
 * reachable. By default `x` is kept in `[0, 1.05]` (the same slack past the
 * right axis as the `outside-right` preset) and `y` in `[0, 1.0]`; `lim`
 * replaces those bounds, which `Legend.svelte` widens to the whole plot host
 * (the frame plus its margins, as fractions of the frame) so a drag may sit
 * over the margins. Points already in range pass through unchanged.
 * `Legend.svelte` also clamps the card's measured box inside the host on
 * screen (px exact, which fractions cannot be) and commits a drop as the
 * fraction of the edges it is anchored by.
 */
export const clampLegend = (
  pos: { x: number; y: number },
  lim: { x: [number, number]; y: [number, number] } = { x: [0, 1.05], y: [0, 1.0] },
) => ({
  x: Math.min(lim.x[1], Math.max(lim.x[0], pos.x)),
  y: Math.min(lim.y[1], Math.max(lim.y[0], pos.y)),
});
