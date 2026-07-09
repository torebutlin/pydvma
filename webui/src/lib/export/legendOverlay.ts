/**
 * Legend overlay for exported figures (round-7d).
 *
 * On screen the legend is an HTML card OUTSIDE the plot SVG, so serialised
 * exports never contained it. This builds an equivalent legend as an SVG
 * STRING that `App.getSvg` appends to the export CLONE when (and only when)
 * the on-screen legend is toggled visible — mirroring its position and the
 * lines it lists.
 *
 * Contract (matches figure.ts's restyle rules):
 * - the card background is a `data-role="plot-bg"` rect with inline
 *   `CHROME.bg` fill + `CHROME.frame` stroke → white/transparent/dark export
 *   modes restyle it exactly like the plot background;
 * - labels are `data-role="axis"` text with inline `CHROME.axis` fill (no
 *   `tick` class → stampFonts gives them the sans label font);
 * - swatches carry each line's own inline stroke and NO data-role, so data
 *   colours pass through untouched (faded lines keep their reduced opacity).
 *
 * Placement mirrors Legend.svelte: fractional x/y over the WHOLE plot region
 * ((0,0) top-left → (1,1) bottom-right), right/bottom-anchored past 0.5 so
 * corner presets pin flush; the box is finally clamped inside the canvas (an
 * on-screen "outside-right" legend has no room outside the exported axes).
 * Entries follow the PLOT, not the interactive list: 'off' rows (struck
 * through on screen purely so they can be clicked back on) are excluded.
 * Beyond 10 entries the rows wrap into balanced columns, like the on-screen
 * card (`legendWrapColumns`). Pure string building — node-testable, and the
 * live DOM is never touched.
 */
import { CHROME } from '../plot/chrome';
import { legendWrapColumns } from '../plot/legendGrid';
import type { LegendEntry } from '../stores/selection';

const ROW_H = 15;
const PAD = 6;
const SWATCH_W = 16;
const SWATCH_GAP = 5;
const COL_GAP = 12;
/** Approximate glyph advance for the 11.5px sans label font (box sizing). */
const CHAR_W = 6.0;
const FONT_SIZE = 11;

/** Escape a label for embedding in SVG text content. */
function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * Build the legend `<g>` markup for an export canvas of `canvas.w × canvas.h`
 * (viewBox units). Returns '' when nothing would be listed (all lines off).
 */
export function legendOverlaySvg(
  entries: readonly LegendEntry[],
  pos: { x: number; y: number },
  canvas: { w: number; h: number },
): string {
  const rows = entries.filter((e) => e.state !== 'off');
  if (rows.length === 0) return '';

  const cols = legendWrapColumns(rows.length);
  const perCol = Math.ceil(rows.length / cols);
  // Per-column width from its longest label (approximate metrics are fine —
  // the box only needs to comfortably contain the text).
  const colWidths: number[] = [];
  for (let c = 0; c < cols; c++) {
    const labels = rows.slice(c * perCol, (c + 1) * perCol).map((r) => r.label.length);
    const maxLen = labels.length ? Math.max(...labels) : 0;
    colWidths.push(SWATCH_W + SWATCH_GAP + maxLen * CHAR_W);
  }
  const boxW = PAD * 2 + colWidths.reduce((a, b) => a + b, 0) + COL_GAP * (cols - 1);
  const boxH = PAD * 2 + perCol * ROW_H;

  // Fraction → px with right/bottom anchoring past 0.5 (Legend.svelte's
  // rule), then clamp fully inside the canvas.
  const ax = pos.x * canvas.w;
  const ay = pos.y * canvas.h;
  let bx = pos.x > 0.5 ? ax - boxW : ax;
  let by = pos.y > 0.5 ? ay - boxH : ay;
  bx = Math.min(Math.max(0, bx), Math.max(0, canvas.w - boxW));
  by = Math.min(Math.max(0, by), Math.max(0, canvas.h - boxH));

  const parts: string[] = [];
  parts.push(`<g data-role="export-legend" transform="translate(${bx.toFixed(1)} ${by.toFixed(1)})">`);
  parts.push(
    `<rect data-role="plot-bg" x="0" y="0" width="${boxW.toFixed(1)}" height="${boxH.toFixed(1)}" ` +
    `rx="4" fill="${CHROME.bg}" stroke="${CHROME.frame}" fill-opacity="0.92"/>`,
  );
  rows.forEach((r, i) => {
    const c = Math.floor(i / perCol);
    const rowInCol = i % perCol;
    const x0 = PAD + colWidths.slice(0, c).reduce((a, b) => a + b, 0) + COL_GAP * c;
    const cy = PAD + rowInCol * ROW_H + ROW_H / 2;
    const dim = r.state === 'fade' ? ' opacity="0.55"' : '';
    parts.push(
      `<line x1="${x0.toFixed(1)}" x2="${(x0 + SWATCH_W).toFixed(1)}" ` +
      `y1="${cy.toFixed(1)}" y2="${cy.toFixed(1)}" stroke="${r.color}" stroke-width="2.5"${dim}/>`,
    );
    parts.push(
      `<text data-role="axis" x="${(x0 + SWATCH_W + SWATCH_GAP).toFixed(1)}" ` +
      `y="${(cy + FONT_SIZE / 2 - 1.5).toFixed(1)}" fill="${CHROME.axis}" ` +
      `font-size="${FONT_SIZE}px"${dim}>${esc(r.label)}</text>`,
    );
  });
  parts.push('</g>');
  return parts.join('');
}
