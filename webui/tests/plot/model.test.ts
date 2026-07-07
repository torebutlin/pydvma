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

// A 2-channel TF slice: input ch0 dropped, ONE output column (ch_1).
// The visible OUTPUT channel is ch 1; the model remaps it to column 0.
test('tf mag: 20·log10|H| in dB', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [0, 1])), chIn: 0, nChannels: 2 },  // |H|=1 → 0 dB
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets, visible: [vis(0, 1, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(0, 9);
});

test('tf phase: atan2(im,re) in degrees', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [0, 1])), chIn: 0, nChannels: 2 },  // atan2(1,0)=90°
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'phase', sets, visible: [vis(0, 1, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(90, 9);
});

test('tf nyquist: squareAspect, x=re/y=im, no dB', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([10, 20, 30]), data: decodeArray(cplx([3, 1], [1, 2, 3, 4, 5, 6])), chIn: 0, nChannels: 2 },
  }];
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'nyquist', sets, visible: [vis(0, 1, 'on')], freqRange: null,
  });
  expect(m.squareAspect).toBe(true);
  expect(Array.from(m.lines[0].x)).toEqual([1, 3, 5]);   // re
  expect(Array.from(m.lines[0].y)).toEqual([2, 4, 6]);   // im
  expect(m.lines[0].xMonotonic).toBe(false);
});

// ── Axis units in labels (round-4 item 6) ──────────────────────────────────

test('unit labels: time y-axis shows the shared engineering unit', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [1, 2, 3, 4])) },
    units: ['m/s²', 'm/s²'],
  }];
  const m = buildPlotModel({ view: 'time', sets, visible: [vis(0, 0, 'on'), vis(0, 1, 'on')] });
  expect(m.yLabel).toBe('Amplitude (m/s²)');
});

test('unit labels: mixed units across visible channels fall back to plain Amplitude', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [1, 2, 3, 4])) },
    units: ['m/s²', 'N'],
  }];
  const m = buildPlotModel({ view: 'time', sets, visible: [vis(0, 0, 'on'), vis(0, 1, 'on')] });
  expect(m.yLabel).toBe('Amplitude');
});

test("unit labels: absent or default 'V' units keep the plain fallback", () => {
  const absent: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 1], [1, 2])) },
  }];
  expect(buildPlotModel({ view: 'time', sets: absent, visible: [vis(0, 0, 'on')] }).yLabel)
    .toBe('Amplitude');

  const volts: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 1], [1, 2])) },
    units: ['V'],
  }];
  expect(buildPlotModel({ view: 'time', sets: volts, visible: [vis(0, 0, 'on')] }).yLabel)
    .toBe('Amplitude');
});

test('unit labels: frequency magnitude carries the unit before (dB) / in linear', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    freq: { axis: Float64Array.from([100]), data: decodeArray(cplx([1, 1], [3, 4])) },
    units: ['Pa'],
  }];
  expect(buildPlotModel({ view: 'frequency', freqMode: 'fft', sets, visible: [vis(0, 0, 'on')] }).yLabel)
    .toBe('Magnitude (Pa, dB)');
  expect(buildPlotModel({ view: 'frequency', freqMode: 'fft', yScale: 'lin', sets, visible: [vis(0, 0, 'on')] }).yLabel)
    .toBe('Magnitude (Pa)');
});

test('unit labels: PSD is power, so the unit reads as unit²/Hz', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    psd: { axis: Float64Array.from([0, 1]), data: decodeArray(real([1, 2], [10, 100])) },
    units: ['m/s²'],
  }];
  expect(buildPlotModel({ view: 'frequency', freqMode: 'psd', sets, visible: [vis(0, 0, 'on')] }).yLabel)
    .toBe('PSD ((m/s²)²/Hz, dB)');
  expect(buildPlotModel({ view: 'frequency', freqMode: 'psd', yScale: 'lin', sets, visible: [vis(0, 0, 'on')] }).yLabel)
    .toBe('PSD ((m/s²)²/Hz)');
});

