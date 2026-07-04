// figure.ts — figure export: turn PlotSurface's on-screen SVG into a
// self-contained, restyled SVG string and rasterise / vectorise it to
// PNG / PDF (Task 14).
//
// THE SELF-CONTAINED-SVG PROBLEM (Step 0, decision A). PlotSurface styles
// its background rect and axis chrome via SCOPED CSS classes (.plot-bg,
// .grid, .tick, .frame, .axlab). A standalone SVG string (getSvgElement()
// .outerHTML) LOSES that <style>, so without help the exported figure would
// render with no background and invisible gridlines. Decision A: PlotSurface
// ALSO emits inline presentation attributes (fill/stroke hexes resolved from
// the design tokens) on every data-role element, so the serialised SVG is
// already self-contained. On-screen the scoped CSS still wins (CSS beats
// presentation attributes), so the visible plot is unchanged; in the export
// the inline attrs carry the styling. prepareSvg then only has to recolour
// those inline hexes for transparent / dark backgrounds.
//
// The transform is a PURE string operation (unit-tested); exportPng /
// exportPdf are browser-only (canvas / jsPDF) and are proven by the LIVE
// SMOKE in the e2e, not by node tests.
import { CHROME } from '../plot/chrome';

/** Background treatment for an exported figure. */
export type BackgroundMode = 'white' | 'transparent' | 'dark';

/**
 * The dark-mode chrome→dark colour map. KEYED OFF the shared CHROME values
 * (not repeated light hexes), so it can never drift from what PlotSurface
 * actually emits: change a CHROME colour without adding its DARK_MAP entry and
 * figure.test.ts's `keys(DARK_MAP) === values(CHROME)` assertion fails RED.
 *
 *   bg    CHROME.bg    (#ffffff) → #1b2130  (deep slate page)
 *   grid  CHROME.grid  (#eef0f4) → #2a3346  (dim grid on slate)
 *   frame CHROME.frame (#e3e6eb) → #3a4356  (axis frame, brighter than grid)
 *   axis  CHROME.axis  (#66708a) → #c7cede  (legible light-grey text)
 *
 * DATA-LINE colours (#2563eb … from the 12-colour palette) are deliberately
 * ABSENT AND the recolouring is scoped to data-role elements, so a data line
 * whose hue happens to collide with a chrome hex is still preserved.
 */
export const DARK_MAP: Readonly<Record<string, string>> = {
  [CHROME.bg]: '#1b2130', // plot-bg
  [CHROME.grid]: '#2a3346', // gridline stroke
  [CHROME.frame]: '#3a4356', // frame stroke
  [CHROME.axis]: '#c7cede', // tick + axis-label fill
};

/**
 * Dark plot-background fill, for the canvas/PDF pre-fill in the renderers.
 * Derived from DARK_MAP so it can never disagree with the SVG's recoloured
 * plot-bg (both are "what CHROME.bg maps to in dark mode").
 */
export const DARK_BG = DARK_MAP[CHROME.bg];

/**
 * Rewrite ONLY the opening tags that carry a `data-role="axis"` or
 * `data-role="plot-bg"` attribute, applying `fn` to each such tag's text.
 * Elements without a data-role (the data `<path>`s, <defs>, <g>, the capture
 * rect, the rubber band) pass through untouched — that is what keeps data
 * line colours safe. Operates on the serialised string, not the DOM, so it
 * runs under node for the unit tests.
 */
function mapRoleTags(svgText: string, fn: (tag: string) => string): string {
  // Match a single element's opening tag: `<name ...>` (non-greedy, no '>').
  return svgText.replace(/<[a-zA-Z][^>]*>/g, (tag) =>
    /data-role="(axis|plot-bg)"/.test(tag) ? fn(tag) : tag,
  );
}

/**
 * Produce a SELF-CONTAINED SVG string restyled for the chosen background.
 *
 *   'white'       — returned unchanged (the on-screen white figure).
 *   'transparent' — the plot-bg rect's fill → "none" (page/checkerboard shows
 *                   through); ALL axis chrome and the data lines are untouched.
 *   'dark'        — the plot-bg fill → #1b2130 AND every axis-chrome hex is
 *                   swapped via DARK_MAP (gridline, frame, tick/label text);
 *                   scoped to data-role elements so DATA-LINE strokes are
 *                   preserved.
 *
 * The input is expected to be PlotSurface's serialised <svg> (data-role tags
 * carrying inline fill/stroke). Idempotent for 'dark' (the mapped hexes are
 * not themselves keys), so re-running is stable.
 */
