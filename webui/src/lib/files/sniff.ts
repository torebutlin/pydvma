// sniff.ts — content-based file-format detection for the load pipeline.
//
// The load flow never trusts a file extension alone: a legacy pydvma
// dataset renamed `.npy` is still a zip if it was re-saved as a .dvma,
// and a `.mat` can only be told apart by extension (MATLAB v5/v7 have no
// single stable magic worth sniffing here). Content wins over extension
// for the two formats that DO carry a magic (zip, numpy), so the
// pipeline routes them correctly regardless of what the user named them.
// The Vibration Apps' transfer-function CSV is recognised the same way, by
// the format it names on its first line.

/** The routes the load pipeline understands. */
export type FileFormat = 'dvma' | 'npy' | 'mat' | 'vacsv' | 'csv' | 'unknown';

/** The Vibration Apps' transfer-function CSV names its format on line 1. */
const VACSV_MARK = 'vibration-apps-tf-csv';

/** The file's first line (BOM dropped), read from at most 256 bytes. */
function firstLine(bytes: Uint8Array): string {
  const head = new TextDecoder('utf-8', { fatal: false }).decode(bytes.subarray(0, 256));
  return head.replace(/^\uFEFF/, '').split(/\r?\n/)[0];
}

/**
 * Detect a file's format from its leading bytes, falling back to the
 * extension only for `.mat`.
 *
 * - `PK` (0x50 0x4b) — a zip local-file header → a `.dvma` container.
 * - `\x93N` (0x93 0x4e) — the start of the numpy `\x93NUMPY` magic → a
 *   legacy pickle `.npy` (pydvma <=1.4.0 saved a pickled DataSet array).
 * - a first line `# … (vibration-apps-tf-csv N)` → the CSV the Vibration
 *   Apps' Transfer function app saves (any version N: pydvma's importer
 *   refuses one it does not read, by name).
 * - otherwise a name ending in `.mat` → a MATLAB import (JW logger).
 * - otherwise a name ending in `.csv` → `csv`, any other CSV (e.g. pydvma's
 *   own export), which the caller refuses with the reason.
 * - anything else → `unknown` (the caller shows an error toast).
 *
 * Content beats extension: a `.dvma` renamed `.npy` still sniffs `dvma`,
 * because the zip magic is checked before the extension fallback.
 */
export function sniffFormat(bytes: Uint8Array, name: string): FileFormat {
  if (bytes[0] === 0x50 && bytes[1] === 0x4b) return 'dvma'; // PK (zip)
  if (bytes[0] === 0x93 && bytes[1] === 0x4e) return 'npy'; // \x93NUMPY
  const line = firstLine(bytes);
  if (line.startsWith('#') && line.includes(VACSV_MARK)) return 'vacsv';
  const lower = name.toLowerCase();
  if (lower.endsWith('.mat')) return 'mat';
  if (lower.endsWith('.csv')) return 'csv';
  return 'unknown';
}
