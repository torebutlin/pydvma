/**
 * The units, sizes and SVG writers that the print renderer (`printFigure.ts`)
 * and the print legend (`legendOverlay.ts`) share.
 *
 * A leaf: it imports only the figure font, never either of those modules, so
 * neither depends on the other at run time. `printFigure.ts` re-exports
 * `PRINT_TYPE` and `UNITS_PER_PT`, which belong to its public contract.
 *
 * Numbers are written in SVG units (`UNITS_PER_PT` = 4 per pt): geometry with
 * one decimal (`geo`, `u`), style numbers with at most one decimal and no
 * trailing `.0` (`sty`).
 */
import { FIGURE_FONT_STACK } from './figureFont';

/**
 * Print type sizes in points: 10 pt axis labels, 9 pt tick numbers and 9 pt
 * legend text. They never shrink: a narrow figure is laid out again instead.
 */
export const PRINT_TYPE = { labelPt: 10, tickPt: 9, legendPt: 9 } as const;

/**
 * SVG user units per point. The viewBox is in quarter points, so `buildPlot`,
 * called with the data rect in units, keeps 4 decimation columns per pt
 * (about 4 px each at 600 dpi). Every size in the SVG is given in units.
 */
export const UNITS_PER_PT = 4;

/** Gap from the canvas edge to the outermost text or legend, pt. */
export const EDGE_PT = 3;
/** Dash and gap of a dashed data line or legend swatch, pt (the screen's `4 3` px × 0.6). */
export const DASH_PT = [2.4, 1.8] as const;
/** Marker half-size, pt: a × spans twice this each way. */
export const MARK_HALF_PT = 2.2;
/** Stroke width of a × marker, pt. */
export const CROSS_STROKE_PT = 0.7;
/** Radius of a ○ marker, pt. */
export const CIRCLE_R_PT = 2.6;
/** Stroke width of a ○ marker, pt. */
export const CIRCLE_STROKE_PT = 0.9;

/** A geometry value (position, size, path coordinate) already in units: one decimal. */
export function geo(units: number): string {
  const s = units.toFixed(1);
  return s === '-0.0' ? '0.0' : s;
}
/** A position or size given in pt, written in units (one decimal). */
export function u(pt: number): string { return geo(pt * UNITS_PER_PT); }
/**
 * A style number given in pt (stroke width, radius, font size, dash), written
 * in units with at most one decimal and no trailing `.0`.
 */
export function sty(pt: number): string { return String(+(pt * UNITS_PER_PT).toFixed(1)); }
/** An opacity, to three decimals. */
export function opa(v: number): string { return String(+v.toFixed(3)); }

/** Escape SVG text content (`&`, `<`, `>`). */
export function escText(s: string): string { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
/** Escape a double-quoted SVG attribute value. */
export function escAttr(s: string): string { return escText(s).replace(/"/g, '&quot;'); }

/** `FIGURE_FONT_STACK`, escaped for a `font-family="…"` attribute. */
export const FONT_FAMILY_ATTR = escAttr(FIGURE_FONT_STACK);
