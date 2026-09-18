import { expect, test } from 'vitest';
import {
  buildCsv,
  buildCsvFiles,
  buildCsvHeader,
  fmtCalFactor,
  fmtComplex,
  fmtImag,
  fmtReal,
  type ExportKind,
  type ExportSet,
  type Exporter,
} from '../../src/lib/export/data';

// The expected strings below are PINNED against real numpy output:
//   np.savetxt(io.StringIO(), darray, delimiter=",")
// where `darray` is built exactly as pydvma file.py::export_to_csv builds it
// (set[0]'s axis as the first column, then each set's data appended). They
// are byte-for-byte what pydvma writes for these fixtures.

test('fmtReal matches numpy %.18e (18 fractional digits, e±DD, sign only if negative)', () => {
  expect(fmtReal(0)).toBe('0.000000000000000000e+00');
  expect(fmtReal(1.5)).toBe('1.500000000000000000e+00');
  expect(fmtReal(-2.25)).toBe('-2.250000000000000000e+00');
  expect(fmtReal(0.5)).toBe('5.000000000000000000e-01');
  expect(fmtReal(1.2)).toBe('1.199999999999999956e+00'); // beyond-double noise digits
  // -0.0 keeps its sign, exactly as numpy's %.18e does.
  expect(fmtReal(-0)).toBe('-0.000000000000000000e+00');
});

test('fmtImag matches numpy %+.18e (sign ALWAYS shown)', () => {
  expect(fmtImag(0)).toBe('+0.000000000000000000e+00');
  expect(fmtImag(3.4)).toBe('+3.399999999999999911e+00');
  expect(fmtImag(-0.5)).toBe('-5.000000000000000000e-01');
  expect(fmtImag(-0)).toBe('-0.000000000000000000e+00');
});

test('fmtComplex wraps ` (RE±IMj)` with the numpy leading space', () => {
  expect(fmtComplex(1.2, 3.4)).toBe(' (1.199999999999999956e+00+3.399999999999999911e+00j)');
  expect(fmtComplex(-2.0, -0.5)).toBe(' (-2.000000000000000000e+00-5.000000000000000000e-01j)');
  expect(fmtComplex(0, 0)).toBe(' (0.000000000000000000e+00+0.000000000000000000e+00j)');
});

/**
 * The calibration header every CSV now carries (see `buildCsvHeader`), for
 * the uncalibrated fixtures below: one `1` / `-` per data column. Composed
 * here so the data-row expectations stay readable and stay the thing under
 * test — the header gets its own dedicated tests further down.
 */
function hdr(kind: 'time' | 'freq' | 'tf', nCols: number): string {
  return [
    '# pydvma export: RAW data, calibration NOT applied.',
    `# Column 1 is the shared axis (${kind === 'time' ? 's' : 'Hz'}); the rest are data columns.`,
    '# Multiply data column k by cal_factors[k] for engineering units.',
    `# cal_factors: ${Array(nCols).fill('1').join(',')}`,
    `# units: ${Array(nCols).fill('-').join(',')}`,
  ].join('\n') + '\n';
}

test('buildCsv: single time set (real), two channels — exact numpy bytes', () => {
  const sets: ExportSet[] = [
    {
      setId: 0,
      axis: Float64Array.of(0, 0.5, 1.0),
      columns: [Float64Array.of(1.5, -2.25, 0.0), Float64Array.of(3.0, 4.0, -0.5)],
    },
  ];
  expect(buildCsv('time', sets)).toBe(
    hdr('time', 2) +
    '0.000000000000000000e+00,1.500000000000000000e+00,3.000000000000000000e+00\n' +
      '5.000000000000000000e-01,-2.250000000000000000e+00,4.000000000000000000e+00\n' +
      '1.000000000000000000e+00,0.000000000000000000e+00,-5.000000000000000000e-01\n',
  );
});

test('buildCsv: two time sets — axis is set[0]-only, then each set appended', () => {
  const sets: ExportSet[] = [
    { setId: 0, axis: Float64Array.of(0, 1), columns: [Float64Array.of(10, 20)] },
    { setId: 1, axis: Float64Array.of(0, 1), columns: [Float64Array.of(30, 40)] },
  ];
  expect(buildCsv('time', sets)).toBe(
    hdr('time', 2) +
    '0.000000000000000000e+00,1.000000000000000000e+01,3.000000000000000000e+01\n' +
      '1.000000000000000000e+00,2.000000000000000000e+01,4.000000000000000000e+01\n',
  );
});