export function prepareSvg(svgText: string, mode: BackgroundMode): string {
  if (mode === 'white') return svgText;

  if (mode === 'transparent') {
    // Only the plot-bg rect loses its fill; everything else stays.
    return mapRoleTags(svgText, (tag) =>
      /data-role="plot-bg"/.test(tag) ? tag.replace(/fill="[^"]*"/, 'fill="none"') : tag,
    );
  }

  // dark: recolour every inline chrome hex on data-role elements.
  return mapRoleTags(svgText, (tag) => {
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

/**
 * Rasterise a PlotSurface SVG string to a PNG Blob at `scale`× the SVG's
 * intrinsic size (default 3 for crisp retina/print output). Restyles via
 * prepareSvg, wraps the SVG in an image/svg+xml Blob, loads it into an
 * <Image>, and draws it scaled onto a canvas. For 'white'/'dark' the canvas
 * is pre-filled with the opaque background (PNG has an alpha channel, but a
 * white/dark figure should not be transparent where the SVG has no bg);
 * 'transparent' leaves the canvas clear. Browser-only.
 */
export async function exportPng(
  svgText: string,
  mode: BackgroundMode,
  scale = 3,
): Promise<Blob> {
  const restyled = prepareSvg(svgText, mode);
  const { width, height } = svgSize(restyled);
  // PlotSurface's <svg> sizes via CSS (viewBox only, no w/h attrs). An <img>
  // loading such an SVG renders at the SVG default (300×150), distorting the
  // draw — so stamp explicit width/height before rasterising.
  const prepared = withExplicitSize(restyled, width, height);
  const url = URL.createObjectURL(new Blob([prepared], { type: 'image/svg+xml' }));
  try {
    const img = await loadImage(url);
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('2d canvas context unavailable');
    if (mode !== 'transparent') {
      ctx.fillStyle = mode === 'dark' ? DARK_BG : '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return await canvasToBlob(canvas);
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Vectorise a PlotSurface SVG string to a PDF Blob at the SVG's intrinsic
 * size in points. Restyles via prepareSvg, then dynamic-imports jspdf +
 * svg2pdf.js (kept out of the main bundle) and renders the parsed SVG node
 * into a point-sized jsPDF document. For 'white'/'dark' a full-page filled
 * rect is drawn first so the page has the intended background (a PDF page is
 * otherwise white paper); 'transparent' leaves the page as-is. Browser-only.
 */
export async function exportPdf(svgText: string, mode: BackgroundMode): Promise<Blob> {
  const prepared = prepareSvg(svgText, mode);
  const { width, height } = svgSize(prepared);
  const { jsPDF } = await import('jspdf');
  await import('svg2pdf.js'); // augments jsPDF.prototype.svg
  const doc = new jsPDF({
    orientation: width >= height ? 'landscape' : 'portrait',
    unit: 'pt',
    format: [width, height],
  });
  if (mode !== 'transparent') {
    const [r, g, b] = mode === 'dark' ? hexRgb(DARK_BG) : [255, 255, 255];
    doc.setFillColor(r, g, b);
    doc.rect(0, 0, width, height, 'F');
  }
  const node = new DOMParser().parseFromString(prepared, 'image/svg+xml')
    .documentElement as unknown as SVGSVGElement;
  // svg2pdf augments the prototype; typed loosely to avoid a global d.ts.
  await (doc as unknown as { svg(n: Element, o: object): Promise<unknown> }).svg(node, {
    x: 0,
    y: 0,
    width,
    height,
  });
  return doc.output('blob');
}

/**
 * Intrinsic pixel size of the root <svg>. Prefers explicit width/height
 * attributes; PlotSurface's <svg> sizes via CSS + a `viewBox` (no w/h
 * attrs), so fall back to the viewBox's w/h, then to 800×400. Getting this
 * right matters: it sets the PNG's base resolution (×scale) and the PDF's
 * point dimensions — a wrong size crops or letterboxes the figure.
 */
function svgSize(svgText: string): { width: number; height: number } {
  const openTag = /<svg[^>]*>/.exec(svgText)?.[0] ?? '';
  const w = /\bwidth="([\d.]+)/.exec(openTag);
  const h = /\bheight="([\d.]+)/.exec(openTag);
  if (w && h) return { width: Number(w[1]), height: Number(h[1]) };
  const vb = /viewBox="[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)"/.exec(openTag);
  if (vb) return { width: Number(vb[1]), height: Number(vb[2]) };
  return { width: 800, height: 400 };
}

/**
 * Ensure the root <svg> carries explicit `width`/`height` px attributes (so
 * an <img> gives it a real intrinsic size). If they are already present the
 * text is returned unchanged; otherwise they are inserted right after `<svg`.
 */
function withExplicitSize(svgText: string, width: number, height: number): string {
  const openTag = /<svg[^>]*>/.exec(svgText)?.[0] ?? '';
  if (/\bwidth="/.test(openTag) && /\bheight="/.test(openTag)) return svgText;
  return svgText.replace(/<svg\b/, `<svg width="${width}" height="${height}"`);
}

/** #rrggbb → [r,g,b] (0–255). */
function hexRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Load a URL into an <Image>, resolving when decoded. */
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
