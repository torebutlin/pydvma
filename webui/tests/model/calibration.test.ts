import { expect, test } from 'vitest';
import {
  sensitivityToFactor,
  factorToSensitivity,
  normalizeFactors,
  normalizeUnits,
  isIdentity,
  CAL_UNITS,
  DEFAULT_UNIT,
  capturedInVolts,
  splitTfUnit,
  composeTfUnit,
  normalizeTfCal,
  tfCalToUi,
  tfCalLine,
} from '../../src/lib/model/calibration';

// ── The sensitivity ↔ factor convention (pydvma acquisition.py:236) ──────── //

test('sensitivityToFactor = 1/sensitivity (100 mV/g accel → factor 10)', () => {
  expect(sensitivityToFactor(0.1)).toBe(10);   // 0.1 V/g → ×10 → reads in g
  expect(sensitivityToFactor(1)).toBe(1);       // uncalibrated
  expect(sensitivityToFactor(0.0023)).toBeCloseTo(434.78, 2);  // 2.3 mV/N force probe
});

test('sensitivityToFactor treats 0 / non-finite as uncalibrated (factor 1)', () => {
  expect(sensitivityToFactor(0)).toBe(1);       // never ±Infinity
  expect(sensitivityToFactor(NaN)).toBe(1);
  expect(sensitivityToFactor(Infinity)).toBe(1);
});

test('factorToSensitivity is the exact inverse (lossless dialog round-trip)', () => {
  expect(factorToSensitivity(10)).toBe(0.1);
  expect(factorToSensitivity(1)).toBe(1);
  expect(factorToSensitivity(sensitivityToFactor(0.1))).toBeCloseTo(0.1, 12);
  expect(factorToSensitivity(0)).toBe(1);       // degenerate factor → sensitivity 1
});

// ── normalizeFactors: the length == channel-count invariant ──────────────── //

test('normalizeFactors pads short input with identity 1s', () => {
  expect(normalizeFactors([2], 3)).toEqual([2, 1, 1]);
});

test('normalizeFactors truncates long input', () => {
  expect(normalizeFactors([1, 2, 3, 4], 2)).toEqual([1, 2]);
});

test('normalizeFactors replaces 0 / NaN / Infinity slots with 1', () => {
  expect(normalizeFactors([0, NaN, Infinity, 5], 4)).toEqual([1, 1, 1, 5]);
});

test('normalizeFactors on undefined/null yields all-ones', () => {
  expect(normalizeFactors(undefined, 3)).toEqual([1, 1, 1]);
  expect(normalizeFactors(null, 2)).toEqual([1, 1]);
});

test('normalizeFactors accepts a typed array', () => {
  expect(normalizeFactors(Float64Array.from([2, 4]), 2)).toEqual([2, 4]);
});

// ── normalizeUnits ───────────────────────────────────────────────────────── //

test('normalizeUnits pads/truncates and defaults missing slots to V', () => {
  expect(normalizeUnits(['g'], 3)).toEqual(['g', DEFAULT_UNIT, DEFAULT_UNIT]);
  expect(normalizeUnits(['N', 'm/s', 'Pa'], 2)).toEqual(['N', 'm/s']);
  expect(normalizeUnits(undefined, 2)).toEqual(['V', 'V']);
});

test('normalizeUnits preserves a non-standard unit verbatim (no data loss)', () => {
  // 'g' is NOT one of the preset options but must survive round-trips.
  expect((CAL_UNITS as readonly string[]).includes('g')).toBe(false);
  expect(normalizeUnits(['g', 'N'], 2)).toEqual(['g', 'N']);
});

test('CAL_UNITS offers the displacement/velocity ladder as well as accel', () => {
  // A velocity-output pickup (3C6's charge amp) reads in m/s; x(iω) then
  // walks it along m -> m/s -> m/s², so all three rungs are presets.
  expect([...CAL_UNITS]).toEqual(['V', 'm', 'm/s', 'm/s²', 'N', 'Pa']);
});

// ── isIdentity ───────────────────────────────────────────────────────────── //

