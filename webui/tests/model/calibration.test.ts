import { expect, test } from 'vitest';
import {
  sensitivityToFactor,
  factorToSensitivity,
  normalizeFactors,
  normalizeUnits,
  isIdentity,
  CAL_UNITS,
  DEFAULT_UNIT,
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
  // 'm/s' is NOT one of the four preset options but must survive round-trips.
  expect((CAL_UNITS as readonly string[]).includes('m/s')).toBe(false);
  expect(normalizeUnits(['m/s', 'N'], 2)).toEqual(['m/s', 'N']);
});

// ── isIdentity ───────────────────────────────────────────────────────────── //

test('isIdentity is true only when every factor is exactly 1', () => {
  expect(isIdentity([1, 1, 1])).toBe(true);
  expect(isIdentity([1, 2])).toBe(false);
  expect(isIdentity([])).toBe(true);            // vacuously
});
