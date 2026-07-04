// sniff.ts — content-based file-format detection for the load pipeline.
//
// The load flow never trusts a file extension alone: a legacy pydvma
// dataset renamed `.npy` is still a zip if it was re-saved as a .dvma,
// and a `.mat` can only be told apart by extension (MATLAB v5/v7 have no
// single stable magic worth sniffing here). Content wins over extension
// for the two formats that DO carry a magic (zip, numpy), so the
// pipeline routes them correctly regardless of what the user named them.

/** The four routes the load pipeline understands. */
export type FileFormat = 'dvma' | 'npy' | 'mat' | 'unknown';

/**
 * Detect a file's format from its leading bytes, falling back to the
 * extension only for `.mat`.
 *
 * - `PK` (0x50 0x4b) — a zip local-file header → a `.dvma` container.
 * - `\x93N` (0x93 0x4e) — the start of the numpy `\x93NUMPY` magic → a
 *   legacy pickle `.npy` (pydvma <=1.4.0 saved a pickled DataSet array).
 * - otherwise a name ending in `.mat` → a MATLAB import (JW logger).
 * - anything else → `unknown` (the caller shows an error toast).
 *
 * Content beats extension: a `.dvma` renamed `.npy` still sniffs `dvma`,
 * because the zip magic is checked before the extension fallback.
 */
export function sniffFormat(bytes: Uint8Array, name: string): FileFormat {
  if (bytes[0] === 0x50 && bytes[1] === 0x4b) return 'dvma'; // PK (zip)
  if (bytes[0] === 0x93 && bytes[1] === 0x4e) return 'npy'; // \x93NUMPY
  if (name.toLowerCase().endsWith('.mat')) return 'mat';
  return 'unknown';
}
