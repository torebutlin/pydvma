/**
 * The print legend: lays a figure's legend out in points for the print
 * renderer (`printFigure.ts`), measured with the embedded figure font, and
 * returns it as an SVG fragment in the renderer's quarter-point units.
 *
 * Placement is relative to the axes frame (the first pane's data rect), never
 * the canvas:
 * - `{ kind: 'position', x, y }` maps the on-screen legend's fractions across
 *   the frame, anchoring the card's right (bottom) edge there past 0.5, and
 *   clamps the card into the frame `LEGEND_INSET_PT` in from its edges;
 *   `x > 1` (outside-right) may sit in the right margin and is clamped into
 *   the canvas instead.
 * - `{ kind: 'best' }` tries the four corners at the inset and takes the one
 *   covering the fewest plotted points, ties going se, ne, nw, sw.
 * - A card that fits the frame at no column count, or a best corner that
 *   still covers more than `max(2, 0.5 %)` of the points, becomes an unboxed
 *   block below the axes, which grows the figure.
 *
 * Every row is written in full (swatch and label); a label too wide for the
 * canvas is shortened with a trailing `…`.
 *
 * Restyle contract (`figure.ts`'s `prepareSvg`): the card is a
 * `data-role="legend-bg"` rect (its own role, so a transparent canvas leaves its
 * white fill alone while dark mode recolours it) carrying `PRINT_CHROME.bg` and `PRINT_CHROME.card`
 * inline, the labels are `data-role="axis"` text in `PRINT_CHROME.ink`, and the
 * swatches carry no data-role, so data colours pass through every background
 * mode untouched. Faded rows (swatch and label) sit in a group at 0.55 opacity.
 *
 * Units, type sizes, marker sizes and the SVG writers come from the shared leaf
 * `printSvg.ts`; from `printFigure.ts` this module takes types only. Pure
 * string building: node-testable, no DOM.
 */
import { PRINT_CHROME } from '../plot/chrome';
import { legendWrapColumns } from '../plot/legendGrid';
import { FONT_ASCENT, FONT_DESCENT, measureText } from './figureFont';
import type { PrintLegend, PrintLegendEntry, PrintText, PtBox } from './printFigure';
import {
  CIRCLE_R_PT, CIRCLE_STROKE_PT, CROSS_STROKE_PT, DASH_PT, EDGE_PT, FONT_FAMILY_ATTR, MARK_HALF_PT, PRINT_TYPE,
  escAttr, escText, opa, sty, u,
} from './printSvg';

/**
 * Gap between the axes frame and a legend card placed inside it, pt
 * (0.6 × the 9 pt legend type).
 */
export const LEGEND_INSET_PT = 5.4;

// Sizes in em of the legend type (`PRINT_TYPE.legendPt`, 9 pt).
/** Swatch length. */
const SWATCH_EM = 1.6;
/** Swatch to label. */
const SWATCH_GAP_EM = 0.5;
/** Card padding, each side. */
const PAD_EM = 0.45;
/** Row pitch. */
const ROW_EM = 1.25;
/** Gap between columns: in a card, and in the block below the axes. */
const CARD_COL_GAP_EM = 1.2;
const BELOW_COL_GAP_EM = 1.6;
/** Gap above and below the block below the axes. */
const BELOW_GAP_EM = 0.3;
/** A label's baseline sits this far below its row's centre line, centring it. */
const LABEL_MID_EM = 0.34;

/** Line swatch stroke width, pt. */
const SWATCH_STROKE_PT = 1.6;
/** Card fill opacity, border width and corner radius, pt. */
const CARD_FILL_OPACITY = 0.92;
const CARD_STROKE_PT = 0.5;
const CARD_RADIUS_PT = 2;
/** Opacity of a faded row. */
const FADED_OPACITY = 0.55;

/** Corner order for `'best'`: also the tie-break order. */
const CORNERS = ['se', 'ne', 'nw', 'sw'] as const;

/**
 * What `layoutPrintLegend` lays out, all in pt with the figure's origin at
 * its top-left corner, y down.
 */
export interface LegendLayoutArgs {
  /** The rows and their placement. */
  legend: PrintLegend;
  /** The axes frame the legend belongs to (the first pane's data rect). */
  frame: PtBox;
  /** The figure's canvas before the legend grows it. */
  canvas: { w: number; h: number };
  /**
   * The bottom of the last pane's lowest text (its x label), pt. A block below
   * the axes starts 0.3 em under it.
   */
  belowTopPt: number;
  /** Plotted points of the first pane, pt, for `'best'`. */
  points: ReadonlyArray<readonly [number, number]>;
}

