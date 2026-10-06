# Lossless CSV and MATLAB exports — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CSV and .mat exports that carry exactly what a `.dvma` carries, and that `load_data` and the web app's Load Data read back.

**Architecture:** `container` is split so the manifest + arrays of a dataset can be built and consumed without a zip. A new private module `pydvma/_exchange.py` lays that manifest and those arrays out as a CSV (format `pydvma-csv 1`) or a MATLAB dict (format `pydvma-mat 1`) and reads them back through the same container reader. `file.py` and new engine ops call it; the web app exports the document Save builds through those ops.

**Tech Stack:** Python 3.11+, numpy, scipy.io; Svelte/TypeScript web app (vitest, Playwright); pyodide engine wheel.

**Spec:** `dev/plans/2026-10-06-lossless-export-design.md` (approved by Tore 2026-10-06, "go ahead as written").

## Global Constraints

- CSV first line exactly `# pydvma dataset (pydvma-csv 1)`; MATLAB variable `pydvma_format = 'pydvma-mat 1'`.
- Floats as the shortest text that reads back to the same float64 (Python `repr`; first drafted as `%.17g`, which writes `0.1` as `0.10000000000000001`), ints `%d`, booleans `0`/`1`, `nan`, `inf`, `-inf`; every array comes back bit-identical (dtype and shape too).
- `.dvma` bytes unchanged by the container refactor.
- `.mat`: no `*_all`, `*_cal_factors`, `*_units` variables any more.
- `export_to_csv` / `export_to_matlab`: first argument a `DataSet` or any data list; `parent` (deprecated) stays where it is; positional filename keeps working.
- Exports from pydvma 2.6 and earlier are refused with a reason; so is any CSV that is neither pydvma's nor the Vibration Apps'.
- `format_cal_factor` and `CAL_FACTOR_FORMAT_VECTORS` stay public.
- Repo rules (CLAUDE.md): docstring for every public function (griffe-strict: one parameter per Args line); `python -m mkdocs build --strict` green; the full Playwright suite (incl. `@engine`) runs whenever a file format changes; engine wheel rebuilt with `(cd webui && npm run vendor:wheels)` after any `pydvma/*.py` change the browser uses; Playwright only from `webui/`; never `git stash`.

## Review Focus

1. **An empty export** (no items, or a "Choose sets…" pick with no data): expect a clear ValueError "nothing to export", not an empty file. Test in Task 4.
2. **A CSV opened and re-saved by Excel** (CRLF line ends, a BOM, numbers rewritten at lower precision or a row lost): CRLF and BOM must read; a changed row/column count must stop with "the file was changed after export: table k has … rows, the manifest says …". Test in Task 2.
3. **Text with newlines or commas in a test name or unit** reaching a `# table` heading line or a column name: headings are for people, so newlines are replaced there; the manifest holds the truth. Test in Task 2.
4. **Items with absent arrays** (`tf_coherence` None, a fresh `ModalData` with `M == []`, an old item without `bla_sigma_n`): absent stays absent after the round trip. Covered by the rich dataset in Task 2/3.
5. **Big time data in the browser engine** (30 s × 51.2 kHz × 4 ch, ~150 MB of CSV): the writer must stream table by table into one buffer (`np.savetxt` into `io.StringIO`), never build a Python list of row strings. Checked by a size/time smoke test in Task 2 (2 M values under a few seconds).

---

### Task 1: Split `container` into manifest builder / reader and zip carrier

**Files:**
- Modify: `pydvma/container.py` (`_write_dataset`, `save`, `save_bytes`, `load`, `load_bytes`)
- Test: `tests/test_container.py`

**Interfaces — Produces:**
```python
def dataset_manifest(dataset) -> tuple[dict, dict[str, np.ndarray]]:
    """(manifest, arrays): the manifest exactly as .dvma writes it, and
    {member_name: array} for every array it references."""

def dataset_from_manifest(manifest: dict, get_array, source) -> DataSet:
    """Rebuild a DataSet from a manifest; get_array(member) returns the
    ndarray for a member name; source names the file in error messages."""
```

