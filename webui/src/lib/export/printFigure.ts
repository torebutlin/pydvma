/**
 * The print renderer: lays a plot out again for print, at a stated printed
 * width, from the same `PlotModel` the screen draws and through the same
 * `buildPlot`, so the figure shows the screen's data, ranges and ticks with
 * print type, print line weights and margins sized from the actual text.
 *
 * Pure (no DOM), so node tests can check the layout. The result is a
 * self-contained SVG string whose root `width`/`height` are in points and
 * whose viewBox is in quarter points (`UNITS_PER_PT` = 4 units per pt), plus
 * the box of every text it drew, so the layout claims are testable.
 *
 * The chrome follows `figure.ts`'s self-contained-SVG contract: the background
 * is `data-role="plot-bg"`, every gridline, frame and text is
 * `data-role="axis"`, and each carries its `PRINT_CHROME` hex inline, so
 * `prepareSvg`'s transparent and dark modes restyle it. Data lines carry no
 * data-role and keep their colours.
 */
import { buildPlot, type BuiltPlot, type PlotLine, type PlotModel } from '../plot/build';
import { PRINT_CHROME } from '../plot/chrome';
import { fmtTick, scaleLinear, scaleLog } from '../plot/scales';
import { FIGURE_FONT_STACK, FONT_ASCENT, FONT_DESCENT, measureText } from './figureFont';

/**
 * What a figure shows, which picks its aspect (`FIGURE_ASPECTS`): `'bode'`
 * is magnitude over phase, `'nyquist'` a square Real/Imag plot, and
 * `'default'` everything else (time, spectra, TF views, the sonogram).
 */
export type FigureKind = 'default' | 'bode' | 'nyquist';

/**
 * Width : height of the whole figure, by kind: default 16:9, Bode 4:3,
 * Nyquist 1:1. A figure is laid out taller than this only when a rotated
 * axis label would not fit its plot (`PrintFigure.grown`).
 */
export const FIGURE_ASPECTS: Readonly<Record<FigureKind, number>> = Object.freeze({
  default: 16 / 9,
  bode: 4 / 3,
  nyquist: 1,
});

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

/**
 * One axes of a figure: the `PlotModel` the screen renders for it, and an
 * optional raster (a PNG data URL, e.g. the sonogram's heat image) drawn to
 * fill its data rect in place of the gridlines.
 */
export interface PrintPane { model: PlotModel; image?: string }

/**
 * A legend row's swatch: a line, a dashed line, a × marker, a ○ marker, or a
 * line with a × on it.
 */
export type LegendStyle = 'line' | 'dash' | 'x' | 'o' | 'xline';

/** One legend row: its label, colour and swatch; `faded` rows print lighter. */
export interface PrintLegendEntry { label: string; color: string; style: LegendStyle; faded: boolean }

/**
 * Where the legend goes: `'position'` takes the on-screen legend's fractions
 * across the axes frame, and `'best'` picks the corner covering the fewest
 * plotted points.
 */
export type LegendPlacement = { kind: 'position'; x: number; y: number } | { kind: 'best' };

/** A figure's legend: its rows and where to put them. */
export interface PrintLegend { entries: readonly PrintLegendEntry[]; placement: LegendPlacement }

/**
 * What to print: the panes top to bottom, the figure kind (its aspect), the
 * printed width in millimetres, and an optional legend.
 */
export interface PrintFigureInput { panes: PrintPane[]; kind: FigureKind; widthMm: number; legend?: PrintLegend | null }

/** A box in points, origin at the figure's top-left corner, y down. */
export interface PtBox { x: number; y: number; w: number; h: number }

/**
 * A string the figure drew, with its role and its box in points. The box is
 * the advance width by the font's ascent plus descent, turned for rotated
 * text. Every string is listed, so the PDF writer can check the font has
 * every glyph.
 */
export interface PrintText { text: string; role: 'tick' | 'label' | 'legend'; box: PtBox }

/**
 * A laid-out figure: the SVG, its size in points, whether it was laid out
 * taller than its kind's aspect to fit a label (`grown`), every text drawn,
 * the axes frame of each pane in points, and the legend's box (`below` when
 * it sits under the axes), or null with no legend.
 */
export interface PrintFigure {
  svg: string; widthPt: number; heightPt: number; grown: boolean;
  texts: PrintText[]; frames: PtBox[]; legendBox: (PtBox & { below: boolean }) | null;
}