/**
 * A laid-out legend: its SVG fragment (quarter-point units, absolute
 * coordinates), its box in pt (`below` when it is the block under the axes),
 * how much the figure must grow to hold it, pt (0 for a card), and every label
 * it drew, with `role: 'legend'`, in entry order.
 */
export interface LegendLayout { svg: string; box: PtBox & { below: boolean }; extraHeightPt: number; texts: PrintText[] }

/** Card or block columns: rows per column, each column's width, and the overall size, pt. */
interface Columns { per: number; colW: number[]; w: number; h: number }

/**
 * Lay out a print legend (see the module header for the rules) and return its
 * SVG, box and labels, or null when it has no entries.
 *
 * Sizes are in em of the 9 pt legend type: swatch 1.6, swatch-to-label gap
 * 0.5, card padding 0.45, row 1.25, column gap 1.2 in a card and 1.6 below the
 * axes. A card's columns fill top to bottom, each as wide as its longest
 * label; `cardColumns` picks how many must fit the frame less two insets
 * (outside-right: as wide as the canvas less its 3 pt edges). When no count
 * fits, the legend goes below the axes. The block below starts 0.3 em under
 * `belowTopPt`, has as many equal columns as fit the frame's width, is centred
 * on the frame and kept 3 pt inside the canvas; `extraHeightPt` keeps 0.3 em
 * under it. A label wider than the canvas less its edges, a swatch, a gap and
 * two paddings is shortened, character by character, with a trailing `…`.
 *
 * Markup: card `<rect data-role="legend-bg">` filled `#ffffff` at 0.92 opacity
 * with a 0.5 pt `#c5cad3` border and 2 pt corners; labels `<text
 * data-role="axis" class="legend">` at 9 pt in `#1d2027`; a line swatch
 * (`line`, `dash`, `xline`) is a 1.6 em line stroked 1.6 pt (`dash` 2.4/1.8
 * pt), a × one path and a ○ a circle at the plot's marker sizes, centred on
 * the swatch, all in the entry's colour.
 */
export function layoutPrintLegend(a: LegendLayoutArgs): LegendLayout | null {
  const { legend, frame, canvas } = a;
  const n = legend.entries.length;
  if (n === 0) return null;
  const em = PRINT_TYPE.legendPt;
  const sw = SWATCH_EM * em, gap = SWATCH_GAP_EM * em, pad = PAD_EM * em, row = ROW_EM * em;
  const maxLabel = canvas.w - 2 * EDGE_PT - sw - gap - 2 * pad;
  const labels = legend.entries.map((e) => fitLabel(e.label, em, maxLabel));
  const widths = labels.map((l) => measureText(l, em));

  const p = legend.placement;
  const outsideRight = p.kind === 'position' && p.x > 1;
  const maxW = outsideRight ? canvas.w - 2 * EDGE_PT : frame.w - 2 * LEGEND_INSET_PT;
  const maxH = frame.h - 2 * LEGEND_INSET_PT;
  const cgap = CARD_COL_GAP_EM * em;
  const c = cardColumns(n, (k) => columns(widths, k, sw + gap, cgap, pad, row), maxW, maxH);

  if (c) {
    const inset = LEGEND_INSET_PT;
    const lo = { x: frame.x + inset, y: frame.y + inset };
    const hi = { x: frame.x + frame.w - inset - c.w, y: frame.y + frame.h - inset - c.h };
    let box: PtBox | null;
    if (p.kind === 'position') {
      let bx = frame.x + p.x * frame.w - (p.x > 0.5 ? c.w : 0);
      let by = frame.y + p.y * frame.h - (p.y > 0.5 ? c.h : 0);
      if (outsideRight) {
        bx = clamp(bx, EDGE_PT, canvas.w - EDGE_PT - c.w);
        by = clamp(by, EDGE_PT, canvas.h - EDGE_PT - c.h);
      } else {
        bx = clamp(bx, lo.x, hi.x);
        by = clamp(by, lo.y, hi.y);
      }
      box = { x: bx, y: by, w: c.w, h: c.h };
    } else {
      box = bestCorner(lo, hi, c, a.points);
    }
    if (box) return drawCard(legend.entries, labels, widths, box, c, sw, gap, pad, row, cgap);
  }
  return drawBelow(a, labels, widths, sw, gap, row);
}

