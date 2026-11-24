/**
 * The damping panel's three charts as print figures (`printFigure.ts`), and
 * the domain helpers the panel shares with them so the screen and the file
 * draw the same frame.
 *
 * Pure (no DOM, no stores): node tests pin the mapping. Each `damping*Figure`
 * returns null when there is nothing to draw. The legends the panel shows as
 * chips (decay) or not at all (spectrum, EDC) are printed inside the axes,
 * placed at the best corner.
 */
import type { PlotLine, PlotModel } from '../plot/build';
import { markerIndices, padDomain, seriesExtent, type MiniDomain } from '../plot/miniplot';
import type { DampingBandsResult, DampingPeaksResult } from '../stores/damping';
import { LINE_PALETTE } from '../stores/selection';
import { clampFigureWidth } from './figureSave';
import type { PrintFigureInput, PrintLegendEntry } from './printFigure';

const SPECTRUM_COLOR = '#4f46e5';
const PEAK_COLOR = '#dc2626';
const FIT_KEY_COLOR = '#6b7280';

/**
 * Threshold display: 3 SIGNIFICANT figures, not fixed decimals — the
 * automatic choice can be tiny (e.g. 4e-4 on a peaky spectrum) and a
 * 3-decimal rounding would show it as a misleading "0".
 */
export function fmtThreshold(v: number): string {
  return String(Number(v.toPrecision(3)));
}

/**
 * The start slice's magnitude normalised min to max (the scale the threshold
 * lives on): the slice's frequencies, the normalised values, and the `lo`
 * and `span` that undo it. Null when the slice is empty.
 */
export function normaliseSlice(
  p: DampingPeaksResult,
): { freq: Float64Array; norm: Float64Array; lo: number; span: number } | null {
  if (p.sliceMag.length === 0) return null;
  const [lo, hi] = seriesExtent([p.sliceMag]);
  const span = hi - lo || 1;
  const norm = new Float64Array(p.sliceMag.length);
  for (let i = 0; i < norm.length; i++) norm[i] = (p.sliceMag[i] - lo) / span;
  return { freq: p.sliceFreq, norm, lo, span };
}

/** The spectrum chart's domain: x the slice's frequencies padded 2 %, y 0 to 1.06. */
export function spectrumDomain(n: { freq: Float64Array }): MiniDomain {
  return { x: padDomain(seriesExtent([n.freq]), 0.02), y: [0, 1.06] };
}

/** The decay chart's domain (x padded 3 %, y 8 % over the data and the fits); null with no fits. */
export function decayDomain(p: DampingPeaksResult): MiniDomain | null {
  if (p.fits.length === 0) return null;
  return {
    x: padDomain(seriesExtent(p.fits.map((f) => f.tFit)), 0.03),
    y: padDomain(seriesExtent(p.fits.flatMap((f) => [f.realData, f.realFit])), 0.08),
  };
}

/**
 * The EDC chart's domain: x padded 2 %, y fixed at -70 to +3 dB. The top of
 * the decay is what matters; the Schroeder tail dives to the -300 dB floor
 * and would crush every fit window into the frame top. Null with no bands.
 */
export function edcDomain(b: DampingBandsResult): MiniDomain | null {
  if (b.bandData.length === 0) return null;
  return { x: padDomain(seriesExtent(b.bandData.map((d) => d.edcT)), 0.02), y: [-70, 3] };
}

const line = (x: ArrayLike<number>, y: ArrayLike<number>, color: string, width: number, o: Partial<PlotLine> = {}): PlotLine =>
  ({ x, y, color, opacity: 1, width, dashed: false, yAxis: 'left', ...o });

function figure(model: PlotModel, entries: PrintLegendEntry[], widthMm: number): PrintFigureInput {
  return {
    panes: [{ model }], kind: 'default', widthMm: clampFigureWidth(widthMm),
    legend: { entries, placement: { kind: 'best' } },
  };
}

/**
 * The start-slice spectrum as a figure: the normalised slice (indigo), the
 * picked peaks as red circles, and the dashed threshold when there is one;
 * the legend names the start time and the threshold when known. Null for an
 * empty slice.
 */
