// data.ts — browser DATA export: Export CSV and Export Matlab.
//
// ONE WRITER PER FORMAT. The app exports the very document Save builds — the
// computed FFT/TF materialised as items, the sonogram question asked, the UI
// state stamped, the "Choose sets…" subset applied — serialised as `.dvma`
// bytes, and the engine's `dvma_to_csv` / `dvma_to_mat` ops turn those into
// the file python's `export_to_csv` / `export_to_matlab` write (formats
// `pydvma-csv 1` / `pydvma-mat 1`). Both hold exactly what the `.dvma` holds,
// and Load Data reads them back. (Until the lossless-export round the CSV was
// a TypeScript twin of python's writer, which carried one kind per file on
// the first set's axis and could not be read back.)
//
// The document is built in App (it owns the sonogram dialog and the session
// journal); this module types the Export card's accessor and does the engine
// hand-off.

/**
 * What one measurement carries, as the "Choose sets…" picker badges it:
 * a time series, an FFT, a transfer function, a sonogram, a modal fit.
 */
export type ChoosableKind = 'time' | 'fft' | 'tf' | 'sono' | 'fit';

/**
 * One row of the "Choose sets…" subset picker — a source MEASUREMENT, its
 * display name, and the kinds it currently carries. Serves Save and Export
 * alike (both subset by measurement).
 */
export interface ChoosableSet {
  setId: number;
  name: string;
  kinds: ChoosableKind[];
}

/** The two data-export formats. */
export type ExportFormat = 'csv' | 'mat';

/**
 * The Export card's accessor (built in App). The optional `setIds` is the
 * "Choose sets…" pick: ABSENT means every set (what the primary buttons
 * always do), a list restricts the export to those measurements.
 */
export interface Exporter {
  /** The bytes of the exported file (boots the engine). */
  exportFile(format: ExportFormat, setIds?: readonly number[]): Promise<Uint8Array>;
  /** The measurements a subset pick can choose between, in load order. */
  choosableSets(): ChoosableSet[];
}

/** The engine's queue, as `engine.enqueue`. */
export type Enqueue = (op: string, payload: Record<string, unknown>) => Promise<unknown>;

/**
 * Hand a document's `.dvma` bytes to the engine's writer for `format` and
 * return the file's bytes. The worker may answer with a plain object, a
 * `Map`, or (marshalled) a plain array of byte values; all come back as a
 * `Uint8Array`.
 */
export async function exportBytes(
  enqueue: Enqueue, dvma: Uint8Array, format: ExportFormat,
): Promise<Uint8Array> {
  const op = format === 'csv' ? 'dvma_to_csv' : 'dvma_to_mat';
  const res = await enqueue(op, { dvma_bytes: dvma });
  const out = res instanceof Map ? res.get(format) : (res as Record<string, unknown>)[format];
  if (out instanceof Uint8Array) return out;
  return Uint8Array.from(out as ArrayLike<number>);
}