- [ ] **Step 1: failing tests** — `test_dvma_bytes_unchanged_by_the_split` (build a rich dataset, see Task 2's helper; save with the CURRENT code into a fixture captured at test time is impossible, so instead assert `save_bytes(ds)` == a zip rebuilt from `dataset_manifest(ds)` member by member, and pin manifest JSON equality with `json.dumps(manifest, indent=1, allow_nan=False)` against the zip's `manifest.json`); `test_from_manifest_round_trips` (manifest + arrays dict → `dataset_from_manifest` equals `load_bytes(save_bytes(ds))` item for item).
- [ ] **Step 2:** run, see them fail (`dataset_manifest` undefined).
- [ ] **Step 3:** move the body of `_write_dataset` into `dataset_manifest` (collect `arrays[member] = np.asarray(arr)` instead of writing); `_write_dataset(zf, ds)` becomes: `manifest, arrays = dataset_manifest(ds)`; write each array with `_write_array`, in the same order as today, then `manifest.json`. Move `load`'s per-item loop into `dataset_from_manifest`; `load` opens the zip, validates format/version (unchanged messages), and calls `dataset_from_manifest(manifest, lambda m: _read_array(zf, m), source)`. Version and format checks live in a shared `_check_manifest(manifest, source)` used by both.
- [ ] **Step 4:** full `tests/test_container.py`, `tests/test_journal.py`, `tests/test_session_launch.py` green; before/after `save_bytes` of the rich dataset identical (compare with `git stash`-free method: run the old code from `git show HEAD:pydvma/container.py` in a temp module).
- [ ] **Step 5:** commit `refactor(container): manifest builder and reader apart from the zip`.

### Task 2: CSV carrier (`pydvma-csv 1`)

**Files:**
- Create: `pydvma/_exchange.py`
- Create: `tests/_rich_dataset.py` (shared builder), `tests/test_exchange_csv.py`

**Interfaces — Consumes:** Task 1. **Produces:**
```python
CSV_FORMAT = 'pydvma-csv 1'
def is_pydvma_csv_line(first_line: str) -> bool        # any 'pydvma-csv N'
def dataset_to_csv_text(dataset) -> str
def dataset_from_csv_text(text: str, name: str) -> DataSet
```

Layout (from the spec): header lines; `# manifest: <json>` with key `csv_tables`:
`[{"item": i, "rows": R, "arrays": [{"field": f, "shape": [...], "dtype": "float64", "row_axis": k, "first_column": c, "n_columns": n, "complex": bool}]}]`.
Row axis: the item's primary axis length R = len of its first present array in `_ARRAY_FIELDS[kind]` order; for each array pick the FIRST axis whose length is R (move it to the front, flatten the rest C-order); an array with no such axis starts its own table keyed by its own leading axis. Column names: `field` for 1-D, `field[i]` / `field[i,j]` for flattened indices, `.re`/`.im` suffix for complex.