export function dampingSpectrumFigure(p: DampingPeaksResult, widthMm: number): PrintFigureInput | null {
  const n = normaliseSlice(p);
  if (!n) return null;
  const dom = spectrumDomain(n);
  const lines: PlotLine[] = [line(n.freq, n.norm, SPECTRUM_COLOR, 1.3)];
  const entries: PrintLegendEntry[] = [{
    label: p.startTime !== null ? `Start slice, t = ${p.startTime.toFixed(2)} s` : 'Start slice',
    color: SPECTRUM_COLOR, style: 'line', faded: false,
  }];
  if (p.peaksFreq.length > 0) {
    const y = Array.from(p.peaksMag, (m) => (m - n.lo) / n.span);
    lines.push(line(p.peaksFreq, y, PEAK_COLOR, 1.4, { marker: 'o', markerOnly: true }));
    entries.push({ label: `Picked peaks (${p.peaksFreq.length})`, color: PEAK_COLOR, style: 'o', faded: false });
  }
  if (p.threshold !== null) {
    lines.push(line([dom.x[0], dom.x[1]], [p.threshold, p.threshold], PEAK_COLOR, 1.2, { dashed: true }));
    entries.push({ label: `Threshold ${fmtThreshold(p.threshold)}`, color: PEAK_COLOR, style: 'dash', faded: false });
  }
  const model: PlotModel = {
    lines, xLabel: 'Frequency (Hz)', yLabel: 'Normalised |S|', xRange: dom.x, yRange: dom.y,
  };
  return figure(model, entries, widthMm);
}

/**
 * The decay fits as a figure: per fitted mode, sparse x markers on the data
 * and the fitted line, both in the mode's palette colour; the legend reads
 * `f Hz, Qn = …` as the panel's chips do. Null with no fits.
 */
export function dampingDecayFigure(p: DampingPeaksResult, widthMm: number): PrintFigureInput | null {
  const dom = decayDomain(p);
  if (!dom) return null;
  const lines: PlotLine[] = [];
  const entries: PrintLegendEntry[] = [];
  p.fits.forEach((f, i) => {
    const color = LINE_PALETTE[i % LINE_PALETTE.length];
    const k = markerIndices(f.tFit.length);
    lines.push(line(k.map((j) => f.tFit[j]), k.map((j) => f.realData[j]), color, 1.1,
      { marker: 'x', markerOnly: true, opacity: 0.75 }));
    lines.push(line(f.tFit, f.realFit, color, 2.4));
    entries.push({ label: `${f.fPeak.toFixed(1)} Hz, Qn = ${f.Qn.toFixed(0)}`, color, style: 'xline', faded: false });
  });
  const model: PlotModel = { lines, xLabel: 'Time (s)', yLabel: 'Re log(S)', xRange: dom.x, yRange: dom.y };
  return figure(model, entries, widthMm);
}

/** A band's centre frequency as its legend label: one decimal below 10 Hz, else none. */
const bandLabel = (fc: number): string => `${fc < 10 ? fc.toFixed(1) : fc.toFixed(0)} Hz`;

/**
 * The band energy-decay curves as a figure: one curve per band in its palette
 * colour, its dashed T60 fit where it has one, and a short vertical tick at
 * the curve's cut (where its decay meets the noise) when the engine reports
 * one. The legend lists the bands, plus a grey "T60 fit (dashed)" key when
 * any band has a fit. Null with no bands.
 */
export function dampingEdcFigure(b: DampingBandsResult, widthMm: number): PrintFigureInput | null {
  const dom = edcDomain(b);
  if (!dom) return null;
  const lines: PlotLine[] = [];
  const entries: PrintLegendEntry[] = [];
  let anyFit = false;
  b.bandData.forEach((d, i) => {
    const color = LINE_PALETTE[i % LINE_PALETTE.length];
    lines.push(line(d.edcT, d.edcDb, color, 1.4, { opacity: 0.9 }));
    if (d.fitT && d.fitDb) {
      lines.push(line(d.fitT, d.fitDb, color, 2, { dashed: true }));
      anyFit = true;
    }
    if (d.cutT !== null && d.edcDb.length > 0) {
      const last = d.edcDb[d.edcDb.length - 1];
      lines.push(line([d.cutT, d.cutT], [last - 1.5, last + 1.5], color, 1.6));
    }
    entries.push({ label: bandLabel(d.fc), color, style: 'line', faded: false });
  });
  if (anyFit) entries.push({ label: 'T60 fit (dashed)', color: FIT_KEY_COLOR, style: 'dash', faded: false });
  const model: PlotModel = { lines, xLabel: 'Time (s)', yLabel: 'EDC (dB)', xRange: dom.x, yRange: dom.y };
  return figure(model, entries, widthMm);
}
