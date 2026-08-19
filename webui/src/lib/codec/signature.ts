// Compute-chain signature — the TypeScript twin of pydvma/_signature.py.
//
// A derived item (FFT, TF) records a short signature of the SOURCE
// samples it was computed from, so a loaded file can tell whether the
// chain is intact ("this TF really is the TF of that time data") or
// broken (the time data was edited/scaled/resampled after the compute).
// The algorithm — FNV-1a 64-bit over little-endian float64 bytes,
// hex-encoded — and the row-strided reduction rule below are defined
// ONCE, in `pydvma/_signature.py`'s module docstring; that file is THE
// contract. This module is a from-the-contract twin, not a port: the
// two are pinned to each other by shared known-answer vectors
// (`webui/tests/codec/signature.test.ts` and `tests/test_signature.py`)
// and the JS<->Python fixture round-trip, so a signature written by
// either side verifies on the other.

const FNV_OFFSET = 0xcbf29ce484222325n;
const FNV_PRIME = 0x100000001b3n;
const MASK = 0xffffffffffffffffn;

/** Budget of float64 VALUES hashed in full before the row-strided
 * reduction rule kicks in — divided by the channel count to give the
 * row cap. Part of the cross-language contract: pydvma._signature's
 * `MAX_HASHED_VALUES` uses the same value. */
const MAX_HASHED_VALUES = 65536;

/**
 * FNV-1a 64-bit hash of `data`, as 16 lowercase hex characters.
 *
 * Offset basis 0xcbf29ce484222325, prime 0x100000001b3, masked to 64
 * bits at every step via BigInt arithmetic — the twin of
 * `pydvma._signature.fnv1a64`.
 */
export function fnv1a64(data: Uint8Array): string {
  let h = FNV_OFFSET;
  for (let i = 0; i < data.length; i++) {
    h = ((h ^ BigInt(data[i])) * FNV_PRIME) & MASK;
  }
  return h.toString(16).padStart(16, '0');
}

/**
 * Signature of a row-major (C-order) sample block plus its sample rate.
 *
 * This is the cross-language contract: `pydvma._signature.signature_of_samples`
 * hashes the same bytes and returns the same string. The byte stream,
 * in order:
 *
 * 1. `n_rows` as one little-endian float64;
 * 2. `n_cols` as one little-endian float64;
 * 3. `fs` as one little-endian float64 (pass 0 when the rate is
 *    unknown, so a signature can always be taken);
 * 4. the selected whole ROWS, each contributing all `n_cols` values as
 *    little-endian float64 in column order — the REDUCTION RULE:
 *    `rowsCap = max(1, floor(65536 / n_cols))`; every row when
 *    `n_rows <= rowsCap`; otherwise `rowStride = ceil(n_rows / rowsCap)`
 *    (exact integer arithmetic), taking rows `0, rowStride, 2*rowStride,
 *    …` below `n_rows`, then the LAST row (index `n_rows - 1`) appended
 *    unconditionally (may duplicate the final strided row — deliberate,
 *    keeps the rule branch-free).
 *
 * `flatRowMajor` is the flat, row-major sample buffer: the `nCols`
 * channel values of one time instant are adjacent (a 1-D record has
 * `nCols = 1`). `n_rows` is derived as `floor(flatRowMajor.length / nCols)`.
 *
 * Special float values (NaN, +/-Infinity, -0) are hashed as their
 * stored bit patterns like any other sample — no normalisation.
 */
export function signatureOfSamples(flatRowMajor: Float64Array, nCols: number, fs: number): string {
  const nRows = nCols > 0 ? Math.floor(flatRowMajor.length / nCols) : 0;
  const rowsCap = nCols > 0 ? Math.max(1, Math.floor(MAX_HASHED_VALUES / nCols)) : MAX_HASHED_VALUES;

  // Select whole rows: every row, or a stride plus the final row
  // (unconditional — may duplicate the last strided row).
  const rows: number[] = [];
  if (nRows <= rowsCap) {
    for (let r = 0; r < nRows; r++) rows.push(r);
  } else {
    const rowStride = Math.ceil(nRows / rowsCap);
    for (let r = 0; r < nRows; r += rowStride) rows.push(r);
    rows.push(nRows - 1);
  }

  const buf = new ArrayBuffer((3 + rows.length * nCols) * 8);
  const dv = new DataView(buf);
  dv.setFloat64(0, nRows, true);
  dv.setFloat64(8, nCols, true);
  dv.setFloat64(16, fs, true);
  let off = 24;
  for (const r of rows) {
    for (let c = 0; c < nCols; c++) {
      dv.setFloat64(off, flatRowMajor[r * nCols + c], true);
      off += 8;
    }
  }
  return fnv1a64(new Uint8Array(buf));
}
