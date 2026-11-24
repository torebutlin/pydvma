// figure.ts — figure files: turn a print figure (`printFigure.ts`'s SVG,
// laid out in points for a printed width) into a 600 dpi PNG or a vector PDF
// with the figure font embedded, on a white, transparent or dark background.
//
// The print SVG is self-contained: its background rect is
// `data-role="plot-bg"`, the legend card is `data-role="legend-bg"`, every
// gridline, frame and text is `data-role="axis"`, and each carries its chrome hex and font inline. `prepareSvg` restyles it for
// the chosen background as a PURE string operation (unit-tested); the PNG and
// PDF writers are browser-only (canvas / jsPDF + svg2pdf.js) and are proven by
// the e2e and by eye, not by node tests.
import { CHROME, PRINT_CHROME } from '../plot/chrome';
import { FIGURE_FONT_FAMILY, loadFigureFontBase64 } from './figureFont';
import type { FigureFormat } from './figureSave';
import { withPngDpi } from './pngDpi';
import type { PrintFigure } from './printFigure';

/** Background treatment for an exported figure. */
export type BackgroundMode = 'white' | 'transparent' | 'dark';

/**
 * The dark-mode chrome→dark colour map. KEYED OFF the shared CHROME and
 * PRINT_CHROME values (not repeated light hexes), so it can never drift from
 * what the print renderer (and PlotSurface) actually emit: change a chrome
 * colour without adding its DARK_MAP entry and figure.test.ts's
 * `keys(DARK_MAP) === values(CHROME) ∪ values(PRINT_CHROME)` assertion fails
 * RED.
 *
 * Screen chrome (the inline hexes PlotSurface and the damping charts carry;
 * no figure is drawn from the screen SVG now, but the map covers every chrome
 * hex the app stamps, and `DARK_BG` is the screen's dark plot background too):
 *
 *   bg    CHROME.bg    (#ffffff) → #1b2130  (deep slate page)
 *   grid  CHROME.grid  (#eef0f4) → #2a3346  (dim grid on slate)
 *   frame CHROME.frame (#e3e6eb) → #3a4356  (axis frame, brighter than grid)
 *   axis  CHROME.axis  (#66708a) → #c7cede  (legible light-grey text)
 *
 * Print chrome (printFigure.ts and the print legend, what the figures are
 * drawn in; its bg is CHROME.bg's #ffffff, mapped above):
 *
 *   ink   PRINT_CHROME.ink   (#1d2027) → #e6e9ef  (near-white text)
 *   frame PRINT_CHROME.frame (#3f4652) → #aab2c0  (light axes frame)
 *   grid  PRINT_CHROME.grid  (#dfe2e7) → #2a3346  (dim grid on slate)
 *   card  PRINT_CHROME.card  (#c5cad3) → #3a4356  (legend card border)
 *
 * No mapped value is itself a key, so restyling twice is stable.
 *
 * DATA-LINE colours (#2563eb … from the 12-colour palette) are deliberately
 * ABSENT AND the recolouring is scoped to data-role elements, so a data line
 * whose hue happens to collide with a chrome hex is still preserved.
 */
export const DARK_MAP: Readonly<Record<string, string>> = {
  [CHROME.bg]: '#1b2130', // plot-bg (screen and print)
  [CHROME.grid]: '#2a3346', // gridline stroke
  [CHROME.frame]: '#3a4356', // frame stroke
  [CHROME.axis]: '#c7cede', // tick + axis-label fill
  [PRINT_CHROME.ink]: '#e6e9ef', // print text fill
  [PRINT_CHROME.frame]: '#aab2c0', // print frame stroke
  [PRINT_CHROME.grid]: '#2a3346', // print gridline stroke
  [PRINT_CHROME.card]: '#3a4356', // print legend card border
};

/**
 * Dark plot-background fill, for the canvas/PDF pre-fill in the renderers.
 * Derived from DARK_MAP so it can never disagree with the SVG's recoloured
 * plot-bg (both are "what CHROME.bg maps to in dark mode").
 */
export const DARK_BG = DARK_MAP[CHROME.bg];

/**
 * Rewrite ONLY the opening tags that carry a `data-role="axis"`,
 * `data-role="plot-bg"` or `data-role="legend-bg"` attribute, applying `fn` to each such tag's text.
 * Elements without a data-role (the data `<path>`s and markers, <defs>, <g>,
 * a sonogram's `<image>`) pass through untouched — that is what keeps data
 * line colours safe. Operates on the serialised string, not the DOM, so it
 * runs under node for the unit tests.
 */
function mapRoleTags(svgText: string, fn: (tag: string) => string): string {
  // Match a single element's opening tag: `<name ...>` (non-greedy, no '>').
  return svgText.replace(/<[a-zA-Z][^>]*>/g, (tag) =>
    /data-role="(axis|plot-bg|legend-bg)"/.test(tag) ? fn(tag) : tag,
  );
}

/**
 * Restyle a self-contained figure SVG for the chosen background.
 *
 *   'white'       — returned unchanged (the figure as drawn).
 *   'transparent' — the plot-bg rect's fill → "none" (page/checkerboard shows
 *                   through); ALL axis chrome, the legend card (keeps its white
 *                   fill, so its text stays legible) and the data lines are untouched.
 *   'dark'        — the plot-bg fill → #1b2130 AND every axis-chrome hex is
 *                   swapped via DARK_MAP (gridlines, frame, text, legend card);
 *                   scoped to data-role elements so DATA-LINE strokes are
 *                   preserved.
 *
 * The input is a print figure's SVG (data-role tags carrying inline
 * fill/stroke; its text already names the figure font and size). Idempotent
 * for 'dark' (the mapped hexes are not themselves keys), so re-running is
 * stable.
 */
