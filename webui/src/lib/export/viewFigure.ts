/**
 * What Save Figure prints for the view on screen: turns the app's view state
 * (which view, Bode or Nyquist, the models the plots render, the sonogram's
 * heat image, the legend's placement and rows, the printed width) into the
 * print renderer's `PrintFigureInput` (`printFigure.ts`).
 *
 * Pure (no DOM, no stores), so node tests pin the mapping. App snapshots the
 * arguments when Save Figure is pressed and lays the figure out before any
 * dialog opens, so a plot change while the dialog is open cannot change the
 * file.
 */
import type { PlotModel } from '../plot/build';
import type { LegendEntry } from '../stores/selection';
import type { ViewId } from '../stores/viewstate';
import { clampFigureWidth } from './figureSave';
import type { FigureKind, PrintFigureInput, PrintLegendEntry, PrintPane } from './printFigure';

/**
 * The legend rows to print, in order, from the rows the on-screen legend
 * lists. An `'off'` row is dropped: on screen it is listed only so it can be
 * clicked back on, and the plot does not draw it. A modal-fit pseudo-set's
 * row (its id in `fitSetIds`) gets a dashed swatch, since its reconstruction
 * draws dashed; every other row a solid line. A `'fade'` row prints faded.
 */
export function toPrintEntries(entries: readonly LegendEntry[], fitSetIds: ReadonlySet<number>): PrintLegendEntry[] {
  return entries
    .filter((e) => e.state !== 'off')
    .map((e) => ({
      label: e.label,
      color: e.color,
      style: fitSetIds.has(e.setId) ? 'dash' : 'line',
      faded: e.state === 'fade',
    }));
}

/**
 * The view state `viewFigureInput` prints, as App holds it when Save Figure
 * is pressed: the active `view`; whether the TF view shows Bode or Nyquist;
 * the main plot's `model`, the Bode phase pane's `phaseModel` and the
 * sonogram's axes `sonoAxisModel`; the sonogram's heat image as a PNG data
 * URL (null when there is none); the legend's visibility and on-screen
 * fractions across its plot; the rows the on-screen legend lists (`entries`,
 * off rows included); the modal-fit pseudo-set ids (`fitSetIds`); and the
 * printed width as typed (`widthMm`, clamped here).
 */
export interface ViewFigureArgs {
  view: ViewId; bode: boolean; nyquist: boolean;
  model: PlotModel; phaseModel: PlotModel; sonoAxisModel: PlotModel; sonoImage: string | null;
  legend: { visible: boolean; x: number; y: number };
  entries: readonly LegendEntry[]; fitSetIds: ReadonlySet<number>; widthMm: unknown;
}

/**
 * The print renderer's input for the view on screen.
 *
 * - The sonogram prints its axes model as one `'default'` pane, with the heat
 *   image drawn over the data rect when there is one, and no legend (the
 *   sonogram shows none on screen).
 * - Bode prints two panes, magnitude (`model`) over phase (`phaseModel`), as
 *   kind `'bode'`; Nyquist one square pane, kind `'nyquist'`; every other view
 *   its one `model` as kind `'default'`.
 * - The legend is printed when it is visible on screen and has a row left
 *   after `toPrintEntries`, placed at the on-screen fractions
 *   (`{ kind: 'position', x, y }`); otherwise it is null.
 * - The width is `clampFigureWidth(widthMm)`: 40–300 mm, 160 mm for anything
 *   non-numeric.
 */
export function viewFigureInput(a: ViewFigureArgs): PrintFigureInput {
  const widthMm = clampFigureWidth(a.widthMm);
  if (a.view === 'sono') {
    const pane: PrintPane = a.sonoImage ? { model: a.sonoAxisModel, image: a.sonoImage } : { model: a.sonoAxisModel };
    return { panes: [pane], kind: 'default', widthMm, legend: null };
  }
  const kind: FigureKind = a.bode ? 'bode' : a.nyquist ? 'nyquist' : 'default';
  const panes: PrintPane[] = a.bode ? [{ model: a.model }, { model: a.phaseModel }] : [{ model: a.model }];
  const entries = a.legend.visible ? toPrintEntries(a.entries, a.fitSetIds) : [];
  const legend = entries.length > 0
    ? { entries, placement: { kind: 'position' as const, x: a.legend.x, y: a.legend.y } }
    : null;
  return { panes, kind, widthMm, legend };
}
