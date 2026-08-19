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

### What Save writes: data *with* its processing

Saving stores the **results you computed**, not just the raw captures.
Any **FFT** and **transfer function** on screen is written into the file
as a real `FreqData` / `TfData` item (coherence included), linked to the
measurement it came from. Reopening the file draws those views
immediately — no engine, no waiting, and the same items load in Python:

```python
data = dvma.load_data('session.dvma')
data.freq_data_list      # the spectra you computed in the app
data.tf_data_list        # transfer functions, with coherence
```

Each stored result also records **how it was made**: the analysis
settings in force (window, averaging, channel choice), and a short
signature of the **source samples** it was computed from.

Re-saving updates the results in place — one FFT and one TF per
measurement, however many times you save.

#### "⚠ source changed"

The signature is what lets the app tell an intact result from a stale
one. If the time data changes *after* a result was stored — you
resampled it, cleaned an impulse, or edited the samples in a notebook and
pushed them back — the stored spectrum no longer belongs to the samples
sitting beside it. On load, that measurement's tray card shows a
**⚠ source changed** badge; click it to recompute the affected views (the
badge clears), or leave it and the file keeps what it always had. A file
saved by an older pydvma carries no signature and is never flagged —
absence of a signature is not evidence of staleness.

#### Sonograms are asked for

A sonogram is **not** stored automatically. The view is one channel's
picture; the file wants the full complex sonogram, so storing it means
running the transform again — slower to save and a bigger file. If you
computed a sonogram this session, Save asks **Include sonogram data?**:

- **This channel** — store the channel you are looking at (the default);
- **All channels** — store every channel of that measurement;
- **Don't include** — skip it. Sonograms already in the document stay
  there; this only declines the new one.

Never opened the Sonogram stage? You will never see the dialog. Answer it
once and an unchanged session will not ask again on the next save.

!!! note "Not everything is materialised yet"
    **Power spectral densities and cross-spectra** are not written as
    stored results — recompute them after loading. Neither is an
    **ensemble ("across sets") transfer function**: it is derived from
    several measurements at once, and a result that named only one of them
    as its source could not honestly be checked for staleness. Both are
    on the follow-up list.

### Choose which measurements to save

Each of **Save Dataset**, **Export Matlab** and **Export CSV** is a split
control: the button itself always means *everything*, and the **▾** beside
it opens **Choose sets…**, a tick list of your measurements (with badges
showing what each carries — time · fft · tf · fit).

A subset save writes the chosen measurements *and* everything hanging off
them — their spectra, transfer functions and any modal fit that spans
them — and nothing else. The pick applies to that one save: it starts
all-ticked every time, is never remembered, and is deliberately unrelated
to what is shown, faded or hidden on the plot. A subset save also does not
clear the autosave, since it is not the whole session.

One thing a subset save does *not* narrow: results it materialises join
your **live session** as well as the file. Say yes to the sonogram prompt
during a subset save and that sonogram is now part of the session too —
it will be in the next full save, and it is what a restore or
`session.data` brings back. Only the file is filtered.

The same split exists in Python:

```python
# one measurement plus everything derived from it
dvma.save_data(dataset, filename='just-4.dvma', sets=[3])
small = dataset.subset([0, 3])       # or take the subset in memory
```

### Autosave and session restore

The **Autosave** switch (on by default) writes your session to browser
storage a couple of seconds after every change:

- If the app has access to a working folder, it keeps an `autosave.dvma`
  there.
- Otherwise it stores the session in the browser (IndexedDB) and offers
  **Restore last session?** the next time you open the app.

A clean **Save Dataset** clears the autosave. Turn Autosave off to stop
the background writes.

When the app is served by `pydvma-serve`, each autosave is *also* posted
to the server, which keeps the authoritative session — so the restore
offer on the next open comes from there rather than from browser storage,
and a session survives the tab closing or the serve process crashing. See
[the session journal](index.md#the-session-lives-in-pydvma-serve).

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
