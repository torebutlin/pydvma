import { describe, expect, it } from 'vitest';
import {
  dampingDecayFigure, dampingEdcFigure, dampingSpectrumFigure, decayDomain, fmtThreshold,
} from '../../src/lib/export/dampingFigure';
import { LINE_PALETTE } from '../../src/lib/stores/selection';
import type { DampingBandsResult, DampingPeaksResult } from '../../src/lib/stores/damping';

const F = (a: number[]) => Float64Array.from(a);
const fit = (fPeak: number, Qn: number) => ({
  fPeak, Qn, tFit: F([0, 0.1, 0.2]), realFit: F([0, -1, -2]), realData: F([0.1, -1.1, -1.9]),
});
const peaks = {
  fn: F([249.04, 459]), Qn: F([273.6, 1394.9]),
  fits: [fit(249.04, 273.6), fit(459.0, 1394.9)],
  startTime: 0.1024, threshold: 0.005566,
  sliceFreq: F([0, 100, 200, 300]), sliceMag: F([1, 5, 2, 3]),
  peaksFreq: F([100, 300]), peaksMag: F([5, 3]),
} as unknown as DampingPeaksResult;
const band = (fc: number, fitted: boolean, cutT: number | null) => ({
  fc, fLo: fc / 1.4, fHi: fc * 1.4, edcT: F([0, 0.5, 1]), edcDb: F([0, -20, -40]),
  fitT: fitted ? F([0.1, 0.6]) : null, fitDb: fitted ? F([-3, -30]) : null, cutT,
});
const bands = { bandData: [band(1.953125, true, 0.8), band(125, false, null)] } as unknown as DampingBandsResult;

describe('dampingFigure', () => {
  it('fmtThreshold keeps three significant figures', () => {
    expect(fmtThreshold(0.005566)).toBe('0.00557');
    expect(fmtThreshold(0.4)).toBe('0.4');
  });

  it('spectrum: normalised slice, peaks as circles, dashed threshold, the panel domain', () => {
    const i = dampingSpectrumFigure(peaks, 160)!;
    const m = i.panes[0].model;
    expect([m.xLabel, m.yLabel]).toEqual(['Frequency (Hz)', 'Normalised |S|']);
    expect(m.xRange).toEqual([-6, 306]); expect(m.yRange).toEqual([0, 1.06]);
    expect(Array.from(m.lines[0].y)).toEqual([0, 1, 0.25, 0.5]);
    expect(m.lines[0]).toMatchObject({ color: '#4f46e5', width: 1.3, dashed: false });
    expect(m.lines[1]).toMatchObject({ color: '#dc2626', marker: 'o', markerOnly: true });
    expect(Array.from(m.lines[1].y)).toEqual([1, 0.5]);
    expect(m.lines[2]).toMatchObject({ color: '#dc2626', dashed: true, width: 1.2 });
    expect(Array.from(m.lines[2].x)).toEqual([-6, 306]); expect(Array.from(m.lines[2].y)).toEqual([0.005566, 0.005566]);
    expect(i.legend).toEqual({ placement: { kind: 'best' }, entries: [
      { label: 'Start slice, t = 0.10 s', color: '#4f46e5', style: 'line', faded: false },
      { label: 'Picked peaks (2)', color: '#dc2626', style: 'o', faded: false },
      { label: 'Threshold 0.00557', color: '#dc2626', style: 'dash', faded: false },
    ] });
    expect(i.kind).toBe('default'); expect(i.widthMm).toBe(160);
  });

  it('spectrum without a threshold or start time leaves them out', () => {
    const i = dampingSpectrumFigure({ ...peaks, threshold: null, startTime: null }, 160)!;
    expect(i.panes[0].model.lines).toHaveLength(2);
    expect(i.legend!.entries.map((e) => e.label)).toEqual(['Start slice', 'Picked peaks (2)']);
  });

  it('decay: x markers and a fit line per mode, palette colours, the panel domain', () => {
    const i = dampingDecayFigure(peaks, 160)!;
    const m = i.panes[0].model;
    expect([m.xLabel, m.yLabel]).toEqual(['Time (s)', 'Re log(S)']);
    expect(m.lines).toHaveLength(4);
    expect(m.lines[0]).toMatchObject({ color: LINE_PALETTE[0], marker: 'x', markerOnly: true, width: 1.1, opacity: 0.75 });
    expect(m.lines[1]).toMatchObject({ color: LINE_PALETTE[0], width: 2.4, dashed: false });
    expect([m.xRange, m.yRange]).toEqual([decayDomain(peaks)!.x, decayDomain(peaks)!.y]);
    expect(i.legend!.entries[0]).toEqual({ label: '249.0 Hz, Qn = 274', color: LINE_PALETTE[0], style: 'xline', faded: false });
  });

  it('EDC: a curve per band, a dashed fit only where there is one, a cut tick where cut, then the fit key', () => {
    const i = dampingEdcFigure(bands, 160)!;
    const m = i.panes[0].model;
    expect([m.xLabel, m.yLabel, m.yRange]).toEqual(['Time (s)', 'EDC (dB)', [-70, 3]]);
    expect(m.lines.map((l) => l.dashed)).toEqual([false, true, false, false]);
    expect(m.lines[0]).toMatchObject({ width: 1.4, opacity: 0.9 }); expect(m.lines[1]).toMatchObject({ width: 2 });
    expect(Array.from(m.lines[2].x)).toEqual([0.8, 0.8]);
    expect(Array.from(m.lines[2].y)).toEqual([-41.5, -38.5]);
    expect(m.lines[2]).toMatchObject({ width: 1.6, opacity: 1, color: m.lines[0].color });
    expect(i.legend!.entries.map((e) => [e.label, e.style])).toEqual([['2.0 Hz', 'line'], ['125 Hz', 'line'], ['T60 fit (dashed)', 'dash']]);
    expect(i.legend!.entries[2].color).toBe('#6b7280');
  });

  it('nothing to draw, no figure', () => {
    expect(dampingSpectrumFigure({ ...peaks, sliceFreq: F([]), sliceMag: F([]) }, 160)).toBeNull();
    expect(dampingDecayFigure({ ...peaks, fits: [] }, 160)).toBeNull();
    expect(dampingEdcFigure({ ...bands, bandData: [] }, 160)).toBeNull();
  });
});