export function prepareSvg(svg: string, mode: BackgroundMode): string {
  if (mode === 'white') return svg;

  if (mode === 'transparent') {
    // Only the plot-bg rect loses its fill; everything else stays.
    return mapRoleTags(svg, (tag) =>
      /data-role="plot-bg"/.test(tag) ? tag.replace(/fill="[^"]*"/, 'fill="none"') : tag,
    );
  }

  // dark: recolour every inline chrome hex on data-role elements.
  return mapRoleTags(svg, (tag) => {
    let out = tag;
    for (const [from, to] of Object.entries(DARK_MAP)) {
      // Replace the hex only inside a fill=/stroke= attribute value, case-
      // insensitively, so a stray hex in some other attribute is left alone.
      out = out.replace(
        new RegExp(`((?:fill|stroke)=")${from}(")`, 'gi'),
        (_m, pre, post) => `${pre}${to}${post}`,
      );
    }
    return out;
  });
}

/** #rrggbb → [r,g,b] (0–255). */
function hexRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Load a URL into an <Image>, resolving on its load event. */
function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('SVG image failed to load'));
    img.src = url;
  });
}

/** canvas.toBlob wrapped as a promise (rejects if the browser returns null). */
function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('toBlob returned null'))), 'image/png');
  });
}

/**
 * Put an `@font-face` for the figure family (the TTF as a base64 data URL)
 * in a `<style>` right after the root tag, so an `<img>`-loaded SVG, which
 * cannot reach the page's fonts, draws with the embedded face.
 */
export function withEmbeddedFont(svg: string, fontBase64: string): string {
  const style =
    `<style>@font-face{font-family:'${FIGURE_FONT_FAMILY}';` +
    `src:url(data:font/ttf;base64,${fontBase64}) format('truetype')}</style>`;
  return svg.replace(/<svg\b[^>]*>/, (root) => root + style);
}

/**
 * Rasterise a print figure to PNG bytes at `dpi` (default 600; 600 dpi is
 * 23622 px/m). The canvas is `round(widthPt / 72 * dpi)` by
 * `round(heightPt / 72 * dpi)`, so the figure's printed size in points is
 * exact; the resolution is stamped in a `pHYs` chunk. 'white' and 'dark' are
 * pre-filled, 'transparent' is left clear. The font is embedded in the SVG
 * and decoded before drawing. Browser-only.
 */
export async function exportPrintPng(fig: PrintFigure, mode: BackgroundMode, dpi = 600): Promise<Uint8Array> {
  const prepared = withEmbeddedFont(prepareSvg(fig.svg, mode), await loadFigureFontBase64());
  const url = URL.createObjectURL(new Blob([prepared], { type: 'image/svg+xml' }));
  try {
    const img = await loadImage(url);
    await img.decode();
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round((fig.widthPt / 72) * dpi));
    canvas.height = Math.max(1, Math.round((fig.heightPt / 72) * dpi));
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2d canvas context unavailable');
    if (mode !== 'transparent') {
      ctx.fillStyle = mode === 'dark' ? DARK_BG : '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await canvasToBlob(canvas);
    return withPngDpi(new Uint8Array(await blob.arrayBuffer()), dpi);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Vectorise a print figure to PDF bytes. The page is the figure's size in
 * points (`widthPt` by `heightPt`). The figure font is registered with jsPDF
 * under `FIGURE_FONT_FAMILY`; svg2pdf.js parses each `font-family` list and
 * takes the first name jsPDF's `getFontList()` knows, so the stack's first
 * entry maps to the registered font and the PDF embeds it (no `<style>`
 * needed). 'white' and 'dark' get a full-page background rect first.
 * Browser-only.
 */
export async function exportPrintPdf(fig: PrintFigure, mode: BackgroundMode): Promise<Uint8Array> {
  const w = fig.widthPt;
  const h = fig.heightPt;
  const prepared = prepareSvg(fig.svg, mode);
  const fontBase64 = await loadFigureFontBase64();
  const { jsPDF } = await import('jspdf');
  await import('svg2pdf.js'); // augments jsPDF.prototype.svg
  const doc = new jsPDF({ unit: 'pt', format: [w, h], orientation: w >= h ? 'landscape' : 'portrait', compress: true });
  doc.addFileToVFS('PydvmaFigureSerif.ttf', fontBase64);
  doc.addFont('PydvmaFigureSerif.ttf', FIGURE_FONT_FAMILY, 'normal', 'Identity-H');
  if (mode !== 'transparent') {
    const [r, g, b] = mode === 'dark' ? hexRgb(DARK_BG) : [255, 255, 255];
    doc.setFillColor(r, g, b);
    doc.rect(0, 0, w, h, 'F');
  }
  const node = new DOMParser().parseFromString(prepared, 'image/svg+xml')
    .documentElement as unknown as SVGSVGElement;
  await (doc as unknown as { svg(n: Element, o: object): Promise<unknown> }).svg(node, { x: 0, y: 0, width: w, height: h });
  return new Uint8Array(doc.output('arraybuffer'));
}

/** The bytes of a print figure in `format`: 600 dpi PNG or point-sized PDF. */
export async function figureBytes(fig: PrintFigure, format: FigureFormat, mode: BackgroundMode): Promise<Uint8Array> {
  if (format === 'png') return exportPrintPng(fig, mode);
  if (format === 'pdf') return exportPrintPdf(fig, mode);
  throw new Error(`unknown figure format: ${String(format)}`);
}