/**
 * The card's columns for `n` rows, sized by `card(k)` for k columns, that fit
 * `maxW` × `maxH` (pt), or null when no count does. It starts at
 * `legendWrapColumns(n)`. Too tall there, it takes the fewest more columns
 * that fit (more columns are never taller). Too wide there, it steps down
 * towards one column while the card still fits the height (fewer columns are
 * never shorter), then tries more columns, since width need not grow with the
 * count.
 */
function cardColumns(n: number, card: (k: number) => Columns, maxW: number, maxH: number): Columns | null {
  const fits = (c: Columns) => c.w <= maxW && c.h <= maxH;
  const start = Math.min(n, legendWrapColumns(n));
  const first = card(start);
  if (fits(first)) return first;
  const more = (): Columns | null => {
    for (let k = start + 1; k <= n; k++) { const c = card(k); if (fits(c)) return c; }
    return null;
  };
  const fewer = (): Columns | null => {
    for (let k = start - 1; k >= 1; k--) {
      const c = card(k);
      if (c.h > maxH) return null;
      if (c.w <= maxW) return c;
    }
    return null;
  };
  return first.h > maxH ? more() : fewer() ?? more();
}

/**
 * The corner box covering the fewest of `points` (ties in `CORNERS` order),
 * or null when even that one covers more than `max(2, 0.5 %)` of them.
 */
function bestCorner(
  lo: { x: number; y: number }, hi: { x: number; y: number }, c: Columns,
  points: ReadonlyArray<readonly [number, number]>,
): PtBox | null {
  let best: PtBox | null = null;
  let fewest = Infinity;
  for (const corner of CORNERS) {
    const x = corner[1] === 'e' ? hi.x : lo.x;
    const y = corner[0] === 's' ? hi.y : lo.y;
    let count = 0;
    for (const [px, py] of points) if (px >= x && px <= x + c.w && py >= y && py <= y + c.h) count++;
    if (count < fewest) { fewest = count; best = { x, y, w: c.w, h: c.h }; }
  }
  return fewest > Math.max(2, 0.005 * points.length) ? null : best;
}

/**
 * Rows split into `cols` columns filled top to bottom (fewer when the rows run
 * out first), each column `lead` (swatch + gap) plus its widest label wide,
 * with `pad` round the whole. Sizes in pt.
 */
function columns(widths: readonly number[], cols: number, lead: number, cgap: number, pad: number, row: number): Columns {
  const per = Math.ceil(widths.length / cols);
  const used = Math.ceil(widths.length / per);
  const colW = Array.from({ length: used }, (_, k) => lead + Math.max(0, ...widths.slice(k * per, (k + 1) * per)));
  return { per, colW, w: 2 * pad + colW.reduce((s, v) => s + v, 0) + cgap * (used - 1), h: 2 * pad + row * per };
}

/** The legend as a card at `box` (pt). */
function drawCard(
  entries: readonly PrintLegendEntry[], labels: readonly string[], widths: readonly number[], box: PtBox,
  c: Columns, sw: number, gap: number, pad: number, row: number, cgap: number,
): LegendLayout {
  const parts = [`<g class="legend"><rect data-role="legend-bg" x="${u(box.x)}" y="${u(box.y)}" width="${u(box.w)}" `
    + `height="${u(box.h)}" fill="${PRINT_CHROME.bg}" fill-opacity="${opa(CARD_FILL_OPACITY)}" `
    + `stroke="${PRINT_CHROME.card}" stroke-width="${sty(CARD_STROKE_PT)}" rx="${sty(CARD_RADIUS_PT)}"/>`];
  const texts: PrintText[] = [];
  const colX = c.colW.map((_, k) => box.x + pad + c.colW.slice(0, k).reduce((s, v) => s + v, 0) + cgap * k);
  entries.forEach((e, i) => {
    const k = Math.floor(i / c.per), r = i % c.per;
    const drawn = rowSvg(e, labels[i], widths[i], colX[k], box.y + pad + row * (r + 0.5), sw, gap);
    parts.push(drawn.svg); texts.push(drawn.text);
  });
  parts.push('</g>');
  return { svg: parts.join(''), box: { ...box, below: false }, extraHeightPt: 0, texts };
}

/**
 * The legend as an unboxed block under the axes: equal columns (as many as fit
 * the frame's width, filled top to bottom), centred on the frame and kept
 * `EDGE_PT` inside the canvas, 0.3 em under `belowTopPt`.
 */
