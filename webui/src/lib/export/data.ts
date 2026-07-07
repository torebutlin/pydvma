// data.ts — browser DATA export (Task A3): CSV in pure TypeScript,
// reproducing pydvma `file.py::export_to_csv` byte-for-byte (within double
// precision), plus the thin glue that turns the engine-side `.mat` bytes and
// the raw per-set arrays into named downloadable files.
//
// WHY PURE TS. The CSV is a straight text serialisation of raw arrays — no
// numpy needed — so it runs without booting the pyodide engine (raw arrays
// come straight from the JS store via `actions.exportArrays`). Matlab, by
// contrast, is built engine-side (`scipy.io.savemat` in a glue op) and handed
// back as ready bytes via `actions.exportMat`; this module only NAMES and
// routes those bytes, it does not build the `.mat` dict.
//
// EXACT-FORMAT CONTRACT (pinned in tests/export/data.test.ts):
//   - `np.savetxt(f, arr, delimiter=",")` default float format is `%.18e`
//     (18 fractional digits, exponent `e±DD` with >=2 digits, sign only when
//     negative). Every row is terminated by '\n' INCLUDING the last.
//   - For freq/tf the axis column is a REAL float, but pydvma appends complex
//     data onto it with `np.append(..., axis=1)`, which promotes the WHOLE
//     array to complex128 — so the axis is rendered complex-with-zero-
//     imaginary too. numpy's complex cell is ` (RE±IMj)`: a LEADING SPACE,
//     the pair wrapped in parens, RE as `%.18e` and IM as `%+.18e` (forced
//     sign), suffixed `j`.
//   - RAW values only (no calibration factors), matching pydvma.

/** A real data column (time export). */
export type RealColumn = Float64Array;
/** A complex data column as split real/imag arrays (freq / tf export). */
export type ComplexColumn = { re: Float64Array; im: Float64Array };

/**
 * One source set's raw arrays for export, as returned by
 * `actions.exportArrays(kind)`. `axis` is always real; `columns` are real
 * for `kind==='time'` and complex `{re, im}` pairs for `'freq'`/`'tf'`.
 */
export interface ExportSet {
  setId: number;
  axis: Float64Array;
  columns: RealColumn[] | ComplexColumn[];
}

/** The three pydvma data-list kinds CSV / Matlab export understands. */
export type ExportKind = 'time' | 'freq' | 'tf';

/**
 * The minimal engine-side accessor surface the Export card depends on
 * (implemented on `actions` by the analysis layer). Typed locally so this
 * module — and the card — stay decoupled from the full `Actions` type.
 */
export interface Exporter {
  /** Raw per-set arrays for a kind (empty when that kind has no data). */
  exportArrays(kind: ExportKind): ExportSet[];
  /** Ready `.mat` bytes (engine-side `scipy.io.savemat`; boots pyodide). */
  exportMat(): Promise<Uint8Array>;
}

/**
 * Format a real number as C `printf("%.18e", x)` / numpy's default savetxt
 * float format: 18 fractional digits, exponent `e±DD` (>=2 digits, always
 * signed), and a leading sign only when negative (−0 keeps its sign, as
 * numpy does).
 *
 * NOTE (documented, functionally irrelevant): V8's `toExponential(18)` rounds
 * half-away-from-zero while glibc/numpy round half-to-even, so a small
 * fraction of large-magnitude values differ in the LAST fractional digit —
 * digits that are already beyond IEEE-754 double precision. Both spellings
 * parse back to the identical double, so downstream parsers behave the same.
 */
export function fmtReal(x: number): string {
  const neg = x < 0 || Object.is(x, -0);
  const s = Math.abs(x)
    .toExponential(18)
    .replace(/e([+-])(\d+)$/, (_m, sign, digits) => `e${sign}${digits.padStart(2, '0')}`);
  return (neg ? '-' : '') + s;
}

/**
 * Format the imaginary part as C `printf("%+.18e", x)`: like {@link fmtReal}
 * but the sign is ALWAYS shown (numpy prints a forced `+`/`-` before the
 * imaginary part of a complex value).
 */
export function fmtImag(x: number): string {
  const neg = x < 0 || Object.is(x, -0);
  const s = Math.abs(x)
    .toExponential(18)
    .replace(/e([+-])(\d+)$/, (_m, sign, digits) => `e${sign}${digits.padStart(2, '0')}`);
  return (neg ? '-' : '+') + s;
}

/**
 * numpy's savetxt complex cell: ` (RE±IMj)` — a LEADING SPACE, the pair
 * wrapped in parens, `RE` via {@link fmtReal} and `IM` via {@link fmtImag}.
 */
export function fmtComplex(re: number, im: number): string {
  return ` (${fmtReal(re)}${fmtImag(im)}j)`;
}

/**
 * Build a CSV string reproducing pydvma `export_to_csv` exactly: the first
 * column is set[0]'s axis, then EVERY set's data columns are appended in load
 * order (comma-delimited, no header, RAW values). For `'time'` every cell is
 * real (`%.18e`); for `'freq'`/`'tf'` the whole array is complex (numpy dtype
 * promotion), so the axis renders complex-with-zero-imaginary too.
 *
 * Mirrors numpy's `np.append(..., axis=1)`, which requires an identical row
 * count across sets — a mismatch throws a clear error rather than emitting a
 * ragged file. Returns '' for no sets. Every line (including the last) ends
 * with '\n', matching savetxt's default newline.
 */
export function buildCsv(kind: ExportKind, sets: ExportSet[]): string {
  if (sets.length === 0) return '';
  const rows = sets[0].axis.length;
  for (const s of sets) {
    if (s.axis.length !== rows) {
      throw new Error('CSV export: all sets must share the same number of samples.');
    }
  }
  const complex = kind !== 'time';
  const lines: string[] = [];
  for (let i = 0; i < rows; i++) {
    const cells: string[] = [
      complex ? fmtComplex(sets[0].axis[i], 0) : fmtReal(sets[0].axis[i]),
    ];
    for (const s of sets) {
      if (complex) {
        for (const col of s.columns as ComplexColumn[]) cells.push(fmtComplex(col.re[i], col.im[i]));
      } else {
        for (const col of s.columns as RealColumn[]) cells.push(fmtReal(col[i]));
      }
    }
    lines.push(cells.join(','));
  }
  return lines.join('\n') + '\n';
}

/** Kind → filename suffix, in pydvma data-list order (time, freq, tf). */
const CSV_KINDS: { kind: ExportKind; suffix: string }[] = [
  { kind: 'time', suffix: 'time' },
  { kind: 'freq', suffix: 'freq' },
  { kind: 'tf', suffix: 'tf' },
];

/** A named file ready to write to disk or download. */
export interface NamedFile {
  name: string;
  text: string;
}

/**
 * Build one CSV file per kind that currently has data, mirroring the Export
 * stage's "save the whole dataset" theme (Save Dataset and Matlab export
 * everything too). A single kind yields `<base>-time.csv`; multiple yield
 * `<base>-time.csv`, `<base>-freq.csv`, `<base>-tf.csv`. Returns [] when
 * nothing is present.
 */
export function buildCsvFiles(exporter: Exporter, base: string): NamedFile[] {
  const files: NamedFile[] = [];
  for (const { kind, suffix } of CSV_KINDS) {
    const sets = exporter.exportArrays(kind);
    if (sets.length === 0) continue;
    files.push({ name: `${base}-${suffix}.csv`, text: buildCsv(kind, sets) });
  }
  return files;
}
