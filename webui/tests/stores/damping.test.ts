import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { createDampingStore, type DampingPeaksResult, type DampingBandsResult } from '../../src/lib/stores/damping';
import { seriesExtent, padDomain, polylinePoints, markerIndices } from '../../src/lib/plot/miniplot';

function peaksResult(over: Partial<DampingPeaksResult> = {}): DampingPeaksResult {
  return {
    fn: new Float64Array([90]), Qn: new Float64Array([40]),
    fits: [], startTime: 0.2, threshold: 0.31,
    sliceFreq: new Float64Array([0, 10]), sliceMag: new Float64Array([1, 2]),
    peaksFreq: new Float64Array([10]), peaksMag: new Float64Array([2]),
    ...over,
  };
}

describe('damping store (round-7 interactive panel state)', () => {
  it('openFor resets knobs/results but keeps the chosen method + ladder', () => {
    const d = createDampingStore();
    d.setMode('bands');
    d.setLadder('third-octave');
    d.setThreshold(0.5);
    d.openFor('set_a', 1);
    const s = get(d);
    expect(s).toMatchObject({
      open: true, setId: 'set_a', ch: 1,
      mode: 'bands', ladder: 'third-octave',
      startTime: null, threshold: null, peaks: null, bands: null,
    });
  });

  it('auto knobs adopt the engine-resolved values on a result; explicit values win', () => {
    const d = createDampingStore();
    d.openFor('s', 0);
    d.setBusy(true);
    d.setPeaks(peaksResult());
    expect(get(d)).toMatchObject({ busy: false, startTime: 0.2, threshold: 0.31 });

    // An explicit user threshold survives the next result's echo.
    d.setThreshold(0.6);
    d.setPeaks(peaksResult({ threshold: 0.11 }));
    expect(get(d).threshold).toBe(0.6);
  });

  it('bands result adopts the resolved start and clears busy/error', () => {
    const d = createDampingStore();
    d.openFor('s', 0);
    d.setError('boom');
    const bands: DampingBandsResult = {
      bands: 'octave', startTime: 0.05,
      fc: new Float64Array([250]), fLo: new Float64Array([177]), fHi: new Float64Array([354]),
      EDT: new Float64Array([NaN]), T20: new Float64Array([0.5]),
      T30: new Float64Array([NaN]), T60: new Float64Array([0.5]),
      Qn: new Float64Array([57]),
      bandData: [],
    };
    d.setBands(bands);
    expect(get(d)).toMatchObject({ error: null, busy: false, startTime: 0.05 });
    expect(get(d).bands?.T60[0]).toBe(0.5);
  });

  it('setError clears busy so the panel never wedges on a failed fit', () => {
    const d = createDampingStore();
    d.setBusy(true);
    d.setError('engine says no');
    expect(get(d)).toMatchObject({ busy: false, error: 'engine says no' });
  });

  it('chart expansion collapses on mode flips and on close (round-7c)', () => {
    const d = createDampingStore();
    d.openFor(1, 0);
    d.setExpanded('decay');
    expect(get(d).expanded).toBe('decay');
    // A mode flip would otherwise pin a stale full-screen chart from the
    // OTHER mode's family.
    d.setMode('bands');
    expect(get(d).expanded).toBeNull();
    d.setExpanded('edc');
    d.close();
    expect(get(d).expanded).toBeNull();
  });
});

describe('miniplot helpers', () => {
  it('seriesExtent spans all series, skips non-finite, guards degenerate spans', () => {
    expect(seriesExtent([[1, 2], [0, NaN, 5]])).toEqual([0, 5]);
    expect(seriesExtent([[3, 3]])).toEqual([2.5, 3.5]);
    expect(seriesExtent([[]])).toEqual([0, 1]);
  });

  it('padDomain pads symmetrically', () => {
    expect(padDomain([0, 10], 0.1)).toEqual([-1, 11]);
  });

  it('polylinePoints maps to pixels (y down) and skips NaN samples', () => {
    const dom = { x: [0, 10] as [number, number], y: [0, 1] as [number, number] };
    const pts = polylinePoints([0, 5, NaN, 10], [0, 0.5, 0.5, 1], dom, 100, 50);
    expect(pts).toBe('0.0,50.0 50.0,25.0 100.0,0.0');
  });

  it('markerIndices caps and always includes both ends', () => {
    expect(markerIndices(3)).toEqual([0, 1, 2]);
    const idx = markerIndices(1000, 60);
    expect(idx.length).toBe(60);
    expect(idx[0]).toBe(0);
    expect(idx.at(-1)).toBe(999);
  });
});