function drawBelow(
  a: LegendLayoutArgs, labels: readonly string[], widths: readonly number[], sw: number, gap: number, row: number,
): LegendLayout {
  const { legend, frame, canvas } = a;
  const em = PRINT_TYPE.legendPt;
  const n = labels.length;
  const cgap = BELOW_COL_GAP_EM * em;
  const cw = sw + gap + Math.max(0, ...widths);
  const fit = Math.max(1, Math.min(n, Math.floor((frame.w + cgap) / (cw + cgap))));
  const per = Math.ceil(n / fit);
  const cols = Math.ceil(n / per);
  const w = cols * cw + (cols - 1) * cgap, h = per * row;
  const x = Math.max(EDGE_PT, Math.min(frame.x + (frame.w - w) / 2, canvas.w - EDGE_PT - w));
  const y = a.belowTopPt + BELOW_GAP_EM * em;
  const parts = ['<g class="legend">'];
  const texts: PrintText[] = [];
  legend.entries.forEach((e, i) => {
    const k = Math.floor(i / per), r = i % per;
    const drawn = rowSvg(e, labels[i], widths[i], x + k * (cw + cgap), y + row * (r + 0.5), sw, gap);
    parts.push(drawn.svg); texts.push(drawn.text);
  });
  parts.push('</g>');
  return {
    svg: parts.join(''),
    box: { x, y, w, h, below: true },
    extraHeightPt: Math.max(0, y + h + BELOW_GAP_EM * em - canvas.h),
    texts,
  };
}

/** One row: the swatch from `x0` and the label after it, centred on `cy` (pt). */
function rowSvg(
  e: PrintLegendEntry, label: string, labelW: number, x0: number, cy: number, sw: number, gap: number,
): { svg: string; text: PrintText } {
  const em = PRINT_TYPE.legendPt;
  const stroke = escAttr(e.color);
  const parts: string[] = [];
  if (e.style === 'line' || e.style === 'dash' || e.style === 'xline') {
    const dash = e.style === 'dash' ? ` stroke-dasharray="${sty(DASH_PT[0])} ${sty(DASH_PT[1])}"` : '';
    parts.push(`<line x1="${u(x0)}" y1="${u(cy)}" x2="${u(x0 + sw)}" y2="${u(cy)}" stroke="${stroke}" `
      + `stroke-width="${sty(SWATCH_STROKE_PT)}"${dash}/>`);
  }
  const mx = x0 + sw / 2;
  if (e.style === 'x' || e.style === 'xline') {
    const h = MARK_HALF_PT;
    parts.push(`<path d="M${u(mx - h)},${u(cy - h)}L${u(mx + h)},${u(cy + h)}M${u(mx - h)},${u(cy + h)}L${u(mx + h)},${u(cy - h)}" `
      + `fill="none" stroke="${stroke}" stroke-width="${sty(CROSS_STROKE_PT)}"/>`);
  }
  if (e.style === 'o') {
    parts.push(`<circle cx="${u(mx)}" cy="${u(cy)}" r="${sty(CIRCLE_R_PT)}" fill="none" stroke="${stroke}" `
      + `stroke-width="${sty(CIRCLE_STROKE_PT)}"/>`);
  }
  const tx = x0 + sw + gap, base = cy + LABEL_MID_EM * em;
  parts.push(`<text data-role="axis" class="legend" font-family="${FONT_FAMILY_ATTR}" font-size="${sty(em)}" `
    + `fill="${PRINT_CHROME.ink}" x="${u(tx)}" y="${u(base)}">${escText(label)}</text>`);
  const body = parts.join('');
  return {
    svg: e.faded ? `<g opacity="${opa(FADED_OPACITY)}">${body}</g>` : body,
    text: { text: label, role: 'legend', box: { x: tx, y: base - FONT_ASCENT * em, w: labelW, h: (FONT_ASCENT + FONT_DESCENT) * em } },
  };
}

/**
 * `text` as it fits `maxPt` at `sizePt`: whole when it fits, else its longest
 * prefix (by code point, trailing spaces dropped) that fits with a `…` after it.
 */
function fitLabel(text: string, sizePt: number, maxPt: number): string {
  if (measureText(text, sizePt) <= maxPt) return text;
  const room = maxPt - measureText('…', sizePt);
  let out = '', w = 0;
  for (const ch of text) {
    const cw = measureText(ch, sizePt);
    if (w + cw > room) break;
    out += ch; w += cw;
  }
  return `${out.trimEnd()}…`;
}

/** `v` kept in `[lo, hi]` (`lo` wins when the range is empty). */
function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(v, hi));
}