test('isIdentity is true only when every factor is exactly 1', () => {
  expect(isIdentity([1, 1, 1])).toBe(true);
  expect(isIdentity([1, 2])).toBe(false);
  expect(isIdentity([])).toBe(true);            // vacuously
});


// ---------------------------------------------------------------------------
// capturedInVolts (Q2): 'V' is doing two jobs, and only the settings tell them
// apart. A Web Audio capture wears 'V' over normalised 0-1 samples; an NI one
// wears it over volts. Judged by exactly the rule the bridge uses for its live
// full-scale reference (`serve._input_scale_fields`).
// ---------------------------------------------------------------------------

test('capturedInVolts: an NI capture is always volts', () => {
  expect(capturedInVolts({ device_driver: 'nidaq' })).toBe(true);
  // Even with VmaxSC untouched — the soundcard field does not apply.
  expect(capturedInVolts({ device_driver: 'nidaq', VmaxSC: 1 })).toBe(true);
});

test('capturedInVolts: a soundcard is volts only once VmaxSC is characterised', () => {
  expect(capturedInVolts({ device_driver: 'soundcard' })).toBe(false);
  expect(capturedInVolts({ device_driver: 'soundcard', VmaxSC: 1 })).toBe(false);
  expect(capturedInVolts({ device_driver: 'soundcard', VmaxSC: 1.9036 })).toBe(true);
});

test('capturedInVolts: Web Audio and anything unreadable are not volts', () => {
  expect(capturedInVolts({ device_driver: 'web_audio' })).toBe(false);
  expect(capturedInVolts(undefined)).toBe(false);
  expect(capturedInVolts(null)).toBe(false);
  expect(capturedInVolts('nidaq')).toBe(false);
  // A nonsense VmaxSC is not a calibration.
  expect(capturedInVolts({ VmaxSC: 0 })).toBe(false);
  expect(capturedInVolts({ VmaxSC: -2 })).toBe(false);
  expect(capturedInVolts({ VmaxSC: Number.NaN })).toBe(false);
});


// ---------------------------------------------------------------------------
// Transfer-function calibration: a factor on the RATIO, for when the TF can be
// calibrated (a free mass: |a/F| = 1/m) but the two transducers cannot.
// ---------------------------------------------------------------------------

test('composeTfUnit wraps compound units like python analysis.wrap_unit', () => {
  expect(composeTfUnit('m/s²', 'N')).toBe('(m/s²)/N');
  expect(composeTfUnit('V', 'V')).toBe('V/V');
  expect(composeTfUnit('m/s', 'N')).toBe('(m/s)/N');
});

test('splitTfUnit reads back the top-level ratio', () => {
  expect(splitTfUnit('(m/s²)/N')).toEqual({ num: 'm/s²', den: 'N' });
  expect(splitTfUnit('V/V')).toEqual({ num: 'V', den: 'V' });
  expect(splitTfUnit('(m/s)/(N)')).toEqual({ num: 'm/s', den: 'N' });
  // Pre-2.5 python wrote no brackets. The denominator of a TF is almost
  // always one unit (a force, a volt), so the LAST slash is the ratio.
  expect(splitTfUnit('m/s/N')).toEqual({ num: 'm/s', den: 'N' });
  expect(splitTfUnit(' (m/s)/N ')).toEqual({ num: 'm/s', den: 'N' });
});

test('splitTfUnit refuses what is not a ratio', () => {
  expect(splitTfUnit('N')).toBeNull();
  expect(splitTfUnit('(m/s)')).toBeNull();
  expect(splitTfUnit('')).toBeNull();
  expect(splitTfUnit('/N')).toBeNull();
  expect(splitTfUnit('m/')).toBeNull();
  expect(splitTfUnit(undefined)).toBeNull();
});

test('splitTfUnit inverts composeTfUnit', () => {
  for (const [n, d] of [['m/s²', 'N'], ['m/s', 'N'], ['V', 'V'], ['Pa', 'm/s']]) {
    expect(splitTfUnit(composeTfUnit(n, d))).toEqual({ num: n, den: d });
  }
});

