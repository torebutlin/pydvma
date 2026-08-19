// Compute-chain signature — the TypeScript twin of pydvma._signature.
// Every literal below is FROZEN and duplicated in tests/test_signature.py
// (the Python twin); change one and you must change both — the
// cross-language contract is pinned by these known-answer vectors plus
// the JS<->Python fixture round-trip. Also cross-checked against the
// independent reference implementation `dev/prototypes/signature_prototype.mjs`.
import { describe, expect, test } from 'vitest';
import { fnv1a64, signatureOfSamples } from '../../src/lib/codec/signature';

const ramp = (n: number) => Float64Array.from({ length: n }, (_, i) => i);

describe('fnv1a64', () => {
  test('known answer: empty input', () => {
    // tests/test_signature.py::TestFnv1a64::test_known_answer_empty
    expect(fnv1a64(new Uint8Array(0))).toBe('cbf29ce484222325');
  });

  test("known answer: 'abc' bytes", () => {
    // tests/test_signature.py::TestFnv1a64::test_known_answer_abc
    expect(fnv1a64(new TextEncoder().encode('abc'))).toBe('e71fa2190541574b');
  });

  test('known answer: [0.0, 1.0, -1.5] raw float64-LE bytes', () => {
    // tests/test_signature.py::TestFnv1a64::test_known_answer_float_vector
    const dv = new DataView(new ArrayBuffer(24));
    dv.setFloat64(0, 0.0, true);
    dv.setFloat64(8, 1.0, true);
    dv.setFloat64(16, -1.5, true);
    expect(fnv1a64(new Uint8Array(dv.buffer))).toBe('7f08103e70108a2d');
  });
});

describe('signatureOfSamples: known-answer vectors', () => {
  // Every literal here mirrors tests/test_signature.py::TestSignatureOfSamples
  // 1:1, and both are cross-checked against dev/prototypes/signature_prototype.mjs.

  test('1-D [0, 1, -1.5] @ fs=8000, nCols=1', () => {
    // tests/test_signature.py::test_known_answer_1d_vector
    expect(signatureOfSamples(Float64Array.from([0, 1, -1.5]), 1, 8000)).toBe('9f7a0c2bcb86ac6f');
  });

  test('[[0,1],[2,3],[4,5]] @ fs=4, nCols=2 (row-major order)', () => {
    // tests/test_signature.py::test_known_answer_two_column_row_order
    expect(signatureOfSamples(Float64Array.from([0, 1, 2, 3, 4, 5]), 2, 4)).toBe('3c8174748ef2be9c');
  });

  test('single-column boundary: 65536 rows (full) vs 65537 (reduced)', () => {
    // tests/test_signature.py::test_known_answer_single_column_boundary
    const full = signatureOfSamples(ramp(65536), 1, 1000);
    const reduced = signatureOfSamples(ramp(65537), 1, 1000);
    expect(full).toBe('2b034c2ef734e356');
    expect(reduced).toBe('df601b6ef7b86797');
    expect(full).not.toBe(reduced);
  });

  test('four-column boundary: 16384 rows (full) vs 16385 (reduced)', () => {
    // tests/test_signature.py::test_known_answer_four_column_boundary
    // rows_cap = 65536 // 4 = 16384 — reduction starts at 16384 TIME
    // samples on a 4-channel record, not 65536.
    const full = signatureOfSamples(ramp(65536), 4, 1000);
    const reduced = signatureOfSamples(ramp(65540), 4, 1000);
    expect(full).toBe('cb10da3bede3b603');
    expect(reduced).toBe('ede25f7b000d0f43');
    expect(full).not.toBe(reduced);
  });

  test('large reduced vector: 100000 rows x 2 cols', () => {
    // tests/test_signature.py::test_known_answer_large_reduced_vector
    expect(signatureOfSamples(ramp(200000), 2, 1000)).toBe('b7720b7fdea6364f');
  });

  test('special values: NaN, +Infinity, -Infinity, -0', () => {
    // tests/test_signature.py::test_known_answer_special_values
    //
    // DIAGNOSTIC: this vector additionally assumes the JS engine
    // canonicalises a computed NaN written via DataView.setFloat64 to
    // the bit pattern 0x7ff8000000000000. That canonicalisation is
    // implementation-defined per ECMA-262 (true on V8, JavaScriptCore
    // and SpiderMonkey, the engines vitest actually runs on) rather than
    // spec-mandated. If this test alone fails on some exotic JS engine,
    // that engine's NaN bit pattern is the reason — not a break in the
    // row-strided contract itself.
    expect(signatureOfSamples(Float64Array.from([NaN, Infinity, -Infinity, -0]), 1, 1)).toBe('b4509e0c4f9f75f0');
  });
});

describe('signatureOfSamples: reduced-branch sensitivity', () => {
  // Mirrors tests/test_signature.py::TestReducedBranchSensitivity — the
  // row-strided rule must see an edit anywhere in a SAMPLED row (every
  // channel) and must NOT see an edit confined to an unsampled gap row.
  // 50000 rows x 4 cols: rows_cap = 16384, row_stride = 4, so rows
  // 0, 4, 8, ... (plus the final row) are sampled in full.
  function record(): Float64Array {
    return ramp(50000 * 4);
  }

  test('mutating a sampled row (second channel) changes the signature', () => {
    const arr = record();
    const before = signatureOfSamples(arr, 4, 1000);
    arr[4 * 4 + 1] += 1.0; // row 4, channel 1 — row 4 is on the stride
    expect(signatureOfSamples(arr, 4, 1000)).not.toBe(before);
  });

  test('mutating a mid-gap row leaves the signature unchanged', () => {
    const arr = record();
    const before = signatureOfSamples(arr, 4, 1000);
    // row 5 falls between two sampled rows (stride 4) and is not hashed
    arr[5 * 4 + 0] += 1.0;
    arr[5 * 4 + 1] += 1.0;
    arr[5 * 4 + 2] += 1.0;
    arr[5 * 4 + 3] += 1.0;
    expect(signatureOfSamples(arr, 4, 1000)).toBe(before);
  });
});

describe('signatureOfSamples: boundary distinctness', () => {
  test('65536 rows and 65537 rows produce different signatures', () => {
    // Same claim as the single-column boundary vector above, phrased as
    // a standalone distinctness assertion (belt-and-braces per the task).
    const a = signatureOfSamples(ramp(65536), 1, 1000);
    const b = signatureOfSamples(ramp(65537), 1, 1000);
    expect(a).not.toBe(b);
  });
});
