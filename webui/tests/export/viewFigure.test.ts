import { describe, expect, it } from 'vitest';
import { toPrintEntries, viewFigureInput, type ViewFigureArgs } from '../../src/lib/export/viewFigure';
import type { PlotModel } from '../../src/lib/plot/build';
import type { TriState } from '../../src/lib/stores/selection';

/** Three distinct stub models: the main pane, the Bode phase pane, the sonogram axes. */
const M: PlotModel = { lines: [], xLabel: 'Frequency (Hz)', yLabel: '|H| (dB)', xRange: null, yRange: null };
const P: PlotModel = { lines: [], xLabel: 'Frequency (Hz)', yLabel: 'Phase (deg)', xRange: null, yRange: null };
const S: PlotModel = { lines: [], xLabel: 'Time (s)', yLabel: 'Frequency (Hz)', xRange: null, yRange: null };

/** A TF view, legend visible at 0.98/0.98, one 'on' entry, 160 mm; `over` replaces fields. */
function args(over: Partial<ViewFigureArgs>): ViewFigureArgs {
  return {
    view: 'tf', bode: false, nyquist: false,
    model: M, phaseModel: P, sonoAxisModel: S, sonoImage: null,
    legend: { visible: true, x: 0.98, y: 0.98 },
    entries: [{ setId: 1, ch: 1, label: 's1', color: '#2563eb', state: 'on' }],
    fitSetIds: new Set<number>(), widthMm: 160,
    ...over,
  };
}

describe('viewFigureInput', () => {
  it('kind and panes follow the view', () => {
    expect(viewFigureInput(args({ bode: true })).kind).toBe('bode');
    expect(viewFigureInput(args({ bode: true })).panes.map((p) => p.model)).toEqual([M, P]);
    expect(viewFigureInput(args({ nyquist: true })).kind).toBe('nyquist');
    expect(viewFigureInput(args({})).panes).toEqual([{ model: M }]);
  });

  it('the sonogram exports its heat image and no legend', () => {
    const i = viewFigureInput(args({ view: 'sono', sonoImage: 'data:image/png;base64,AA' }));
    expect(i.panes).toEqual([{ model: S, image: 'data:image/png;base64,AA' }]);
    expect(i.legend).toBeNull();
  });

  it('a hidden legend is left out; otherwise it carries the on-screen fractions', () => {
    expect(viewFigureInput(args({ legend: { visible: false, x: 0.98, y: 0.98 } })).legend).toBeNull();
    expect(viewFigureInput(args({})).legend!.placement).toEqual({ kind: 'position', x: 0.98, y: 0.98 });
  });

  it('the width is clamped', () => {
    expect(viewFigureInput(args({ widthMm: 9999 })).widthMm).toBe(300);
  });
});

describe('toPrintEntries', () => {
  it('toPrintEntries drops off rows, dashes fit lines and fades faded ones', () => {
    const e = (setId: number, state: TriState) => ({ setId, ch: 1, label: `s${setId}`, color: '#2563eb', state });
    expect(toPrintEntries([e(1, 'on'), e(2, 'off'), e(3, 'fade'), e(9, 'on')], new Set([9]))).toEqual([
      { label: 's1', color: '#2563eb', style: 'line', faded: false },
      { label: 's3', color: '#2563eb', style: 'line', faded: true },
      { label: 's9', color: '#2563eb', style: 'dash', faded: false },
    ]);
  });
});