/**
 * How a Bode figure's data height is shared: magnitude 60 %, phase 40 %
 * (fractions of the data height left after the gap between the panes).
 */
export const BODE_SPLIT = [0.6, 0.4] as const;
/** Gap between stacked panes, pt: the top pane's frame to the next pane's frame. */
export const PANE_GAP_PT = 9;

/** Gap from the canvas edge to the outermost text, pt. */
const EDGE_PT = 3;
/** Gap between the frame and its tick numbers, pt (0.4 × the tick size). */
const TICK_PAD_PT = 0.4 * PRINT_TYPE.tickPt;
/** Gap between tick numbers and their axis label, pt (0.35 × the label size). */
const LABEL_PAD_PT = 0.35 * PRINT_TYPE.labelPt;
/** An unrotated text's baseline sits this many em below the top of its line. */
const BASELINE_EM = 0.8;
/** A y tick number's baseline sits this many em below its tick, centring it. */
const Y_TICK_BASELINE_EM = 0.33;
/** Data line width per on-screen px, pt. */
const LINE_PT_PER_PX = 2 / 3;
/** Dash and gap of a dashed data line, pt (the screen's `4 3` px × 0.6). */
const DASH_PT = [2.4, 1.8] as const;
/** Frame and gridline stroke widths, pt. */
const FRAME_PT = 0.6;
const GRID_PT = 0.4;
/** Marker half-size, pt; a × is stroked 0.7 pt, a ○ has radius 2.6 pt, stroked 0.9 pt. */
const MARK_HALF_PT = 2.2;
const CROSS_STROKE_PT = 0.7;
const CIRCLE_R_PT = 2.6;
const CIRCLE_STROKE_PT = 0.9;
/** Points per millimetre. */
const PT_PER_MM = 72 / 25.4;

/** A geometry value (position, size, path coordinate) in units: one decimal. */
function geo(units: number): string {
  const s = units.toFixed(1);
  return s === '-0.0' ? '0.0' : s;
}
/** A position or size in pt, written in units. */
const u = (pt: number): string => geo(pt * UNITS_PER_PT);
/** A style number in units (stroke width, radius, font size, dash): at most one decimal. */
const sty = (pt: number): string => String(+(pt * UNITS_PER_PT).toFixed(1));
/** An opacity, to three decimals. */
const opa = (v: number): string => String(+v.toFixed(3));

