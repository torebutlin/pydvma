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
  /**
   * Per-column calibration factors, aligned with `columns`. Feeds the CSV
   * header only — the DATA stays raw, exactly as pydvma writes it. Absent or
   * short entries render as `1` (identity), matching
   * `pydvma.file._column_calibration`.
   */
  calFactors?: readonly number[];
  /**
   * Per-column engineering units, aligned with `columns`. Also header-only;
   * an absent entry renders as `'-'` rather than asserting a unit nobody
   * stated.
   */
  units?: readonly string[];
}

/** The three pydvma data-list kinds CSV / Matlab export understands. */
export type ExportKind = 'time' | 'freq' | 'tf';

/**
 * What one measurement carries, as the "Choose sets…" picker badges it:
 * a time series, an FFT, a transfer function, a sonogram, a modal fit.
 *
 * NOT the same list as `ExportKind` (CSV/Matlab still export time/freq/tf
 * only) — this is what a SAVE would carry, and a Save can now include the
 * sonogram if the user says yes at the include prompt.
 */
export type ChoosableKind = 'time' | 'fft' | 'tf' | 'sono' | 'fit';

/**
 * One row of the "Choose sets…" subset picker — a source MEASUREMENT, its
 * display name, and the kinds it currently carries. Serves Save and Export
 * alike (both subset by measurement), which is why it lives beside the
 * `Exporter` surface the card already reads rather than inside the popover.
 */
export interface ChoosableSet {
  setId: number;
  name: string;
  kinds: ChoosableKind[];
}

/**
 * The minimal engine-side accessor surface the Export card depends on
 * (implemented on `actions` by the analysis layer). Typed locally so this
 * module — and the card — stay decoupled from the full `Actions` type.
 *
 * The optional `setIds` on each export is the "Choose sets…" pick: ABSENT
 * means every set (what the primary buttons always do), a list restricts the
 * export to those measurements.
 */
