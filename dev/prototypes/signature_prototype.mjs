// Compute-chain signature — independent JavaScript prototype.
//
// Written from the byte-stream contract in pydvma/_signature.py, NOT
// ported from the Python source, so that agreement between the two is
// evidence the contract is unambiguous. It exists to make the
// "verified against a JavaScript prototype" claim in
// tests/test_signature.py falsifiable: run it and diff the table
// against the frozen literals in that file (and, once it lands, in
// webui/tests/codec/signature.test.ts).
//
// This is a prototype, not the shipped twin — the real one is
// webui/src/lib/codec/signature.ts (derived-data save round, Task 2).
//
//   node dev/prototypes/signature_prototype.mjs
//
// Prints every frozen known-answer vector plus a timing for the
// worst realistic record (30 s x 4 ch x 51.2 kHz).

const FNV_OFFSET = 0xcbf29ce484222325n;
const FNV_PRIME = 0x100000001b3n;
const MASK = 0xFFFFFFFFFFFFFFFFn;
const MAX_HASHED_VALUES = 65536;

/** FNV-1a 64-bit over bytes, as 16 lowercase hex characters. */
export function fnv1a64(bytes) {
  let h = FNV_OFFSET;
  for (let i = 0; i < bytes.length; i++) {
    h = ((h ^ BigInt(bytes[i])) * FNV_PRIME) & MASK;
  }
  return h.toString(16).padStart(16, '0');
}

/**
 * Signature of a row-major sample block.
 *
 * @param {Float64Array|number[]} samples flat, row-major (C-order):
 *   the n_cols channel values of one time instant are adjacent.
 * @param {number} nCols channels per row (1 for a 1-D record).
 * @param {number} fs sample rate in Hz (0 when unknown).
 *
 * nCols === 0 degenerate: a flat row-major buffer cannot distinguish
 * different row counts once each row contributes zero values (the
 * buffer's length is 0 regardless of the "intended" row count), so
 * nRows is defined as 0 rather than dividing by zero. This matches
 * pydvma._signature's Python behaviour (n_rows kept in the head, zero
 * value bytes) exactly when the true row count is itself 0 — the only
 * case either twin's real callers ever produce. See the "n_cols == 0
 * DEGENERATE" paragraph in pydvma/_signature.py's module docstring.
 */
export function signatureOfSamples(samples, nCols, fs) {
  const nRows = nCols > 0 ? Math.floor(samples.length / nCols) : 0;
  const rowsCap = nCols > 0
    ? Math.max(1, Math.floor(MAX_HASHED_VALUES / nCols))
    : MAX_HASHED_VALUES;

  // pick whole rows: every row, or a stride plus the final row
  const rows = [];
  if (nRows <= rowsCap) {
    for (let r = 0; r < nRows; r++) rows.push(r);
  } else {
    const rowStride = Math.ceil(nRows / rowsCap);
    for (let r = 0; r < nRows; r += rowStride) rows.push(r);
    rows.push(nRows - 1);            // unconditional: may duplicate
  }

  const buf = new ArrayBuffer((3 + rows.length * nCols) * 8);
  const dv = new DataView(buf);
  dv.setFloat64(0, nRows, true);
  dv.setFloat64(8, nCols, true);
  dv.setFloat64(16, fs, true);
  let off = 24;
  for (const r of rows) {
    for (let c = 0; c < nCols; c++) {
      dv.setFloat64(off, samples[r * nCols + c], true);
      off += 8;
    }
  }
  return fnv1a64(new Uint8Array(buf));
}

// ---------------------------------------------------------------- vectors

function bytesOf(values) {
  const dv = new DataView(new ArrayBuffer(values.length * 8));
  values.forEach((v, i) => dv.setFloat64(i * 8, v, true));
  return new Uint8Array(dv.buffer);
}

const ramp = (n) => Float64Array.from({ length: n }, (_, i) => i);

const vectors = [
  ['fnv1a64 empty        ', fnv1a64(new Uint8Array(0))],
  ['fnv1a64 abc          ', fnv1a64(new TextEncoder().encode('abc'))],
  ['fnv1a64 [0,1,-1.5]   ', fnv1a64(bytesOf([0.0, 1.0, -1.5]))],
  ['1-D [0,1,-1.5] @8000 ', signatureOfSamples([0.0, 1.0, -1.5], 1, 8000)],
  ['2-col [[0,1]..] @4   ', signatureOfSamples([0, 1, 2, 3, 4, 5], 2, 4)],
  ['1-col 65536 rows     ', signatureOfSamples(ramp(65536), 1, 1000)],
  ['1-col 65537 rows     ', signatureOfSamples(ramp(65537), 1, 1000)],
  ['4-col 16384 rows     ', signatureOfSamples(ramp(16384 * 4), 4, 1000)],
  ['4-col 16385 rows     ', signatureOfSamples(ramp(16385 * 4), 4, 1000)],
  ['2-col 100000 rows    ', signatureOfSamples(ramp(200000), 2, 1000)],
  ['special values       ', signatureOfSamples(
    [NaN, Infinity, -Infinity, -0.0], 1, 1)],
  // n_cols == 0 degenerate — see the JSDoc above and the matching
  // paragraph in pydvma/_signature.py: head-only stream, no value
  // bytes. NOT a frozen cross-language vector (Python's n_rows for a
  // zero-column array can differ from this side's, per the documented
  // divergence) — printed here only as a sanity check on this branch.
  ['n_cols=0 degenerate  ', signatureOfSamples([], 0, 100)],
];

for (const [name, hex] of vectors) console.log(name, hex);

// ---------------------------------------------------------------- timing

const big = ramp(30 * 51200 * 4);
const t0 = process.hrtime.bigint();
signatureOfSamples(big, 4, 51200);
const ms = Number(process.hrtime.bigint() - t0) / 1e6;
console.log(`\n30 s x 4 ch x 51.2 kHz (${(big.length * 8 / 1e6).toFixed(1)} MB): `
            + `${ms.toFixed(1)} ms`);
