# Saving and exporting

The **Export** stage saves your session and writes files for use
elsewhere. Everything the web logger holds — time series, spectra,
transfer functions, sonograms, modal fits, calibration and units — can
be saved to pydvma's native format or exported to MATLAB, CSV or a
figure.

## Save the session (`.dvma`)

**Save Dataset** writes a [`.dvma` container](dvma-format.md): a zip of a
JSON manifest plus plain `.npy` arrays, containing no executable code and
safe to share. It captures the full dataset, including your calibration,
units, channel labels and any modal fit — so reopening it (in the web
logger, in Python via `dvma.load_data()`, or in the JupyterLite notebook)
restores exactly where you were.

### Autosave and session restore

The **Autosave** switch (on by default) writes your session to browser
storage a couple of seconds after every change:

- If the app has access to a working folder, it keeps an `autosave.dvma`
  there.
- Otherwise it stores the session in the browser (IndexedDB) and offers
  **Restore last session?** the next time you open the app.

A clean **Save Dataset** clears the autosave. Turn Autosave off to stop
the background writes.

## Export data

- **Export Matlab** writes a `.mat` file. The MATLAB bytes are built by
  SciPy (`scipy.io.savemat`) in the engine, so the structure matches the
  Python [`export_to_matlab`](../user-guide/import-export.md#export-to-matlab).
- **Export CSV** writes CSV files (one per data kind — time / freq / tf).
  The CSV is generated to **byte-for-byte match** pydvma's
  [`export_to_csv`](../user-guide/import-export.md#export-to-csv):
  `%.18e` formatting, complex values written as `(RE±IMj)`, and **raw**
  (uncalibrated) values, so a browser export and a Python export of the
  same data are identical.

!!! info "Schema parity"
    Both the `.mat` and CSV exporters reproduce the Python file schemas
    exactly, so files are interchangeable between the web logger and
    scripted pydvma workflows. The `.dvma` format is the same on both
    sides too — see [the format reference](dvma-format.md).

## Export figures

The current plot can be written as a **figure**:

- **format** — tick **PNG** (raster, 3× scale) and/or **PDF** (vector);
  tick both to write both.
- **background** — **white** (default), **transparent**, or **dark**. The
  *dark* option recolours the figure chrome for a dark background while
  preserving the data lines — useful for slides.
- **filename** — a default like `pydvma_figure_YYYY-MM-DD_HHMM`, editable.

The figure contains what the plot shows: the **legend** is included when
it is toggled visible (at its on-screen position, listing the drawn
lines — hidden lines are left out), and the TF **coherence** overlay and
its right-hand axis export exactly when that toggle is on. A Bode export
contains **both** stacked panes; a sonogram export includes the heat
map.

Press **Export** to write the ticked formats.

!!! note "'Dark' here is a figure option, not a theme"
    The **dark** background applies only to exported figures and is
    independent of the app's own light/dark theme toggle — exports are
    theme-invariant, so the same figure comes out whichever theme the
    interface is using.

## Where files go

If you granted the app a working folder, saves and exports land there;
otherwise they download through the browser. Either way the files are
ordinary `.dvma` / `.mat` / `.csv` / `.png` / `.pdf` you can move, share
or reopen.

## Opening files

Load data from the header's **Load Data** button. The web logger opens:

- **`.dvma`** — read directly (no engine needed);
- legacy **`.npy`** pickle files from pydvma ≤ 1.4.0 — decoded by the
  pyodide engine; and
- **`.mat`** files from the original JW logger — spectral files
  (spectra / transfer functions, with coherence columns recognised
  automatically) *and* time captures.

Format is detected from the file's content, not its extension. See
[The `.dvma` file format](dvma-format.md) and
[From the Qt logger](migration.md#files-carry-over).

**Loading adds; it does not replace.** With data already present,
loading another file appends its sets alongside the current ones — the
tray and legend show everything together (the old logger's
"Add on load"), and **Save Dataset** writes the composite to one
`.dvma`. To drop a set, use its tray **×**; to start from scratch,
reload the page. One caveat: a fitted modal model inside an *appended*
file is ignored — the session keeps its own live fit.