export interface Exporter {
  /** Raw per-set arrays for a kind (empty when that kind has no data). */
  exportArrays(kind: ExportKind, setIds?: readonly number[]): ExportSet[];
  /** Ready `.mat` bytes (engine-side `scipy.io.savemat`; boots pyodide). */
  exportMat(setIds?: readonly number[]): Promise<Uint8Array>;
  /** The measurements a subset pick can choose between, in load order. */
  choosableSets(): ChoosableSet[];
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
 * Format one calibration factor for the CSV header exactly as Python's
 * `'{:.12g}'.format(x)` does — the JS twin of `pydvma.file.format_cal_factor`.
 *
 * This has to be byte-exact, not merely close: the header is part of the file
 * the browser and pydvma must both produce identically, and it is the line a
 * script parses to recover engineering units. `%.12g` semantics, which
 * `Number.toPrecision` alone does NOT give:
 *   - 12 SIGNIFICANT digits;
 *   - exponential form when the decimal exponent is < -4 or >= 12 (JS switches
 *     at < -6, so the -5/-6 band has to be forced by hand);
 *   - trailing zeros — and a trailing '.' — stripped from the mantissa;
 *   - a two-digit, always-signed exponent (`1e-05`, not JS's `1e-5`).
 *
 * A non-finite factor renders as `'1'`, the identity — never `NaN` into a
 * header. Pinned against the Python side by the shared known-answer vectors
 * (`CAL_FACTOR_FORMAT_VECTORS`) in `tests/export/data.test.ts`.
 */
export function fmtCalFactor(x: number): string {
  if (!Number.isFinite(x)) return '1';
  if (x === 0) return Object.is(x, -0) ? '-0' : '0';   // %g keeps the sign of -0
  const exp = Math.floor(Math.log10(Math.abs(x)));
  // Recompute from the rounded representation: log10 can land a hair under an
  // exact power of ten (log10(1e-5) is exact here, but 1e21-style values are
  // not), and %g decides on the exponent of the ROUNDED value.
  const rounded = Number(x.toPrecision(12));
  const e = rounded === 0 ? exp : Math.floor(Math.log10(Math.abs(rounded)));
  const strip = (m: string): string =>
    (m.indexOf('.') >= 0 ? m.replace(/0+$/, '').replace(/\.$/, '') : m);
  if (e < -4 || e >= 12) {
    const [mant, ex] = rounded.toExponential(11).split('e');
    const sign = ex.startsWith('-') ? '-' : '+';
    return `${strip(mant)}e${sign}${ex.replace(/^[+-]/, '').padStart(2, '0')}`;
  }
  // Fixed notation with (12 - 1 - e) fractional digits, then zeros stripped.
  return strip(rounded.toFixed(Math.max(0, Math.min(100, 11 - e))));
}

/**
 * numpy's savetxt complex cell: ` (RE±IMj)` — a LEADING SPACE, the pair
 * wrapped in parens, `RE` via {@link fmtReal} and `IM` via {@link fmtImag}.
 */
export function fmtComplex(re: number, im: number): string {
  return ` (${fmtReal(re)}${fmtImag(im)}j)`;
}

/**
 * The commented metadata block `export_to_csv` puts above its data rows —
 * the JS twin of `pydvma.file._csv_header`, byte-for-byte.
 *
 * WHY IT EXISTS. The data rows are RAW: pydvma stores time series in volts
 * and converts to engineering units at display time by multiplying each
 * channel by its `channel_cal_factors` entry. A CSV of just the numbers
 * therefore disagrees with what the user read off the screen, with nothing in
 * the file to explain the difference. Keeping the export raw is deliberate;
 * leaving it unlabelled was not. Each line is prefixed `'# '` exactly as
 * `np.savetxt(header=...)` does, so the numeric rows below are unchanged and
 * `np.loadtxt` / `pandas.read_csv(comment='#')` skip it by default.
 */
export function buildCsvHeader(kind: ExportKind, sets: ExportSet[]): string {
  const factors: string[] = [];
  const units: string[] = [];
  for (const s of sets) {
    for (let c = 0; c < s.columns.length; c++) {
      const f = s.calFactors?.[c];
      factors.push(fmtCalFactor(typeof f === 'number' ? f : 1));
      const u = s.units?.[c];
      units.push(typeof u === 'string' && u.length > 0 ? u : '-');
    }
  }
  const axisUnit = kind === 'time' ? 's' : 'Hz';
  return [
    '# pydvma export: RAW data, calibration NOT applied.',
    `# Column 1 is the shared axis (${axisUnit}); the rest are data columns.`,
    '# Multiply data column k by cal_factors[k] for engineering units.',
    `# cal_factors: ${factors.join(',')}`,
    `# units: ${units.join(',')}`,
  ].join('\n') + '\n';
}

/**
 * Build a CSV string reproducing pydvma `export_to_csv` exactly: a commented
 * calibration header (see {@link buildCsvHeader}), then set[0]'s axis as the
 * first column and EVERY set's data columns appended in load order
 * (comma-delimited, RAW values). For `'time'` every cell is
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
  return buildCsvHeader(kind, sets) + lines.join('\n') + '\n';
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
 *
 * `setIds` threads the "Choose sets…" pick straight through to
 * `exportArrays`: absent exports every measurement (the primary button), a
 * list exports only those — and a kind none of them carries drops out of the
 * file list entirely, as an absent kind always has.
 */
export function buildCsvFiles(
  exporter: Exporter, base: string, setIds?: readonly number[],
): NamedFile[] {
  const files: NamedFile[] = [];
  for (const { kind, suffix } of CSV_KINDS) {
    const sets = exporter.exportArrays(kind, setIds);
    if (sets.length === 0) continue;
    files.push({ name: `${base}-${suffix}.csv`, text: buildCsv(kind, sets) });
  }
  return files;
}