test('normalizeTfCal keeps valid lines, indexed by source channel', () => {
  const c = normalizeTfCal(
    { ch_in: 0, lines: [null, { factor: 2.5, num: 'm/s', den: 'N' }] }, 2,
  );
  expect(c).toEqual({ chIn: 0, lines: [null, { factor: 2.5, num: 'm/s', den: 'N' }] });
});

test('normalizeTfCal pads/truncates to the channel count', () => {
  expect(normalizeTfCal({ ch_in: 0, lines: [null, { factor: 2, num: 'a', den: 'b' }] }, 3))
    .toEqual({ chIn: 0, lines: [null, { factor: 2, num: 'a', den: 'b' }, null] });
  expect(normalizeTfCal(
    { ch_in: 0, lines: [null, { factor: 2, num: 'a', den: 'b' }, { factor: 3, num: '', den: '' }] }, 2,
  )).toEqual({ chIn: 0, lines: [null, { factor: 2, num: 'a', den: 'b' }] });
});

test('normalizeTfCal drops unusable lines and returns null when none are left', () => {
  // A zero or non-finite factor is not a calibration; nor is a missing one.
  expect(normalizeTfCal({ ch_in: 0, lines: [null, { factor: 0, num: 'a', den: 'b' }] }, 2)).toBeNull();
  expect(normalizeTfCal({ ch_in: 0, lines: [null, { factor: NaN }] }, 2)).toBeNull();
  expect(normalizeTfCal({ ch_in: 0, lines: [null, { num: 'a' }] }, 2)).toBeNull();
  // Units default to '' (no label) rather than failing the line.
  expect(normalizeTfCal({ ch_in: 0, lines: [null, { factor: 4 }] }, 2))
    .toEqual({ chIn: 0, lines: [null, { factor: 4, num: '', den: '' }] });
});

test('normalizeTfCal refuses an input channel the set does not have', () => {
  const line = { factor: 2, num: 'a', den: 'b' };
  expect(normalizeTfCal({ ch_in: 5, lines: [null, line] }, 2)).toBeNull();
  expect(normalizeTfCal({ ch_in: -1, lines: [null, line] }, 2)).toBeNull();
  expect(normalizeTfCal({ ch_in: 0.5, lines: [null, line] }, 2)).toBeNull();
  // A line ON the input channel is meaningless (it has no TF) and is dropped.
  expect(normalizeTfCal({ ch_in: 1, lines: [null, line] }, 2)).toBeNull();
  expect(normalizeTfCal(undefined, 2)).toBeNull();
  expect(normalizeTfCal('junk', 2)).toBeNull();
});

test('normalizeTfCal accepts the in-memory (camelCase) form too', () => {
  const c = { chIn: 0, lines: [null, { factor: 2, num: 'a', den: 'b' }] };
  expect(normalizeTfCal(c, 2)).toEqual(c);
});

test('tfCalToUi round-trips through normalizeTfCal', () => {
  const c = { chIn: 1, lines: [{ factor: 0.25, num: 'm/s', den: 'N' }, null, null] };
  const ui = tfCalToUi(c);
  expect(ui).toEqual({ ch_in: 1, lines: [{ factor: 0.25, num: 'm/s', den: 'N' }, null, null] });
  expect(normalizeTfCal(JSON.parse(JSON.stringify(ui)), 3)).toEqual(c);
});

test('tfCalLine applies only to the input channel it was set against', () => {
  const c = { chIn: 0, lines: [null, { factor: 2, num: 'a', den: 'b' }] };
  expect(tfCalLine(c, 1, 0)).toEqual({ factor: 2, num: 'a', den: 'b' });
  expect(tfCalLine(c, 0, 0)).toBeNull();
  // The same numbers against a different input are a different ratio.
  expect(tfCalLine(c, 1, 1)).toBeNull();
  expect(tfCalLine(c, 1, null)).toBeNull();
  expect(tfCalLine(undefined, 1, 0)).toBeNull();
  expect(tfCalLine(null, 1, 0)).toBeNull();
});
