import { expect, test } from 'vitest';
import { buildPlotModel, decodeArray, type MarshalledArray, type SetArrays, type VisibleLine }
  from '../../src/lib/plot/model';

/** A marshalled real array with the given shape and flat row-major data. */
const real = (shape: number[], data: number[]): MarshalledArray =>
  ({ shape, data: Float64Array.from(data), complex: false });
/** A marshalled complex array; `data` is interleaved [re,im,re,im,…]. */
const cplx = (shape: number[], interleaved: number[]): MarshalledArray =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

const vis = (setId: number, ch: number, state: 'on' | 'fade', color = '#2563eb'): VisibleLine =>
  ({ setId, ch, state, color });

test('decodeArray de-interleaves complex into re/im', () => {
  const d = decodeArray(cplx([2], [1, 2, 3, 4]));
  expect(Array.from(d.re)).toEqual([1, 3]);
  expect(Array.from(d.im!)).toEqual([2, 4]);
  expect(d.shape).toEqual([2]);
});

test('decodeArray passes real arrays through as re, no im', () => {
  const d = decodeArray(real([3], [5, 6, 7]));
  expect(Array.from(d.re)).toEqual([5, 6, 7]);
  expect(d.im).toBeUndefined();
});

test('time view: one line per visible (set,ch) from the channel column', () => {
  // 2 samples, 2 channels, row-major (Ns, Nc): [[10,20],[11,21]]
  const sets: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [10, 20, 11, 21])) },
  }];
  const m = buildPlotModel({ view: 'time', sets, visible: [vis(0, 1, 'on')] });
  expect(m.lines).toHaveLength(1);
  expect(Array.from(m.lines[0].y)).toEqual([20, 21]);   // channel 1 column
  expect(m.lines[0].xMonotonic).toBe(true);
});

test('frequency FFT: y = 20·log10|H| for a known complex array', () => {
  // freq_data (Nf=1, Nc=1): value 3+4i → |H|=5 → 20·log10(5)
  const sets: SetArrays[] = [{
    setId: 0,
    freq: { axis: Float64Array.from([100]), data: decodeArray(cplx([1, 1], [3, 4])) },
  }];
  const m = buildPlotModel({ view: 'frequency', freqMode: 'fft', sets, visible: [vis(0, 0, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(20 * Math.log10(5), 9);
  expect(m.yLabel).toBe('Magnitude (dB)');
});

test('frequency PSD: y = 10·log10(psd) with (Nc, Nf) layout', () => {
  // psd (Nc=2, Nf=2) row-major: ch0=[10,100], ch1=[1,1000]
  const sets: SetArrays[] = [{
    setId: 0,
    psd: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [10, 100, 1, 1000])) },
  }];
  const m = buildPlotModel({ view: 'frequency', freqMode: 'psd', sets, visible: [vis(0, 1, 'on')] });
  expect(Array.from(m.lines[0].y)).toEqual([10 * Math.log10(1), 10 * Math.log10(1000)]);
  expect(m.yLabel).toBe('PSD (dB)');
});

test('tf mag: 20·log10|H| in dB', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [0, 1])) },  // |H|=1 → 0 dB
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets, visible: [vis(0, 0, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(0, 9);
});

test('tf phase: atan2(im,re) in degrees', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [0, 1])) },  // atan2(1,0)=90°
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'phase', sets, visible: [vis(0, 0, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(90, 9);
});

test('tf nyquist: squareAspect, x=re/y=im, no dB', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([10, 20, 30]), data: decodeArray(cplx([3, 1], [1, 2, 3, 4, 5, 6])) },
  }];
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'nyquist', sets, visible: [vis(0, 0, 'on')], freqRange: null,
  });
  expect(m.squareAspect).toBe(true);
  expect(Array.from(m.lines[0].x)).toEqual([1, 3, 5]);   // re
  expect(Array.from(m.lines[0].y)).toEqual([2, 4, 6]);   // im
  expect(m.lines[0].xMonotonic).toBe(false);
});

test('tf nyquist: windows to the shared freq range', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([10, 20, 30]), data: decodeArray(cplx([3, 1], [1, 2, 3, 4, 5, 6])) },
  }];
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'nyquist', sets, visible: [vis(0, 0, 'on')], freqRange: [15, 25],
  });
  expect(Array.from(m.lines[0].x)).toEqual([3]);   // only f=20 in [15,25]
  expect(Array.from(m.lines[0].y)).toEqual([4]);
});

test('tf coherence: dashed right-axis lines, y2Range [0,1], same colour', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: {
      axis: Float64Array.from([10, 20]),
      data: decodeArray(cplx([2, 1], [1, 0, 1, 0])),
      coherence: decodeArray(real([2, 1], [0.9, 0.8])),
    },
  }];
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'mag', coherence: true, sets, visible: [vis(0, 0, 'on', '#dc2626')],
  });
  expect(m.y2Range).toEqual([0, 1]);
  expect(m.y2Label).toBe('coherence γ²');
  const coh = m.lines.find(l => l.yAxis === 'right')!;
  expect(coh.dashed).toBe(true);
  expect(coh.color).toBe('#dc2626');
  expect(Array.from(coh.y)).toEqual([0.9, 0.8]);
});

test('tf coherence NOT shown for nyquist/real/imag', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: {
      axis: Float64Array.from([10]),
      data: decodeArray(cplx([1, 1], [1, 0])),
      coherence: decodeArray(real([1, 1], [0.9])),
    },
  }];
  for (const pt of ['real', 'imag', 'nyquist'] as const) {
    const m = buildPlotModel({ view: 'tf', tfPlotType: pt, coherence: true, sets, visible: [vis(0, 0, 'on')] });
    expect(m.lines.some(l => l.yAxis === 'right')).toBe(false);
    expect(m.y2Range).toBeUndefined();
  }
});

test('faded line renders at opacity 0.35; on at 1.0', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [1, 2, 3, 4])) },
  }];
  const m = buildPlotModel({ view: 'time', sets, visible: [vis(0, 0, 'on'), vis(0, 1, 'fade')] });
  expect(m.lines[0].opacity).toBe(1.0);
  expect(m.lines[1].opacity).toBe(0.35);
});

test('empty dataset → empty model, no throw', () => {
  for (const view of ['time', 'frequency', 'tf', 'sono'] as const) {
    const m = buildPlotModel({ view, sets: [], visible: [] });
    expect(m.lines).toHaveLength(0);
  }
});

test('channel index beyond a set is skipped, not thrown', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 1], [1, 2])) },  // 1 channel
  }];
  const m = buildPlotModel({ view: 'time', sets, visible: [vis(0, 5, 'on')] });
  expect(m.lines).toHaveLength(0);
});

test('bode plot type degrades to the magnitude pane (card stacks two)', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [10, 0])) },  // |H|=10 → 20 dB
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'bode', sets, visible: [vis(0, 0, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(20, 9);
  expect(m.yLabel).toBe('|H| (dB)');
});
