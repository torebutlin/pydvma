import { expect, test } from 'vitest';
import {
  buildCsv,
  buildCsvFiles,
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

test('buildCsv: single time set (real), two channels — exact numpy bytes', () => {
  const sets: ExportSet[] = [
    {
      setId: 0,
      axis: Float64Array.of(0, 0.5, 1.0),
      columns: [Float64Array.of(1.5, -2.25, 0.0), Float64Array.of(3.0, 4.0, -0.5)],
    },
  ];
  expect(buildCsv('time', sets)).toBe(
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
function stubExporter(data: Partial<Record<ExportKind, ExportSet[]>>): Exporter {
  return {
    exportArrays: (kind) => data[kind] ?? [],
    exportMat: async () => new Uint8Array([1, 2, 3]),
  };
}

test('buildCsvFiles: only kinds with data are emitted, named <base>-<kind>.csv', () => {
  const exporter = stubExporter({
    time: [{ setId: 0, axis: Float64Array.of(0, 1), columns: [Float64Array.of(2, 3)] }],
  });
  const files = buildCsvFiles(exporter, 'logged_data');
  expect(files.map((f) => f.name)).toEqual(['logged_data-time.csv']);
  expect(files[0].text).toBe(
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