test('buildCsv: complex (tf) set — axis is dtype-promoted to complex-with-zero-imag', () => {
  const sets: ExportSet[] = [
    {
      setId: 0,
      axis: Float64Array.of(0, 1),
      columns: [{ re: Float64Array.of(1.2, -2.0), im: Float64Array.of(3.4, -0.5) }],
    },
  ];
  expect(buildCsv('tf', sets)).toBe(
    hdr('tf', 1) +
    ' (0.000000000000000000e+00+0.000000000000000000e+00j), (1.199999999999999956e+00+3.399999999999999911e+00j)\n' +
      ' (1.000000000000000000e+00+0.000000000000000000e+00j), (-2.000000000000000000e+00-5.000000000000000000e-01j)\n',
  );
});

test('buildCsv: freq uses the same complex rendering as tf', () => {
  const sets: ExportSet[] = [
    {
      setId: 0,
      axis: Float64Array.of(0, 1),
      columns: [{ re: Float64Array.of(1.2, -2.0), im: Float64Array.of(3.4, -0.5) }],
    },
  ];
  expect(buildCsv('freq', sets)).toBe(buildCsv('tf', sets));
});

test('buildCsv: empty sets → empty string', () => {
  expect(buildCsv('time', [])).toBe('');
});

test('buildCsv: mismatched row counts throw (numpy np.append would fail)', () => {
  const sets: ExportSet[] = [
    { setId: 0, axis: Float64Array.of(0, 1, 2), columns: [Float64Array.of(1, 2, 3)] },
    { setId: 1, axis: Float64Array.of(0, 1), columns: [Float64Array.of(9, 9)] },
  ];
  expect(() => buildCsv('time', sets)).toThrow(/same number of samples/);
});

/** A fake exporter for the file-routing tests. */
function stubExporter(
  data: Partial<Record<ExportKind, ExportSet[]>>,
  seen?: (readonly number[] | undefined)[],
): Exporter {
  return {
    exportArrays: (kind, setIds) => {
      seen?.push(setIds);
      const sets = data[kind] ?? [];
      return setIds ? sets.filter((s) => setIds.includes(s.setId)) : sets;
    },
    exportMat: async () => new Uint8Array([1, 2, 3]),
    choosableSets: () => [],
  };
}

test('buildCsvFiles: only kinds with data are emitted, named <base>-<kind>.csv', () => {
  const exporter = stubExporter({
    time: [{ setId: 0, axis: Float64Array.of(0, 1), columns: [Float64Array.of(2, 3)] }],
  });
  const files = buildCsvFiles(exporter, 'logged_data');
  expect(files.map((f) => f.name)).toEqual(['logged_data-time.csv']);
  expect(files[0].text).toBe(
    hdr('time', 1) +
    '0.000000000000000000e+00,2.000000000000000000e+00\n' +
      '1.000000000000000000e+00,3.000000000000000000e+00\n',
  );
});

test('buildCsvFiles: multiple kinds → one file each, in time/freq/tf order', () => {
  const exporter = stubExporter({
    time: [{ setId: 0, axis: Float64Array.of(0, 1), columns: [Float64Array.of(2, 3)] }],
    tf: [
      {
        setId: 0,
        axis: Float64Array.of(0, 1),
        columns: [{ re: Float64Array.of(1, 2), im: Float64Array.of(0, 0) }],
      },
    ],
  });
  const files = buildCsvFiles(exporter, 'run7');
  expect(files.map((f) => f.name)).toEqual(['run7-time.csv', 'run7-tf.csv']);
});

test('buildCsvFiles: no data → no files', () => {
  expect(buildCsvFiles(stubExporter({}), 'logged_data')).toEqual([]);
});

test('buildCsvFiles: a "Choose sets…" pick threads through to every kind', () => {
  const seen: (readonly number[] | undefined)[] = [];
  const exporter = stubExporter({
    time: [
      { setId: 0, axis: Float64Array.of(0, 1), columns: [Float64Array.of(2, 3)] },
      { setId: 1, axis: Float64Array.of(0, 1), columns: [Float64Array.of(8, 9)] },
    ],
  }, seen);

  const files = buildCsvFiles(exporter, 'run7', [1]);
  expect(seen).toEqual([[1], [1], [1]]);            // time, freq, tf all asked
  expect(files.map((f) => f.name)).toEqual(['run7-time.csv']);
  // Only the chosen set's column is beside the axis.
  expect(files[0].text).toBe(
    hdr('time', 1) +
    '0.000000000000000000e+00,8.000000000000000000e+00\n' +
      '1.000000000000000000e+00,9.000000000000000000e+00\n',
  );
  // No pick ⇒ no filter reaches the accessor (today's behaviour, unchanged).
  seen.length = 0;
  buildCsvFiles(exporter, 'run7');
  expect(seen).toEqual([undefined, undefined, undefined]);
});

