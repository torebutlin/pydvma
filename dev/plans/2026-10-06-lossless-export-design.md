# Lossless CSV and MATLAB exports that load back (design, 2026-10-06)

## What Tore asked for

"Fix your own CSV export so it is more complete, and can be re-imported
(and should recover the same info that a dvma save would). Same with .mat
ideally." Then: "read pydvma's own export back once the other fixes are in
place."

Decided with Tore (2026-10-06):

- **CSV: one file for the whole export**, each item its own table (not
  today's one file per kind), so a reload keeps a TF linked to its time
  data and Load Data takes one file.
- **.mat: drop the interpolated common-grid matrices** (`time_data_all`,
  `tf_axis_all`, … and their `*_cal_factors` / `*_units`). The file holds
  the exact per-item data only.
- Assumed from the earlier exchange, not separately asked: the web app's
  exports carry what its Save carries (see "Web app" below).

## What is wrong today (verified 2026-10-06)

- `export_to_csv(data_list)` writes one kind, every set's columns on the
  FIRST set's axis. Sets of different lengths crash inside `np.append`
  (and the web app's twin throws "all sets must share the same number of
  samples"). FFT/TF cells are numpy's `(re+imj)` text, the frequency
  column included, which Excel, pandas and MATLAB read as strings. There
  is no coherence, no fs, no channel roles, no names or timestamps, no set
  boundaries, and FFT and TF files cannot be told apart.
- `export_to_matlab(dataset)` interpolates every set onto one common grid
  (linear interpolation of time data between sample rates; a 20-point
  stepped sine spread over a fine grid) and drops coherence, cross-spectra,
  sonograms and modal fits.
- Neither can be loaded back: `load_data` refuses both.

## Approach: the .dvma manifest, carried by CSV and .mat

A `.dvma` is a JSON manifest (every item's kind, metadata, settings,
calibration, units, names, timestamps, ids and links, provenance, and the
app's own per-item state) plus its arrays. Both exports carry **that same
manifest** and **every array**, and both readers rebuild the dataset
through **the same reader** `.dvma` uses. Nothing is listed field by
field, so the three formats cannot drift apart, and a field added to the
container later reaches CSV and .mat with no extra work.

Alternatives considered and rejected:

- A hand-designed CSV schema (`key=value` lines per set, like the
  Vibration Apps). Readable, but every field of `MySettings` (about 50)
  and every optional attribute would have to be mapped by hand and kept in
  step with the container forever; it would end up as JSON anyway.
- Keeping today's files and adding a separate "complete" export. Two
  formats per tool, and the familiar button would still produce a file
  that cannot come back.

### 1. `container`: split the writer and reader from the zip

`_write_dataset(zf, dataset)` becomes two steps:

- `dataset_manifest(dataset) -> (manifest, arrays)`: the manifest dict
  exactly as today, and `{member_name: ndarray}` for every array.
- `dataset_from_manifest(manifest, get_array, source)`: today's `load`
  body, with `get_array(member)` in place of reading a zip member.

`save`, `save_bytes`, `load` and `load_bytes` call them. **The `.dvma`
bytes stay identical** (pinned by a test that saves the same dataset
before and after and compares every member and the manifest JSON).

### 2. CSV: format `pydvma-csv 1`

```
# pydvma dataset (pydvma-csv 1)
# Written by pydvma 2.6.0. Load it back with pydvma.load_data('x.csv') or the web app's Load Data.
# Values are RAW, calibration NOT applied: multiply a column by its item's channel_cal_factors.
# Each '# table' line below starts one table: its column names, then its rows.
# manifest: {"format": "dvma-dataset", "format_version": 1, ..., "items": [...], "csv_tables": [...]}
# table 0: item 0, TimeData 'impulse test' (2 channels, fs 10000 Hz, units m/s, N)
time_axis,time_data[0],time_data[1]
0,0.0012,-0.0003
...
# table 1: item 1, TfData 'impulse test' (1 output, ch_in 0, units m/s/N)
freq_axis,tf_data[0].re,tf_data[0].im,tf_coherence[0]
...
```

- **Manifest**: the container manifest as one JSON line, ASCII-escaped,
  plus a `csv_tables` key: for each table, its item, and for each array in
  it the field, original shape, dtype, the axis moved to the rows and the
  first column. The reader needs nothing else; the table heading lines
  are for people.
- **Tables**: one per item, plus one per array that cannot share it. The
  row axis is the item's primary axis (`time_axis` / `freq_axis`; `M` for
  a modal fit). Each array is laid out with that axis as rows (moved to
  the front if it is not already: `Pxy` is `(n, n, F)`) and its other
  axes flattened, C order, into columns. An array with no axis of that
  length (a sonogram's `time_axis`, a `ModalData`'s `M`) gets its own
  table. Complex arrays become `.re` / `.im` column pairs.
- **Numbers**: floats `%.17g` (round-trips every float64 exactly),
  integers `%d`, booleans 0/1, `nan`, `inf`, `-inf`. dtypes restore
  from the manifest. Every array comes back **bit-identical**.
- Reading: split at the `# table` lines, `np.loadtxt` each table in one
  pass, check the row and column counts against the manifest, rebuild the
  arrays, then `dataset_from_manifest`.
- Still a normal CSV for other tools: Excel shows the tables one under
  another, and `pandas.read_csv(f, comment='#')` reads one table at a time
  (the docs show how to split them).
- Size: about 24 bytes per value. A 30 s, 51.2 kHz, 4-channel capture is
  about 150 MB, as today's CSV already is.

### 3. MATLAB: format `pydvma-mat 1`

Variables:

- `pydvma_format`: `'pydvma-mat 1'`.
- `pydvma_manifest`: the manifest as JSON text (MATLAB's `jsondecode`
  reads it); its `mat_arrays` key gives each array's shape and dtype.
- `pydvma_items`: a cell array, one struct per item: `kind`,
  `test_name`, `units`, `channel_cal_factors`, `fs`, `timestamp` (ISO
  text) and each array field under its own name, at its exact shape
  (1-D arrays as column vectors). `d = load('x.mat');
  d.pydvma_items{2}.tf_data` is the TF of the second item.

The interpolated `*_all` matrices and their `*_cal_factors` / `*_units`
are **removed** (Tore). `export_to_matlab_jwlogger` is unchanged: it
writes another program's format.

Reading: `scipy.io.loadmat(..., simplify_cells=True)`, then each array is
reshaped and cast back from `mat_arrays` (savemat squeezes and stores
booleans as uint8), then `dataset_from_manifest`. Verified: scipy
round-trips non-ASCII text and cells of structs.

### 4. Python API

- `export_to_csv(data, filename, overwrite_without_prompt=False)` and
  `export_to_matlab(data, filename, overwrite_without_prompt=False)`:
  `data` is a `DataSet` or any data list (`TimeDataList`, `TfDataList`,
  …), which is wrapped in a `DataSet`. The deprecated `parent` stays
  where it is today. Positional use keeps working
  (`export_to_csv(ds.tf_data_list, 'x.csv')`).
- `load_data` recognises both by content: a CSV whose first line names
  `pydvma-csv`, a `.mat` with `pydvma_manifest`. It still reads `.dvma`,
  legacy `.npy`, JW-logger `.mat` and the Vibration Apps CSV.
- Files exported before this change are refused with a reason: a CSV
  with the old `# pydvma export: RAW data` header, a `.mat` with
  `time_data_all` / `freq_data_all` / `tf_data_all` and no manifest
  ("exported by pydvma 2.6 or earlier, which could not be read back:
  export it again, or load the .dvma").
- `format_cal_factor` and `CAL_FACTOR_FORMAT_VECTORS` stay public (2.5.0
  API); they are no longer used by the CSV writer.

### 5. Web app

- **Export CSV** and **Export Matlab** build the same document Save
  builds: `materializeDerived()` (so computed FFT/TF are real items),
  the same sonogram question, `stampUiState()`, `subsetDataset(setIds)`
  for "Choose sets…", then `writeDvma`. That `.dvma` goes to new engine
  ops `dvma_to_csv` / `dvma_to_mat`, which run the Python writers. One
  writer per format, shared by Python and the app.
- Export CSV writes **one** file, `<name>.csv`.
- **Removed**: the TypeScript CSV writer in `lib/export/data.ts`
  (`buildCsv`, `buildCsvHeader`, the `fmt*` helpers and `fmtCalFactor`,
  its byte-identity vectors), `actions.exportArrays` / `exportMat`, and
  the engine's `export_mat` op with its tests. Export CSV then needs the
  engine started, as Export Matlab already does.
- **Load Data**: one engine op, `file_to_dvma(data, name)`, writes the
  bytes to a temp file and calls `load_data`, so the app accepts exactly
  what Python does (pydvma CSV and .mat, JW `.mat`, Vibration Apps CSV).
  It replaces `mat_to_dvma` and `vibration_csv_to_dvma`; `legacy_to_dvma`
  stays (it unpickles, which `load_data` also does, but keeps its own
  stale-wheel guard). `sniffFormat` gains `pydvmacsv`; a `.mat` goes to
  the engine as today and Python decides what it is.

### 6. Tests

- **Round trip, the core test**: a dataset with every kind (TimeData with
  calibration, units, a non-ASCII name and a timestamp; FreqData;
  CrossSpecData with `enbw_hz`; TfData with coherence, BLA sigmas,
  `source_settings` and `source_signature`; SonoData; ModalData with its
  `measurement_type` / `source_targets` extras; MetaData; the app's `ui`
  extras; NaN and ±inf values; a dangling `id_link`). For CSV and for
  .mat: export, load, and compare with save/load as `.dvma`: the same
  manifest and bit-identical arrays.
- `.dvma` bytes unchanged by the container refactor.
- A Vibration Apps import exported to CSV and .mat loads back equal.
- Different-length sets export (the old crash) and keep their own axes.
- Old exports are refused with the reason; any other CSV too.
- Web app: `e2e/export.spec.ts` (it pins today's CSV layout) is rewritten
  to export CSV and Matlab and load each back through Load Data, getting
  the same sets; vitest for the new sniff route and for the removed
  writer's call sites.
- The `@engine` Playwright specs and the full suites, as the CLAUDE.md
  lesson on file formats requires.

### 7. Docs and release

- `docs/web-logger/export.md` ("What each output holds", "Opening
  files"), `docs/user-guide/import-export.md` (CSV and MATLAB sections,
  reading a table with pandas, MATLAB access), `docs/web-logger/
  dvma-format.md` (the same manifest travels in CSV and .mat).
- CHANGELOG `## Unreleased`, **Changed**: both export formats change and
  existing scripts that read them need updating; the next release should
  be at least a minor version (Tore's call).
- TODO: the `export_to_csv` problems entry closes.

## Out of scope

- The JW-logger export.
- H2 / H_power (TODO), and the per-set poles fit mode (TODO, its own
  design round).
