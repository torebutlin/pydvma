// figureSave.ts — what Save Figure writes, shared by the top bar's Save Figure
// and the Export stage card (both run App's `saveFigure`).
//
// The choices (PNG / PDF, background) live in a store rather than in the
// Export card: the card unmounts whenever another stage is active, and the
// top bar's button must save with what the card last showed. The naming rules
// are pure functions so they carry the unit tests.
import { writable } from 'svelte/store';
import type { BackgroundMode } from './figure';

/** A figure file format. */
export type FigureFormat = 'png' | 'pdf';

/** The Export stage's figure choices: which formats to write, on what background. */
export interface FigureOptions {
  png: boolean;
  pdf: boolean;
  bg: BackgroundMode;
}

/** The figure choices for this session (not persisted): PNG on white to start. */
export const figureOptions = writable<FigureOptions>({ png: true, pdf: false, bg: 'white' });

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