// ── Calibration header (F5) ────────────────────────────────────────────────
// The data rows stay RAW — that is the point of this export — but the file
// now says so and carries the per-column factor that converts to engineering
// units. It must match `pydvma.file._csv_header` byte-for-byte, because the
// browser and pydvma are supposed to write the same file.

test('buildCsvHeader: states the raw-data contract and the per-column factors', () => {
  const sets: ExportSet[] = [{
    setId: 0,
    axis: Float64Array.of(0, 1),
    columns: [Float64Array.of(1, 2), Float64Array.of(3, 4)],
    calFactors: [10, 0.5],
    units: ['m/s²', 'N'],
  }];
  expect(buildCsvHeader('time', sets)).toBe(
    '# pydvma export: RAW data, calibration NOT applied.\n'
    + '# Column 1 is the shared axis (s); the rest are data columns.\n'
    + '# Multiply data column k by cal_factors[k] for engineering units.\n'
    + '# cal_factors: 10,0.5\n'
    + '# units: m/s²,N\n',
  );
});

test('buildCsvHeader: the axis unit follows the kind; sets concatenate in order', () => {
  const sets: ExportSet[] = [
    { setId: 0, axis: Float64Array.of(0), columns: [{ re: Float64Array.of(1), im: Float64Array.of(0) }], calFactors: [2], units: ['Pa'] },
    { setId: 1, axis: Float64Array.of(0), columns: [{ re: Float64Array.of(1), im: Float64Array.of(0) }], calFactors: [4], units: ['N'] },
  ];
  const h = buildCsvHeader('freq', sets);
  expect(h).toContain('# Column 1 is the shared axis (Hz);');
  expect(h).toContain('# cal_factors: 2,4\n');
  expect(h).toContain('# units: Pa,N\n');
});

test('buildCsvHeader: absent metadata renders as identity / unknown, never blank', () => {
  const sets: ExportSet[] = [{
    setId: 0, axis: Float64Array.of(0), columns: [Float64Array.of(1), Float64Array.of(2)],
    calFactors: [5],          // SHORT on purpose — the second column has none
  }];
  expect(buildCsvHeader('time', sets)).toContain('# cal_factors: 5,1\n');
  expect(buildCsvHeader('time', sets)).toContain('# units: -,-\n');
});

// Known-answer vectors mirrored VERBATIM from
// `pydvma.file.CAL_FACTOR_FORMAT_VECTORS`. `%.12g` is not a format JS has
// natively (`toPrecision` switches to exponential at a different threshold
// and keeps trailing zeros), so the twin implementation is pinned rather than
// trusted. A change on either side must change both.
const CAL_FACTOR_FORMAT_VECTORS: [number, string][] = [
  [1.0, '1'],
  [10.0, '10'],
  [0.5, '0.5'],
  [-0.5, '-0.5'],
  [1000.0, '1000'],
  [0.001, '0.001'],
  [1e-5, '1e-05'],
  [1.5e-7, '1.5e-07'],
  [123456789012.0, '123456789012'],
  [1234567890123.0, '1.23456789012e+12'],
  [1.0 / 3.0, '0.333333333333'],
  [2.0 / 3.0, '0.666666666667'],
  [0.0001, '0.0001'],
  [1e16, '1e+16'],
];

test('fmtCalFactor matches python format_cal_factor on every shared vector', () => {
  for (const [value, expected] of CAL_FACTOR_FORMAT_VECTORS) {
    expect(`${value} → ${fmtCalFactor(value)}`).toBe(`${value} → ${expected}`);
  }
});

test('fmtCalFactor: a non-finite factor renders as the identity, never NaN', () => {
  expect(fmtCalFactor(NaN)).toBe('1');
  expect(fmtCalFactor(Infinity)).toBe('1');
  expect(fmtCalFactor(-Infinity)).toBe('1');
});
