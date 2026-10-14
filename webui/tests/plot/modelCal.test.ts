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
  const psd = buildPlotModel({ view: 'frequency', freqMode: 'power', yScale: 'lin', sets, visible: [vis(0, 0, 'on')] });
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

// NOTE (round-7 item 6): the dedicated `recon` overlay option — and its tests
// — are gone. Modal-fit reconstructions now reach `buildPlotModel` as ordinary
// pseudo-set tf slices (dashed lines via `visible[].dashed`); that path is
// covered by tests/analysis/modalPseudoSet.test.ts.

// ---- TF calibration (a factor on the ratio itself) ---------------------- //

/** 2-channel measured TF, chIn = 0, one output column (ch1), |H| = 2. */
const tfSet = (extra: Partial<SetArrays>): SetArrays => ({
  setId: 0,
  tf: { axis: Float64Array.from([0, 1]), data: decodeArray(cplx([2, 1], [2, 0, 2, 0])), chIn: 0, nChannels: 2 },
  ...extra,
});

test('TF calibration replaces the channel ratio for that line', () => {
  const sets = [tfSet({
    calFactors: [4, 10],                       // channel ratio would be 2.5
    tfCal: { chIn: 0, lines: [null, { factor: 7, num: 'm/s', den: 'N' }] },
  })];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(Array.from(m.lines[0].y)).toEqual([14, 14]);       // 2 × 7, not 2 × 2.5
});

test('TF calibration set against another input channel does not apply', () => {
  const sets = [tfSet({
    calFactors: [4, 10],
    tfCal: { chIn: 1, lines: [{ factor: 7, num: 'm/s', den: 'N' }, null] },
  })];
  const m = buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] });
  expect(Array.from(m.lines[0].y)).toEqual([5, 5]);         // back on the channel ratio
});

test('TF calibration covers only its own lines; the rest keep the channel ratio', () => {
  // 3 channels, chIn = 0 → columns are ch1, ch2.
  const sets: SetArrays[] = [{
    setId: 0,
    tf: {
      axis: Float64Array.from([0]), data: decodeArray(cplx([1, 2], [1, 0, 1, 0])),
      chIn: 0, nChannels: 3,
    },
    calFactors: [2, 6, 8],                     // ratios 3 and 4
    tfCal: { chIn: 0, lines: [null, { factor: 10, num: '', den: '' }, null] },
  }];
  const at = (ch: number) =>
    buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets, visible: [vis(0, ch, 'on')] }).lines[0].y[0];
  expect(at(1)).toBe(10);
  expect(at(2)).toBe(4);
});

test('TF calibration units label the axis, and x(iω) moves the numerator', () => {
  // An uncalibrated NI capture: channels are plain volts, so the channel
  // ratio would read V/V. The TF calibration states what the ratio really is.
  const base = { units: ['V', 'V'], unitsAreVolts: true,
    tfCal: { chIn: 0, lines: [null, { factor: 7, num: 'm/s', den: 'N' }] } };
  const label = (extra: Partial<SetArrays>) => buildPlotModel({
    view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets: [tfSet({ ...base, ...extra })], visible: [vis(0, 1, 'on')],
  }).yLabel;
  expect(label({})).toBe('|H| ((m/s)/N)');
  expect(label({ iwPower: 1 })).toBe('|H| ((m/s²)/N)');
});

test('TF calibration with no unit stated keeps the plain |H|', () => {
  const sets = [tfSet({
    units: ['N', 'm/s²'],                      // the channels DO say something
    tfCal: { chIn: 0, lines: [null, { factor: 7, num: '', den: '' }] },
  })];
  // ...but the calibrated line's unit is unstated, and a channel-derived
  // (m/s²)/N would be a claim about numbers the channels no longer produce.
  expect(buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets, visible: [vis(0, 1, 'on')] }).yLabel)
    .toBe('|H|');
});

test('TF calibration units obey the volts-placeholder rule like channel units', () => {
  const mk = (unitsAreVolts: boolean) => buildPlotModel({
    view: 'tf', tfPlotType: 'mag', yScale: 'lin', visible: [vis(0, 1, 'on')],
    sets: [tfSet({ unitsAreVolts, tfCal: { chIn: 0, lines: [null, { factor: 3, num: 'V', den: 'V' }] } })],
  }).yLabel;
  expect(mk(false)).toBe('|H|');               // Web Audio: 'V' is a placeholder
  expect(mk(true)).toBe('|H| (V/V)');
});

test('an orphan TF labels its axis from its own stored ratio unit', () => {
  // A TF-only file: no input channel, so the unit cannot be built from two
  // channels — but the TfData carries it whole, as python stores it.
  const orphan = (units: string[], iwPower = 0): SetArrays => ({
    setId: 0, units, iwPower,
    tf: { axis: Float64Array.from([1]), data: decodeArray(cplx([1, 1], [1, 0])), chIn: null, nChannels: 1 },
  });
  const label = (s: SetArrays) =>
    buildPlotModel({ view: 'tf', tfPlotType: 'mag', yScale: 'lin', sets: [s], visible: [vis(0, 0, 'on')] }).yLabel;
  expect(label(orphan(['(m/s)/N']))).toBe('|H| ((m/s)/N)');
  expect(label(orphan(['(m/s)/N'], 1))).toBe('|H| ((m/s²)/N)');
  // The placeholder default is not a ratio, and a volts ratio on a set not
  // known to be volts is not a claim worth making.
  expect(label(orphan(['V']))).toBe('|H|');
  expect(label(orphan(['V/V']))).toBe('|H|');
});