test('unit labels: TF magnitude reads as the out/in ratio unit', () => {
  // ch0 (input) = N, ch1 (output) = m/s² → ratio (m/s²)/N.
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [0, 1])), chIn: 0, nChannels: 2 },
    units: ['N', 'm/s²'],
  }];
  expect(buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets, visible: [vis(0, 1, 'on')] }).yLabel)
    .toBe('|H| ((m/s²)/N, dB)');
  expect(buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] }).yLabel)
    .toBe('|H| ((m/s²)/N)');
  // Phase stays degrees regardless of units.
  expect(buildPlotModel({ view: 'tf', tfPlotType: 'phase', sets, visible: [vis(0, 1, 'on')] }).yLabel)
    .toBe('Phase (deg)');
});

test('unit labels: TF ratio is dropped when the input unit is unknown', () => {
  // Output has a unit but the input channel is default 'V' → not determinable.
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [0, 1])), chIn: 0, nChannels: 2 },
    units: ['V', 'm/s²'],
  }];
  expect(buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets, visible: [vis(0, 1, 'on')] }).yLabel)
    .toBe('|H| (dB)');
});

test('tf nyquist: windows to the shared freq range', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([10, 20, 30]), data: decodeArray(cplx([3, 1], [1, 2, 3, 4, 5, 6])), chIn: 0, nChannels: 2 },
  }];
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'nyquist', sets, visible: [vis(0, 1, 'on')], freqRange: [15, 25],
  });
  expect(Array.from(m.lines[0].x)).toEqual([3]);   // only f=20 in [15,25]
  expect(Array.from(m.lines[0].y)).toEqual([4]);
});

test('tf nyquist: the committed range is a freq band and must NOT reach the Real/Imag axes', () => {
  // Regression for the App-composition bug: viewstate feeds tf.range.x as BOTH
  // `freqRange` (the locus window) AND `range` (the axis domain). For Nyquist
  // the axes are Real/Imag, so the frequency band must be dropped from xRange/
  // yRange (else squareAspect collapses the locus). Here range.x === freqRange.
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([10, 20, 30]), data: decodeArray(cplx([3, 1], [1, 2, 3, 4, 5, 6])), chIn: 0, nChannels: 2 },
  }];
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'nyquist', sets, visible: [vis(0, 1, 'on')],
    freqRange: [15, 25], range: { x: [15, 25], y: null },
  });
  expect(m.xRange).toBeNull();          // freq band [15,25] must NOT become the Real axis
  expect(m.yRange).toBeNull();
  expect(m.squareAspect).toBe(true);
  expect(Array.from(m.lines[0].x)).toEqual([3]);   // locus still windowed to f=20
  expect(Array.from(m.lines[0].y)).toEqual([4]);
});

test('tf coherence: dashed right-axis lines, y2Range [0,1], same colour', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: {
      axis: Float64Array.from([10, 20]),
      data: decodeArray(cplx([2, 1], [1, 0, 1, 0])),
      coherence: decodeArray(real([2, 1], [0.9, 0.8])),
      chIn: 0, nChannels: 2,
    },
  }];
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'mag', coherence: true, sets, visible: [vis(0, 1, 'on', '#dc2626')],
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
      chIn: 0, nChannels: 2,
    },
  }];
  for (const pt of ['real', 'imag', 'nyquist'] as const) {
    const m = buildPlotModel({ view: 'tf', tfPlotType: pt, coherence: true, sets, visible: [vis(0, 1, 'on')] });
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

// ---- y-scale toggle: dB (log magnitude) ↔ linear magnitude (R3) ----

test('frequency FFT yScale="lin": y = |H| (linear), label drops the dB', () => {
  // 3+4i → |H| = 5 (linear), not 20·log10(5).
  const sets: SetArrays[] = [{
    setId: 0,
    freq: { axis: Float64Array.from([100]), data: decodeArray(cplx([1, 1], [3, 4])) },
  }];
  const m = buildPlotModel({ view: 'frequency', freqMode: 'fft', yScale: 'lin', sets, visible: [vis(0, 0, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(5, 9);
  expect(m.yLabel).toBe('Magnitude');
});

test('frequency FFT yScale="log" (default) is unchanged: dB + (dB) label', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    freq: { axis: Float64Array.from([100]), data: decodeArray(cplx([1, 1], [3, 4])) },
  }];
  const m = buildPlotModel({ view: 'frequency', freqMode: 'fft', yScale: 'log', sets, visible: [vis(0, 0, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(20 * Math.log10(5), 9);
  expect(m.yLabel).toBe('Magnitude (dB)');
});

test('frequency PSD yScale="lin": linear psd, no 10·log10, label drops dB', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    psd: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [10, 100, 1, 1000])) },
  }];
  const m = buildPlotModel({ view: 'frequency', freqMode: 'psd', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(Array.from(m.lines[0].y)).toEqual([1, 1000]);       // raw psd, ch1
  expect(m.yLabel).toBe('PSD');
});

test('tf mag yScale="lin": y = |H| (linear), label is |H|', () => {
  // 10+0i → |H| = 10 (linear), not 20 dB.
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [10, 0])), chIn: 0, nChannels: 2 },
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(10, 9);
  expect(m.yLabel).toBe('|H|');
});

