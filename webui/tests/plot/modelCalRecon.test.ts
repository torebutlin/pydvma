import { expect, test } from 'vitest';
import { buildPlotModel, decodeArray, type MarshalledArray, type SetArrays, type VisibleLine }
  from '../../src/lib/plot/model';

const real = (shape: number[], data: number[]): MarshalledArray =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]): MarshalledArray =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });
const vis = (setId: number, ch: number, state: 'on' | 'fade', color = '#2563eb'): VisibleLine =>
  ({ setId, ch, state, color });

// ---- Calibration seam --------------------------------------------------- //

test('cal seam: all-ones (absent) is identity for time', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [10, 20, 11, 21])) },
  }];
  const m = buildPlotModel({ view: 'time', sets, visible: [vis(0, 1, 'on')] });
  expect(Array.from(m.lines[0].y)).toEqual([20, 21]);       // unchanged
});

test('cal seam: a per-channel factor scales that time channel', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    time: { axis: Float64Array.from([0, 1]), data: decodeArray(real([2, 2], [10, 20, 11, 21])) },
    calFactors: [2, 3],
  }];
  // ch0 scaled by 2, ch1 by 3
  const m0 = buildPlotModel({ view: 'time', sets, visible: [vis(0, 0, 'on')] });
  const m1 = buildPlotModel({ view: 'time', sets, visible: [vis(0, 1, 'on')] });
  expect(Array.from(m0.lines[0].y)).toEqual([20, 22]);      // [10,11]×2
  expect(Array.from(m1.lines[0].y)).toEqual([60, 63]);      // [20,21]×3
});

test('cal seam: FFT linear magnitude scales by cal; PSD by cal²', () => {
  const sets: SetArrays[] = [{
    setId: 0,
    freq: { axis: Float64Array.from([0, 1]), data: decodeArray(cplx([2, 1], [3, 4, 3, 4])) }, // |H|=5
    psd: { axis: Float64Array.from([0, 1]), data: decodeArray(real([1, 2], [4, 9])) },        // (Nc,Nf)
    calFactors: [10],
  }];
  const fft = buildPlotModel({ view: 'frequency', freqMode: 'fft', yScale: 'lin', sets, visible: [vis(0, 0, 'on')] });
  expect(Array.from(fft.lines[0].y)).toEqual([50, 50]);     // 5×10
  const psd = buildPlotModel({ view: 'frequency', freqMode: 'psd', yScale: 'lin', sets, visible: [vis(0, 0, 'on')] });
  expect(Array.from(psd.lines[0].y)).toEqual([400, 900]);   // [4,9]×10²
});

test('cal seam: TF column scales by the ratio cal[out]/cal[in]', () => {
  // 2-channel set, chIn=0, one output column (ch1). tf_data |H| = 2.
  const sets: SetArrays[] = [{
    setId: 0,
    tf: { axis: Float64Array.from([0, 1]), data: decodeArray(cplx([2, 1], [2, 0, 2, 0])), chIn: 0, nChannels: 2 },
    calFactors: [4, 10],   // ratio out(1)/in(0) = 10/4 = 2.5
  }];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(Array.from(m.lines[0].y)).toEqual([5, 5]);         // 2 × 2.5
});

// ---- Reconstruction overlay --------------------------------------------- //

/** A minimal TF set: 2 channels, chIn=0, one output column at |H|=2. */
const tfSet = (): SetArrays => ({
  setId: 0,
  tf: { axis: Float64Array.from([0, 1, 2]), data: decodeArray(cplx([3, 1], [2, 0, 2, 0, 2, 0])), chIn: 0, nChannels: 2 },
});

test('recon overlay: local adds a pink solid line per visible TF line', () => {
  const recon = {
    setId: 0, chIn: 0, nChannels: 2, showGlobal: false,
    local: { axis: Float64Array.from([0, 1, 2]), data: decodeArray(cplx([3, 1], [1, 0, 1, 0, 1, 0])) },
  };
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets: [tfSet()], visible: [vis(0, 1, 'on')], recon });
  // 1 measured + 1 recon line
  expect(m.lines).toHaveLength(2);
  const pink = m.lines.find((l) => l.color === '#be185d');
  expect(pink).toBeTruthy();
  expect(pink!.dashed).toBe(false);
});

test('recon overlay: global draws grey dashed ONLY when showGlobal is on', () => {
  const base = {
    setId: 0, chIn: 0, nChannels: 2,
    local: { axis: Float64Array.from([0, 1, 2]), data: decodeArray(cplx([3, 1], [1, 0, 1, 0, 1, 0])) },
    global: { axis: Float64Array.from([0, 1, 2]), data: decodeArray(cplx([3, 1], [0.5, 0, 0.5, 0, 0.5, 0])) },
  };
  const off = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets: [tfSet()], visible: [vis(0, 1, 'on')], recon: { ...base, showGlobal: false } });
  expect(off.lines.some((l) => l.color === '#66708a')).toBe(false);
  const on = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets: [tfSet()], visible: [vis(0, 1, 'on')], recon: { ...base, showGlobal: true } });
  const grey = on.lines.find((l) => l.color === '#66708a');
  expect(grey).toBeTruthy();
  expect(grey!.dashed).toBe(true);
});

test('recon overlay: no overlay when recon is null or targets another set', () => {
  const none = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets: [tfSet()], visible: [vis(0, 1, 'on')], recon: null });
  expect(none.lines).toHaveLength(1);
  const other = buildPlotModel({
    view: 'tf', tfPlotType: 'mag', sets: [tfSet()], visible: [vis(0, 1, 'on')],
    recon: { setId: 99, chIn: 0, nChannels: 2, showGlobal: false, local: { axis: Float64Array.from([0]), data: decodeArray(cplx([1, 1], [1, 0])) } },
  });
  expect(other.lines).toHaveLength(1);                       // recon set 99 ≠ visible set 0
});

test('recon overlay: the INPUT channel draws no overlay (out/in remap)', () => {
  // ch0 IS the input — it has no measured TF line and no recon overlay.
  const recon = {
    setId: 0, chIn: 0, nChannels: 2, showGlobal: false,
    local: { axis: Float64Array.from([0, 1, 2]), data: decodeArray(cplx([3, 1], [1, 0, 1, 0, 1, 0])) },
  };
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets: [tfSet()], visible: [vis(0, 0, 'on')], recon });
  expect(m.lines).toHaveLength(0);                           // input channel: nothing drawn
});