/** Escape text content. */
const escText = (s: string): string => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
/** Escape an attribute value (double-quoted). */
const escAttr = (s: string): string => escText(s).replace(/"/g, '&quot;');

const FONT_ATTR = escAttr(FIGURE_FONT_STACK);

/**
 * A tick number as printed: `fmtTick`'s text with every hyphen-minus turned
 * into a true minus (U+2212), the exponent's included.
 */
export function printTick(v: number, span: number): string {
  return fmtTick(v, span).replace(/-/g, '−');
}

type Anchor = 'start' | 'middle' | 'end';
type Role = 'tick' | 'label';

/** A drawn text: its SVG element and its record. */
interface Drawn { svg: string; text: PrintText }

/** Unrotated text anchored at (x, baseline y), all pt. */
function flatText(text: string, role: Role, sizePt: number, anchor: Anchor, x: number, y: number): Drawn {
  const w = measureText(text, sizePt);
  const left = anchor === 'end' ? x - w : anchor === 'middle' ? x - w / 2 : x;
  return {
    svg: `<text data-role="axis" class="${role}" font-family="${FONT_ATTR}" font-size="${sty(sizePt)}" `
      + `fill="${PRINT_CHROME.ink}" text-anchor="${anchor}" x="${u(x)}" y="${u(y)}">${escText(text)}</text>`,
    text: { text, role, box: { x: left, y: y - FONT_ASCENT * sizePt, w, h: (FONT_ASCENT + FONT_DESCENT) * sizePt } },
  };
}

/**
 * Text turned a quarter, centred on (x, y) along its length, its baseline at
 * x, all pt. `-90` reads bottom to top with the glyphs left of the baseline;
 * `90` reads top to bottom with the glyphs right of it.
 */
function turnedText(text: string, sizePt: number, angle: -90 | 90, x: number, y: number): Drawn {
  const len = measureText(text, sizePt);
  const left = angle === -90 ? x - FONT_ASCENT * sizePt : x - FONT_DESCENT * sizePt;
  return {
    svg: `<text data-role="axis" class="label" font-family="${FONT_ATTR}" font-size="${sty(sizePt)}" `
      + `fill="${PRINT_CHROME.ink}" text-anchor="middle" transform="translate(${u(x)} ${u(y)}) rotate(${angle})">`
      + `${escText(text)}</text>`,
    text: { text, role: 'label', box: { x: left, y: y - len / 2, w: (FONT_ASCENT + FONT_DESCENT) * sizePt, h: len } },
  };
}

/** A pane's texts, measured before the margins are set. */
interface PaneText {
  /** x tick numbers with their position across the data rect (0 left, 1 right). */
  xTicks: Array<{ text: string; frac: number }>;
  /** Widest y and y2 tick number, pt (0 when none). */
  yTickW: number;
  y2TickW: number;
  /** The pane has a right axis (y2 ticks). */
  hasY2: boolean;
  /** The rotated labels it draws ('' when it draws none). */
  yLabel: string;
  y2Label: string;
}

/**
 * Measure a pane's tick numbers and labels. `buildPlot`'s ticks and domains do
 * not depend on the drawing size, so a 1 × 1 build gives each x tick's
 * position as a fraction of the data rect's width.
 */
function measurePane(pane: PrintPane): PaneText {
  const b = buildPlot(pane.model, 1, 1);
  const tickPt = PRINT_TYPE.tickPt;
  const spans = axisSpans(pane.model, b);
  const widest = (ticks: BuiltPlot['yTicks'], span: number) =>
    Math.max(0, ...ticks.map((t) => measureText(printTick(t.v, span), tickPt)));
  const hasY2 = b.y2Ticks.length > 0;
  return {
    xTicks: b.xTicks.map((t) => ({ text: printTick(t.v, spans.x), frac: t.px })),
    yTickW: widest(b.yTicks, spans.y),
    y2TickW: widest(b.y2Ticks, spans.y2),
    hasY2,
    yLabel: pane.model.yLabel,
    y2Label: hasY2 ? pane.model.y2Label ?? '' : '',
  };
}

/** The spans tick numbers are formatted against, as on screen (PlotSurface). */
function axisSpans(model: PlotModel, b: BuiltPlot): { x: number; y: number; y2: number } {
  return {
    x: b.xDomain[1] - b.xDomain[0],
    y: b.yDomain[1] - b.yDomain[0],
    y2: model.y2Range ? model.y2Range[1] - model.y2Range[0] : 1,
  };
}

/** Space round the data rect, pt. */
interface Margins { left: number; right: number; top: number; bottom: number }

/**
 * The margins every pane shares, from the measured text: the widest tick
 * numbers over all panes plus the rotated label line on each side (or a
 * small pad on the right without a right axis), a little over half a tick
 * line on top, the tick line and x label line below. Then each side is raised
 * until the first and last x tick numbers, centred on their ticks, stay 1 pt
 * inside the canvas (for a tick on the frame's edge: half its width + 1).
 */
function figureMargins(panes: readonly PaneText[], widthPt: number): Margins {
  const tick = PRINT_TYPE.tickPt, label = PRINT_TYPE.labelPt;
  const yw = Math.max(0, ...panes.map((p) => p.yTickW));
  let left = EDGE_PT + label + LABEL_PAD_PT + yw + TICK_PAD_PT;
  const right2 = panes.filter((p) => p.hasY2);
  let right = right2.length > 0
    ? EDGE_PT + (right2.some((p) => p.y2Label) ? label + LABEL_PAD_PT : 0)
      + Math.max(...right2.map((p) => p.y2TickW)) + TICK_PAD_PT
    : 0.5 * tick + 2;
  // A tick at fraction f of the data rect sits at left + f·(W − left − right).
  // Solving "its half-width + 1 pt fits before the canvas edge" for one margin
  // couples it to the other, so settle the two together.
  for (let pass = 0; pass < 3; pass++) {
    for (const p of panes) {
      const first = p.xTicks[0], last = p.xTicks[p.xTicks.length - 1];
      if (last && last.frac > 0) {
        const half = measureText(last.text, tick) / 2 + 1;
        right = Math.max(right, (half - (1 - last.frac) * (widthPt - left)) / last.frac);
      }
      if (first && first.frac < 1) {
        const half = measureText(first.text, tick) / 2 + 1;
        left = Math.max(left, (half - first.frac * (widthPt - right)) / (1 - first.frac));
      }
    }
  }
  return {
    left, right,
    top: 0.6 * tick,
    bottom: TICK_PAD_PT + tick + LABEL_PAD_PT + label + EDGE_PT,
  };
}

/**
 * The data height a pane's rotated labels need: the longer label plus a tick
 * line of clearance (0 with no label).
 */
function labelNeed(p: PaneText): number {
  const len = Math.max(measureText(p.yLabel, PRINT_TYPE.labelPt), measureText(p.y2Label, PRINT_TYPE.labelPt));
  return len > 0 ? len + 2 * PRINT_TYPE.tickPt : 0;
}

/** The frame inside a pane's slot: the slot, or its centred square for `squareAspect`. */
function frameIn(slot: PtBox, square: boolean | undefined): PtBox {
  if (!square) return slot;
  const side = Math.min(slot.w, slot.h);
  return { x: slot.x + (slot.w - side) / 2, y: slot.y + (slot.h - side) / 2, w: side, h: side };
}

/** One pane drawn: its SVG and every text in it. */
interface PaneOut { svg: string; texts: PrintText[] }

/**
 * Draw one pane in its frame (pt): image or gridlines, the clipped data lines
 * and markers, the frame, the tick numbers and the axis labels. `k` numbers
 * its clip path; `widthPt` is the canvas width, which the y2 label hangs from
 * and the x label is kept inside. With `xLabels` false (every stacked pane but
 * the last) the x tick numbers and the x label are left out; the gridlines stay.
 */
function layoutPane(pane: PrintPane, k: number, frame: PtBox, widthPt: number, xLabels = true): PaneOut {
  const { model } = pane;
  const { x: ox, y: oy, w: fw, h: fh } = frame;
  const wU = fw * UNITS_PER_PT, hU = fh * UNITS_PER_PT;
  const built = buildPlot(model, wU, hU);
  const spans = axisSpans(model, built);
  const tick = PRINT_TYPE.tickPt, label = PRINT_TYPE.labelPt;
  const parts: string[] = [];
  const texts: PrintText[] = [];
  const put = (d: Drawn) => { parts.push(d.svg); texts.push(d.text); };
  const ax = (px: number) => geo(ox * UNITS_PER_PT + px);
  const ay = (px: number) => geo(oy * UNITS_PER_PT + px);

  if (pane.image) {
    const href = escAttr(pane.image);
    parts.push(`<image x="${u(ox)}" y="${u(oy)}" width="${u(fw)}" height="${u(fh)}" preserveAspectRatio="none" `
      + `image-rendering="pixelated" href="${href}" xlink:href="${href}"/>`);
  } else {
    const grid = `stroke="${PRINT_CHROME.grid}" stroke-width="${sty(GRID_PT)}"`;
    for (const t of built.xTicks) {
      parts.push(`<line data-role="axis" class="grid" x1="${ax(t.px)}" y1="${u(oy)}" x2="${ax(t.px)}" y2="${u(oy + fh)}" ${grid}/>`);
    }
    for (const t of built.yTicks) {
      parts.push(`<line data-role="axis" class="grid" x1="${u(ox)}" y1="${ay(t.px)}" x2="${u(ox + fw)}" y2="${ay(t.px)}" ${grid}/>`);
    }
  }

  const clip = `pf-clip-${k}`;
  parts.push(`<defs><clipPath id="${clip}"><rect x="0" y="0" width="${geo(wU)}" height="${geo(hU)}"/></clipPath></defs>`);
  parts.push(`<g transform="translate(${u(ox)} ${u(oy)})" clip-path="url(#${clip})">`);
  built.paths.forEach((p, i) => {
    const line = model.lines[i];
    if (p.d && !line.markerOnly) {
      const dash = p.dashed ? ` stroke-dasharray="${sty(DASH_PT[0])} ${sty(DASH_PT[1])}"` : '';
      parts.push(`<path d="${p.d}" fill="none" stroke="${escAttr(p.color)}" `
        + `stroke-width="${sty(p.width * LINE_PT_PER_PX)}" opacity="${opa(p.opacity)}"${dash} stroke-linejoin="round"/>`);
    }
    if (line.marker) parts.push(markersSvg(line, model, built, wU, hU));
  });
  parts.push('</g>');

  parts.push(`<rect data-role="axis" class="frame" x="${u(ox)}" y="${u(oy)}" width="${u(fw)}" height="${u(fh)}" `
    + `fill="none" stroke="${PRINT_CHROME.frame}" stroke-width="${sty(FRAME_PT)}"/>`);

  const xTickY = oy + fh + TICK_PAD_PT + BASELINE_EM * tick;
  for (const t of xLabels ? built.xTicks : []) {
    put(flatText(printTick(t.v, spans.x), 'tick', tick, 'middle', ox + t.px / UNITS_PER_PT, xTickY));
  }
  for (const t of built.yTicks) {
    put(flatText(printTick(t.v, spans.y), 'tick', tick, 'end', ox - TICK_PAD_PT,
      oy + t.px / UNITS_PER_PT + Y_TICK_BASELINE_EM * tick));
  }
  for (const t of built.y2Ticks) {
    put(flatText(printTick(t.v, spans.y2), 'tick', tick, 'start', ox + fw + TICK_PAD_PT,
      oy + t.px / UNITS_PER_PT + Y_TICK_BASELINE_EM * tick));
  }

  if (model.xLabel && xLabels) {
    // Centred on the frame, but kept inside the canvas when it fits it.
    const w = measureText(model.xLabel, label);
    let cx = ox + fw / 2;
    if (w <= widthPt - 2 * EDGE_PT) cx = Math.min(Math.max(cx, EDGE_PT + w / 2), widthPt - EDGE_PT - w / 2);
    put(flatText(model.xLabel, 'label', label, 'middle', cx,
      oy + fh + TICK_PAD_PT + tick + LABEL_PAD_PT + BASELINE_EM * label));
  }
  if (model.yLabel) put(turnedText(model.yLabel, label, -90, EDGE_PT + BASELINE_EM * label, oy + fh / 2));
  if (model.y2Label && built.y2Ticks.length > 0) {
    put(turnedText(model.y2Label, label, 90, widthPt - EDGE_PT - BASELINE_EM * label, oy + fh / 2));
  }
  return { svg: parts.join(''), texts };
}

/**
 * A line's markers, in units relative to the data rect: its raw points mapped
 * through the built domains (log where the axis is log, never on a square
 * Nyquist model), skipping points outside them. A ○ per point, or one path of
 * ×s, in the line's colour and opacity.
 */
function markersSvg(line: PlotLine, model: PlotModel, built: BuiltPlot, wU: number, hU: number): string {
  const right = line.yAxis === 'right';
  const xd = built.xDomain;
  const yd: readonly [number, number] = right ? model.y2Range ?? [0, 1] : built.yDomain;
  const logX = model.xScale === 'log' && !model.squareAspect;
  const logY = !right && model.yLogAxis === true && !model.squareAspect;
  const sx = (logX ? scaleLog : scaleLinear)(xd[0], xd[1], 0, wU);
  const sy = (logY ? scaleLog : scaleLinear)(yd[0], yd[1], hU, 0);
  const [xlo, xhi] = [Math.min(xd[0], xd[1]), Math.max(xd[0], xd[1])];
  const [ylo, yhi] = [Math.min(yd[0], yd[1]), Math.max(yd[0], yd[1])];
  const pts: Array<[number, number]> = [];
  const n = Math.min(line.x.length, line.y.length);
  for (let i = 0; i < n; i++) {
    const xv = line.x[i], yv = line.y[i];
    if (!(xv >= xlo && xv <= xhi && yv >= ylo && yv <= yhi)) continue;
    const X = sx(xv), Y = sy(yv);
    if (Number.isFinite(X) && Number.isFinite(Y)) pts.push([X, Y]);
  }
  if (pts.length === 0) return '';
  const stroke = escAttr(line.color), op = opa(line.opacity);
  if (line.marker === 'o') {
    return pts.map(([X, Y]) => `<circle cx="${geo(X)}" cy="${geo(Y)}" r="${sty(CIRCLE_R_PT)}" fill="none" `
      + `stroke="${stroke}" stroke-width="${sty(CIRCLE_STROKE_PT)}" opacity="${op}"/>`).join('');
  }
  const h = MARK_HALF_PT * UNITS_PER_PT;
  const d = pts.map(([X, Y]) => `M${geo(X - h)},${geo(Y - h)}L${geo(X + h)},${geo(Y + h)}`
    + `M${geo(X - h)},${geo(Y + h)}L${geo(X + h)},${geo(Y - h)}`).join('');
  return `<path d="${d}" fill="none" stroke="${stroke}" stroke-width="${sty(CROSS_STROKE_PT)}" opacity="${op}"/>`;
}

/**
 * Lay a figure out for print and return its SVG and layout.
 *
 * The figure is `widthMm` wide (pt = mm / 25.4 × 72) and `FIGURE_ASPECTS[kind]`
 * shaped. Margins come from the measured text: on the left the y label line,
 * the widest y tick number and their gaps (0.35 × 10 pt, 0.4 × 9 pt) from a
 * 3 pt canvas edge; on the right the same for a right axis, else 6.5 pt; at
 * least enough that the end x tick numbers stay 1 pt inside the canvas; 5.4 pt
 * on top; the x tick and x label lines below. When a rotated y or y2 label
 * plus 18 pt is longer than the data height, the height grows to fit and
 * `grown` is true; the type never shrinks.
 *
 * A `squareAspect` (Nyquist) pane draws in a centred square. `buildPlot` runs
 * at the data rect's size in units, so the ticks and decimation match the
 * screen's logic. Data lines print at 2/3 pt per on-screen px, dashed
 * 2.4/1.8 pt; frame 0.6 pt `#3f4652`; gridlines 0.4 pt `#dfe2e7` (none under
 * an image); text `#1d2027` in `FIGURE_FONT_STACK`; no tick marks. Markers
 * (`PlotLine.marker`) are 2.2 pt half-size: × stroked 0.7 pt, ○ radius 2.6 pt
 * stroked 0.9 pt.
 *
 * Lays out one pane (`'default'`, `'nyquist'`) or, for `'bode'`, two stacked
 * panes (magnitude, then phase) and throws on any other count. The Bode panes
 * share one set of margins, so their frames share left and right edges; the
 * data height (after `PANE_GAP_PT` of gap) splits by `BODE_SPLIT`; the grow
 * rule is per pane (label need ÷ share); only the last pane prints x numbers
 * and the x label, the others keep their gridlines. Data lines are stroked
 * with round joins.
 * The legend is not drawn yet: `legendBox` is always null.
 */
export function printFigureSvg(input: PrintFigureInput): PrintFigure {
  const want = input.kind === 'bode' ? 2 : 1;
  if (input.panes.length !== want) {
    throw new Error(`printFigureSvg: kind '${input.kind}' takes ${want === 1 ? 'one pane' : 'two panes'}, got ${input.panes.length}`);
  }
  const shares: readonly number[] = want === 2 ? BODE_SPLIT : [1];
  const W = input.widthMm * PT_PER_MM;
  const H0 = W / FIGURE_ASPECTS[input.kind];
  const measured = input.panes.map(measurePane);
  const m = figureMargins(measured, W);

  // The data height is what is left after the margins and the gaps, shared by
  // `shares`; a pane whose rotated labels need more than its share grows all.
  const gaps = PANE_GAP_PT * (shares.length - 1);
  let dataH = H0 - m.top - m.bottom - gaps;
  const need = Math.max(...measured.map((p, i) => labelNeed(p) / shares[i]));
  const grown = need > dataH;
  if (grown) dataH = need;
  const H = dataH + gaps + m.top + m.bottom;

  const frames: PtBox[] = [];
  const outs: PaneOut[] = [];
  let y = m.top;
  input.panes.forEach((pane, i) => {
    const slot: PtBox = { x: m.left, y, w: Math.max(1, W - m.left - m.right), h: dataH * shares[i] };
    const frame = frameIn(slot, pane.model.squareAspect);
    frames.push(frame);
    outs.push(layoutPane(pane, i, frame, W, i === input.panes.length - 1));
    y += slot.h + PANE_GAP_PT;
  });

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" `
    + `width="${W.toFixed(2)}pt" height="${H.toFixed(2)}pt" viewBox="0 0 ${u(W)} ${u(H)}">`
    + `<rect data-role="plot-bg" x="0" y="0" width="${u(W)}" height="${u(H)}" fill="${PRINT_CHROME.bg}"/>`
    + outs.map((o) => o.svg).join('')
    + '</svg>';
  return { svg, widthPt: W, heightPt: H, grown, texts: outs.flatMap((o) => o.texts), frames, legendBox: null };
}