test('tf bode yScale="lin": magnitude pane is linear |H| with |H| label', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [10, 0])), chIn: 0, nChannels: 2 },
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'bode', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(10, 9);
  expect(m.yLabel).toBe('|H|');
});

test('yScale="lin" is IGNORED on phase/real/imag (leave as-is)', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [0, 1])), chIn: 0, nChannels: 2 },
  }];
  // phase stays degrees regardless of yScale.
  const ph = buildPlotModel({ view: 'tf', tfPlotType: 'phase', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(ph.lines[0].y[0]).toBeCloseTo(90, 9);
  expect(ph.yLabel).toBe('Phase (deg)');
  // real stays Re(H).
  const re = buildPlotModel({ view: 'tf', tfPlotType: 'real', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(re.lines[0].y[0]).toBeCloseTo(0, 9);
  expect(re.yLabel).toBe('Re(H)');
});

test('xScale threads onto the model for frequency; time x stays linear', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    freq: { axis: Float64Array.from([1, 10, 100]), data: decodeArray(cplx([3, 1], [1, 0, 1, 0, 1, 0])) },
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 1], [1, 2])) },
  }];
  const f = buildPlotModel({ view: 'frequency', freqMode: 'fft', xScale: 'log', sets, visible: [vis(0, 0, 'on')] });
  expect(f.xScale).toBe('log');
  // Time view never goes log even if xScale='log' is passed (nonsensical).
  const t = buildPlotModel({ view: 'time', xScale: 'log', sets, visible: [vis(0, 0, 'on')] });
  expect(t.xScale).not.toBe('log');
});

test('bode plot type degrades to the magnitude pane (card stacks two)', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([50]), data: decodeArray(cplx([1, 1], [10, 0])), chIn: 0, nChannels: 2 },  // |H|=10 → 20 dB
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'bode', sets, visible: [vis(0, 1, 'on')] });
  expect(m.lines[0].y[0]).toBeCloseTo(20, 9);
  expect(m.yLabel).toBe('|H| (dB)');
});

// ---- R4: TF out/in multi-channel remap (E1 bug fix) ----
//
// `calculate_tf(time_data, ch_in)` DROPS the input channel, so tf_data is
// (Nf, N−1) OUTPUT columns in ascending channel order. A 3-channel set
// with chIn=0 has tf_data columns [ch_1, ch_2]. The model must map a
// visible source channel to its output column, draw NO line for the input
// channel, and never mislabel or drop an output (the shipped E1 bug).

/**
 * 3-channel TF slice, chIn=0 → 2 output columns.
 *   col 0 = ch_1's TF (re=1,im=0)   col 1 = ch_2's TF (re=0,im=2)
 * Nf=1 so each column is one complex sample.
 */
