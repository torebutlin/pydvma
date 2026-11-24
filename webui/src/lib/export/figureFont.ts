/**
 * The font that publication figures are drawn in and measured with.
 *
 * It is a subset of STIX Two Text 2.13 (Regular instance, SIL OFL 1.1; see
 * fonts/OFL.txt), renamed "Pydvma Figure Serif". `scripts/subset-figure-font.py`
 * regenerates the TTF, the licence and `fonts/figureFontMetrics.ts` together.
 */
import { FIGURE_FONT_METRICS as M } from './fonts/figureFontMetrics';

/** Family name of the embedded subset font. */
export const FIGURE_FONT_FAMILY = 'Pydvma Figure Serif';

/** CSS font stack: the embedded font first, then close installed serifs. */
export const FIGURE_FONT_STACK =
  "'Pydvma Figure Serif', 'STIX Two Text', 'Times New Roman', Times, serif";

/** Ascent in em (positive). */
export const FONT_ASCENT: number = M.ascender / M.unitsPerEm;

/** Descent in em (positive). */
export const FONT_DESCENT: number = M.descender / M.unitsPerEm;

const MISSING_ADVANCE_EM = 0.5;

/**
 * Width of `text` in points at `sizePt`, from the font's advances (no kerning).
 * A code point the subset lacks counts 0.5 em.
 */
export function measureText(text: string, sizePt: number): number {
  let units = 0;
  for (const ch of text) {
    const adv = M.advances[String(ch.codePointAt(0))];
    units += adv ?? MISSING_ADVANCE_EM * M.unitsPerEm;
  }
  return (units * sizePt) / M.unitsPerEm;
}

/**
 * The distinct non-whitespace characters across `texts` that the font lacks,
 * in first-seen order.
 */
export function missingGlyphs(texts: Iterable<string>): string[] {
  const seen = new Set<string>();
  for (const t of texts) {
    for (const ch of t) {
      if (/\s/u.test(ch)) continue;
      if (M.advances[String(ch.codePointAt(0))] === undefined) seen.add(ch);
    }
  }
  return [...seen];
}

let fontBase64: Promise<string> | null = null;

/**
 * The TTF as base64, for embedding in an SVG or PDF. Fetched once and cached;
 * the file's URL is imported lazily so node tests and app start never load it.
 */
export function loadFigureFontBase64(): Promise<string> {
  fontBase64 ??= (async () => {
    const { default: url } = await import('./fonts/PydvmaFigureSerif.ttf?url');
    const res = await fetch(url);
    if (!res.ok) throw new Error(`figure font fetch failed: ${res.status}`);
    const bytes = new Uint8Array(await res.arrayBuffer());
    let bin = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    return btoa(bin);
  })();
  return fontBase64;
}
