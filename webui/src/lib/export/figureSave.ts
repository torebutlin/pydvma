// figureSave.ts — what Save Figure writes, shared by the top bar's Save Figure
// and the Export stage card (both run App's `saveFigure`).
//
// The choices (PNG / PDF, background) live in a store rather than in the
// Export card: the card unmounts whenever another stage is active, and the
// top bar's button must save with what the card last showed. The naming rules
// are pure functions so they carry the unit tests.
import { writable } from 'svelte/store';
import type { BackgroundMode } from './figure';
import { missingGlyphs } from './figureFont';
import type { PrintFigure } from './printFigure';

/** A figure file format. */
export type FigureFormat = 'png' | 'pdf';

/** The Export stage's figure choices: which formats to write, on what background. */
export interface FigureOptions {
  png: boolean;
  pdf: boolean;
  bg: BackgroundMode;
  /** Printed width of the figure in millimetres (labels print at 10 pt at this width). */
  widthMm: number;
}

/** Default printed figure width in millimetres. */
export const DEFAULT_FIGURE_WIDTH_MM = 160;
/** Quick-pick printed widths (mm) offered beside the width field. */
export const FIGURE_WIDTH_PRESETS = [90, 140, 160, 190] as const;
/** The printed widths (mm) a figure may take: [min, max]. */
export const FIGURE_WIDTH_RANGE = [40, 300] as const;

/** The figure choices for this session (not persisted): PNG on white, 160 mm, to start. */
export const figureOptions = writable<FigureOptions>({
  png: true, pdf: false, bg: 'white', widthMm: DEFAULT_FIGURE_WIDTH_MM,
});

/** A typed width as a number of mm within `FIGURE_WIDTH_RANGE`; anything non-numeric gives the 160 mm default. */
export function clampFigureWidth(v: unknown): number {
  if (v === '' || v === null || v === undefined) return DEFAULT_FIGURE_WIDTH_MM;
  const n = Number(v);
  if (!Number.isFinite(n)) return DEFAULT_FIGURE_WIDTH_MM;
  return Math.min(FIGURE_WIDTH_RANGE[1], Math.max(FIGURE_WIDTH_RANGE[0], n));
}

/**
 * Sentences for the toast after a save: `grown` when the layout was made
 * taller to fit its labels at 10 pt, `glyphs` when a PDF is being written and
 * its embedded font lacks some characters in the figure (null otherwise).
 */
export function figureNotes(
  fig: Pick<PrintFigure, 'grown' | 'texts'>, formats: readonly FigureFormat[],
): { grown: string | null; glyphs: string | null } {
  const grown = fig.grown ? 'laid out taller than its usual shape so the labels fit at 10 pt' : null;
  let glyphs: string | null = null;
  if (formats.includes('pdf')) {
    const missing = missingGlyphs(fig.texts.map((t) => t.text));
    if (missing.length) {
      glyphs = `The PDF can't draw ${missing.join(' ')}: those characters print as boxes there. The PNG shows them.`;
    }
  }
  return { grown, glyphs };
}

/**
 * The error toast for a figure save that threw. When some files were already
 * written (a PNG, then its PDF failed), it names them first so the message does
 * not read as though nothing was saved: `Saved a.png; PDF failed: <reason>`.
 * With nothing written: `<what> failed: <reason>`. `failing` is the format
 * being written when it threw (null before any file was started).
 */
export function figureSaveError(
  what: string, saved: readonly string[], failing: FigureFormat | null, e: unknown,
): string {
  const reason = e instanceof Error ? e.message : String(e);
  if (!saved.length) return `${what} failed: ${reason}`;
  return `Saved ${saved.join(' and ')}; ${failing ? failing.toUpperCase() : what} failed: ${reason}`;
}

/** The extensions a figure name may carry; the served Save dialog keeps either as typed. */
export const FIGURE_EXTENSIONS = ['.png', '.pdf'];

/** Default figure name: pydvma_figure_YYYY-MM-DD_HHMM (no extension). */
export function defaultFigureName(now: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  const stamp = `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}_${p(now.getHours())}${p(now.getMinutes())}`;
  return `pydvma_figure_${stamp}`;
}

/** The ticked formats, PNG first (empty when neither is ticked). */
export function figureFormats(o: FigureOptions): FigureFormat[] {
  const out: FigureFormat[] = [];
  if (o.png) out.push('png');
  if (o.pdf) out.push('pdf');
  return out;
}

/** `name` (a file name or a full path) without a trailing .png / .pdf, in any case. */
export function figureStem(name: string): string {
  return name.replace(/\.(png|pdf)$/i, '');
}

/**
 * The files one Save Figure writes for the chosen `name` (a file name or a
 * full path). With both formats ticked: `<stem>.png` and `<stem>.pdf` side by
 * side, whatever extension the name carries, so one Save dialog covers both.
 * With one: the name's own .png / .pdf decides the format (typing `beam.pdf`
 * saves a PDF even when PNG is ticked), and a name with neither gets the
 * ticked format's extension.
 */
export function figureTargets(
  name: string, formats: readonly FigureFormat[],
): { name: string; format: FigureFormat }[] {
  const stem = figureStem(name);
  if (formats.length > 1) return formats.map((format) => ({ name: `${stem}.${format}`, format }));
  const typed = /\.(png|pdf)$/i.exec(name);
  if (typed) return [{ name, format: typed[1].toLowerCase() as FigureFormat }];
  return formats.map((format) => ({ name: `${name}.${format}`, format }));
}