function tf3ch(chIn = 0): SetArrays[] {
  return [{
    setId: 0,
    tf: {
      axis: Float64Array.from([50]),
      // tf_data (Nf=1, Nout=2): [col0_re, col0_im, col1_re, col1_im]
      data: decodeArray(cplx([1, 2], [1, 0, 0, 2])),
      coherence: decodeArray(real([1, 2], [0.9, 0.7])),  // (Nf=1, Nout=2)
      chIn, nChannels: 3,
    },
  }];
}

test('R4 tf 3-channel chIn=0: input channel (ch_0) draws NO line', () => {
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'real', sets: tf3ch(0), visible: [vis(0, 0, 'on')] });
  expect(m.lines).toHaveLength(0);   // ch_0 IS the input → dropped
});

test('R4 tf 3-channel chIn=0: ch_1 → column 0, ch_2 → column 1', () => {
  // ch_1 maps to column 0 (re=1); ch_2 maps to column 1 (im=2).
  const m1 = buildPlotModel({ view: 'tf', tfPlotType: 'real', sets: tf3ch(0), visible: [vis(0, 1, 'on')] });
  expect(m1.lines).toHaveLength(1);
  expect(m1.lines[0].y[0]).toBeCloseTo(1, 9);   // Re(col0) = 1
  const m2 = buildPlotModel({ view: 'tf', tfPlotType: 'imag', sets: tf3ch(0), visible: [vis(0, 2, 'on')] });
  expect(m2.lines).toHaveLength(1);
  expect(m2.lines[0].y[0]).toBeCloseTo(2, 9);   // Im(col1) = 2
});

test('R4 tf 3-channel chIn=0: all three channels visible → 2 lines, input absent', () => {
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'real', sets: tf3ch(0),
    visible: [vis(0, 0, 'on'), vis(0, 1, 'on'), vis(0, 2, 'on')],
  });
  expect(m.lines).toHaveLength(2);              // ch_0 dropped; ch_1, ch_2 remain
  expect(m.lines[0].y[0]).toBeCloseTo(1, 9);    // ch_1 → col0
  expect(m.lines[1].y[0]).toBeCloseTo(0, 9);    // ch_2 → col1 (Re=0)
});

test('R4 tf 3-channel chIn=1: outputs [ch_0, ch_2] remap around the gap', () => {
  // chIn=1 → tf_data columns are [ch_0, ch_2]. ch_0 → col0, ch_2 → col1,
  // ch_1 (the input) → no line.
  const sets = tf3ch(1);
  const m0 = buildPlotModel({ view: 'tf', tfPlotType: 'real', sets, visible: [vis(0, 0, 'on')] });
  expect(m0.lines).toHaveLength(1);
  expect(m0.lines[0].y[0]).toBeCloseTo(1, 9);   // ch_0 → col0 (re=1)
  const m1 = buildPlotModel({ view: 'tf', tfPlotType: 'real', sets, visible: [vis(0, 1, 'on')] });
  expect(m1.lines).toHaveLength(0);             // ch_1 IS the input → no line
  const m2 = buildPlotModel({ view: 'tf', tfPlotType: 'imag', sets, visible: [vis(0, 2, 'on')] });
  expect(m2.lines).toHaveLength(1);
  expect(m2.lines[0].y[0]).toBeCloseTo(2, 9);   // ch_2 → col1 (im=2)
});

test('R4 coherence overlay uses the SAME out/in remap (input dropped)', () => {
  // coherence is (Nf, Nout) too: col0=0.9 (ch_1), col1=0.7 (ch_2).
  const sets = tf3ch(0);
  const m = buildPlotModel({
    view: 'tf', tfPlotType: 'mag', coherence: true, sets,
    visible: [vis(0, 0, 'on'), vis(0, 1, 'on'), vis(0, 2, 'on')],
  });
  const coh = m.lines.filter(l => l.yAxis === 'right');
  expect(coh).toHaveLength(2);                  // input has no coherence line
  expect(coh[0].y[0]).toBeCloseTo(0.9, 9);      // ch_1 → col0
  expect(coh[1].y[0]).toBeCloseTo(0.7, 9);      // ch_2 → col1
});