- [ ] **Step 1: failing tests** — `test_round_trip_equals_dvma` (rich dataset → text → dataset; compare manifests via `dataset_manifest` on both and arrays bit-identical incl. NaN/inf and dtypes); `test_first_line_and_tables_are_readable` (first line, `# table` lines, column names like `tf_data[0].re`); `test_tables_have_their_own_lengths` (two TfData of 5 and 7 rows → two tables); `test_crlf_and_bom_read`; `test_changed_row_count_is_refused` (drop a row → ValueError naming table and counts); `test_newline_in_a_name_does_not_break_the_file`; `test_pandas_reads_a_table` (`pd.read_csv` on one table's lines with `comment='#'` — skip if pandas absent); `test_two_million_values_in_seconds` (TimeData 500k×4; write+read < 10 s).
- [ ] **Step 2:** run, see them fail.
- [ ] **Step 3:** implement `_exchange.py` CSV half: `dataset_to_csv_text` writes into one `io.StringIO`, each table with `np.savetxt(buf, block, delimiter=',', fmt=col_fmts, comments='')` where `block` is float64 (ints as exact floats only if |x| < 2**53, else `%d` columns via a per-column fmt list); `dataset_from_csv_text` strips BOM, normalises CRLF, finds the manifest line, splits at `# table` lines, `np.loadtxt(io.StringIO(...), delimiter=',', ndmin=2)` per table, rebuilds arrays from `csv_tables`, then `container.dataset_from_manifest`. Booleans written `0`/`1` and cast back. Manifest JSON with `ensure_ascii=True`.
- [ ] **Step 4:** tests green.
- [ ] **Step 5:** commit `feat: pydvma-csv 1 — a dataset as one CSV that loads back`.

### Task 3: MATLAB carrier (`pydvma-mat 1`)

**Files:** Modify `pydvma/_exchange.py`; Test `tests/test_exchange_mat.py`

**Produces:**
```python
MAT_FORMAT = 'pydvma-mat 1'
def dataset_to_mat_dict(dataset) -> dict          # for scipy.io.savemat
def is_pydvma_mat(d: dict) -> bool                # has 'pydvma_manifest'
def dataset_from_mat_dict(d: dict, name: str) -> DataSet   # d from loadmat(simplify_cells=True)
```
Variables: `pydvma_format`, `pydvma_manifest` (JSON text, key `mat_arrays`: `{member: {"item": i, "field": f, "shape": [...], "dtype": "..."}}`), `pydvma_items` (object array of dicts: `kind`, `test_name`, `units`, `channel_cal_factors`, `fs`, `timestamp` ISO text, and each array under its field name, 1-D as column vectors).

- [ ] **Step 1: failing tests** — `test_round_trip_equals_dvma` through a real file (`savemat` → `loadmat(simplify_cells=True)` → equal manifests, bit-identical arrays, dtypes incl. bool and int); `test_matlab_view` (`pydvma_items[k]['tf_data']` shape `(n, 1)`, `freq_axis` a column vector, `test_name` text); `test_no_common_grid_variables` (no key ending `_all`, `_cal_factors`, `_units` at top level); `test_non_ascii_name_round_trips`.
- [ ] **Step 2:** run, fail. **Step 3:** implement (reshape + `astype` from `mat_arrays`; `simplify_cells` turns a 1-item cell into a dict — wrap). **Step 4:** green. **Step 5:** commit `feat: pydvma-mat 1 — exact per-item MATLAB export that loads back`.

### Task 4: `file.py` API, `load_data` routing, old-format refusals

**Files:** Modify `pydvma/file.py` (`export_to_csv`, `export_to_matlab`, `load_data`, `_not_vibration_apps_csv`, remove now-dead `_csv_header`, `_column_calibration`, `_attach_matlab_calibration`, `_attach_matlab_column_calibration`, `_time_grid`/`_spectral_grid`/`_interp_onto`/`_clean_rate` ONLY if nothing else uses them — `export_to_matlab_jwlogger` does use some: keep those); Tests: `tests/test_file.py` (replace the layout-pinning tests listed below), `tests/test_vibration_apps_csv.py`.

Tests to retire or rewrite (they pin the old layouts): `test_csv_header_names_the_factors_and_units`, `test_csv_header_does_not_disturb_the_data_rows`, `test_csv_tf_header_carries_the_ratio_and_out_over_in_unit`, `test_matlab_export_carries_cal_factors_and_units`, `test_matlab_export_keeps_every_stored_column`, `test_tf_only_dataset_exports`, `test_pydvma_export_is_refused_as_export_only`, `test_load_data_refuses_a_pydvma_export_too`, `test_export_to_csv_positional`, `test_export_to_matlab_positional` (keep the positional behaviour, new assertions).

- [ ] **Step 1: failing tests** — `test_export_to_csv_loads_back` / `test_export_to_matlab_loads_back` (DataSet and a bare `TfDataList`); `test_different_length_sets_export` (the old crash); `test_empty_export_is_refused`; `test_old_csv_export_is_refused_with_reason` (text starting `# pydvma export: RAW data`); `test_old_mat_export_is_refused_with_reason` (`time_data_all` without manifest); `test_vibration_apps_import_exports_and_reloads` (v2 example → CSV and .mat → load equal); the Vibration Apps "any other CSV" test updated (its message now says pydvma's own exports from this version load).
- [ ] **Step 2:** fail. **Step 3:** implement: `_as_dataset(data)` wraps a list; `export_to_csv` writes `dataset_to_csv_text` (UTF-8, `newline=''`), `export_to_matlab` `scipy.io.savemat(filename, dataset_to_mat_dict(ds), oned_as='column')`; `load_data`: zip → `.dvma`; first line `pydvma-csv` → CSV; Vibration Apps → as now; `.mat` → `loadmat` once, `pydvma_manifest` → exchange, else JW-logger import (its own refusal of the old pydvma `.mat` keeps its keys check, message updated to "exported by pydvma 2.6 or earlier"); `.csv` other → refusal naming both formats it can read. Docstrings rewritten.
- [ ] **Step 4:** `python -m pytest` full green. **Step 5:** commit `feat: export_to_csv / export_to_matlab carry the whole dataset and load back`.

### Task 5: Engine ops

**Files:** Modify `pydvma/engine.py` (add `dvma_to_csv`, `dvma_to_mat`, `file_to_dvma`; delete `export_mat`, `mat_to_dvma`, `vibration_csv_to_dvma` and helpers only they use: `_common_axis`, `_extend_column_calibration`); Tests: `tests/test_engine_import_ops.py` (rewrite for `file_to_dvma`), delete `tests/test_engine_export_mat.py`, new `tests/test_engine_export_ops.py`.

```python
def dvma_to_csv(dvma_bytes) -> {'csv': bytes}      # UTF-8 text of export_to_csv
def dvma_to_mat(dvma_bytes) -> {'mat': bytes}      # savemat into BytesIO
def file_to_dvma(data, name) -> {'dvma': bytes}    # temp file named `name`, load_data, save_bytes
```
- [ ] Steps: failing tests (each op round-trips a rich dataset; `file_to_dvma` handles pydvma CSV, pydvma .mat, JW .mat, Vibration Apps CSV, and refuses others with the message naming `name`); implement; green; commit `feat(engine): dvma_to_csv, dvma_to_mat, file_to_dvma`.

### Task 6: Web app

**Files:** Modify `webui/src/components/cards/ExportCard.svelte`, `webui/src/App.svelte` (`onsave` pipeline factored into `buildSaveDocument(setIds)` shared by Save and the exports; `toDataset` routing), `webui/src/lib/analysis/actions.ts` (remove `exportArrays`, `exportMat`, `exportColumnCalibration` if unused), `webui/src/lib/export/data.ts` (remove the CSV writer; keep `ChoosableSet`/`Exporter` types adjusted), `webui/src/lib/files/sniff.ts` (`pydvmacsv`), `webui/src/lib/files/workdir.ts`; Tests: `webui/tests/export/data.test.ts` (drop writer tests), `webui/tests/files/sniff.test.ts`, `webui/e2e/export.spec.ts` (rewrite), `webui/e2e/files.spec.ts`.

- [ ] Steps: vitest for sniff `pydvmacsv` (first line `# pydvma dataset (pydvma-csv`), and for the exporter calling `dvma_to_csv` / `dvma_to_mat` with `writeDvma` bytes of the subset document; implement; e2e: Export CSV → one download `<name>.csv` → Load Data it → same sets and lines; same for Matlab; `npm run vendor:wheels`; `npm run check`; vitest; Playwright full incl. `@engine`; commit `feat(webui): exports carry the Save document and load back`.

### Task 7: Docs, CHANGELOG, TODO, CLAUDE.md, gates

- [ ] `docs/web-logger/export.md`, `docs/user-guide/import-export.md`, `docs/web-logger/dvma-format.md`, `docs/getting-started/basic-usage.md` (CSV example), `docs/api/file.md` (unchanged list; check); CHANGELOG `## Unreleased` → `### Changed` (both formats, scripts need updating, minor version); TODO entry for export problems closed; CLAUDE.md current-focus entry.
- [ ] Gates: full pytest, vitest, `npm run check`, mkdocs `--strict`, Playwright full (incl. `@engine`); commit `docs: lossless exports`.
