# Saving and exporting

The **Export** stage saves your session and writes files for other
tools:

- **Save Dataset** writes a `.dvma` file, which reopens with your data,
  calibration and results as you left them;
- **Export Matlab** and **Export CSV** write your data for use
  elsewhere; and
- **Export**, with the figure options, writes the current plot as a PNG
  or PDF.

**Save Dataset** and **Save Figure** are also in the header. **Save
Figure** opens this stage. **Load Data**, also in the header, opens
files.

## What each output holds

| | `.dvma` | `.mat` | `.csv` |
| - | ------- | ------ | ------ |
| Time series | yes | yes | yes |
| FFT and transfer functions you have computed | yes | yes | yes |
| Coherence | yes | no | no |
| Power, PSD and CSD | no | no | no |
| Sonograms | if you choose | no | no |
| Modal fit | yes | no | no |
| Channel labels and analysis settings | yes | no | no |
| Calibration factors and units | yes | no | in a `#` header |
| Opens again in the web logger | yes | no | no |

Spectra and transfer functions are included only if you have computed
them, so press **Calc FFT** or **Calc TF** first. The table describes
what the app writes; a `.dvma` file made from Python can also hold
cross-spectra.

**Export Matlab** and **Export CSV** write the values as recorded, not
as plotted, so they differ from the screen by each channel's
[calibration factor](calibration.md). To keep the factors in a file, use
CSV, which records them in its header, or `.dvma`, which stores them
with the data. The app's `.mat` does not carry them. Python's
`export_to_matlab` does, as `time_cal_factors` and `time_units`, with
`freq_` and `tf_` equivalents.

## Save the session

1. Press **Save Dataset**.
2. Type a name when asked. The app suggests `pydvma_` followed by the
   date and time, and adds `.dvma` if you leave it off.

The file holds every measurement with its calibration, units, channel
labels and any modal fit. It contains no executable code, so it is safe
to share. See [The `.dvma` file format](dvma-format.md).

### Your results are saved too

Any **FFT** and **transfer function** on screen is saved with the
measurement it came from, coherence included, along with the settings
that made it (window, averaging, channel choice). Reopening the file
draws those views straight away, with no calculation. In Python they
load as well:

```python
data = dvma.load_data(filename='session.dvma')
data.freq_data_list      # the spectra you computed in the app
data.tf_data_list        # transfer functions, with coherence
```

Saving again updates the results in place, so a measurement never
collects duplicates.

**Power**, **PSD** and **CSD** results, and transfer functions averaged
**across sets**, are not stored. Recompute them after loading.

#### "⚠ source changed"

If a measurement's time data changes after its results were saved (you
resampled it, cleaned an impulse, or edited it in a notebook), the saved
spectrum no longer matches its samples. When you open the file, the
measurement's tray card shows **⚠ source changed**. Click it to
recompute the affected views. Results saved without a check are never
flagged.

### Sonograms

A sonogram is saved only if you say so, because saving it means running
the transform again, which is slower and makes a bigger file. If you
computed a sonogram this session, **Save Dataset** asks **Include
sonogram data?**:

- **This channel** stores the channel you are looking at (the default);
- **All channels** stores every channel of that measurement; and
- **Don't include** skips it. Sonograms already in the session stay.

You never see the question unless you computed a sonogram. Once you
answer, an unchanged session doesn't ask again.

### Choose which measurements to save

**Save Dataset**, **Export Matlab** and **Export CSV** each have a **▾**
button beside them. It opens a list of your measurements, with badges
for what each holds (time, fft, tf, fit), and saves or exports only the
ticked ones.

A partial save also includes everything computed from the chosen
measurements: their spectra, transfer functions, and any fit that
involves them. The list starts with everything ticked each time, and
doesn't depend on which lines are shown or hidden on the plot. A partial
save leaves autosave alone, because it isn't the whole session.

In Python, `dvma.save_data(data, filename=..., sets=[3])` saves the same
subset ([example](running-locally.md#5-save-and-finish)).

### Autosave and restore

The **Autosave** switch on the Export stage is on by default. Two
seconds after each change it writes your session to:

- an `autosave.dvma` file in your working folder, if you have chosen
  one ([below](#where-files-go)); or
- the browser's own storage, otherwise. The next time you open the app
  it offers **Restore last session?**.

A full **Save Dataset** clears the autosave. Turn the switch off to stop
the background writes.

Served locally, the server also keeps your session, and offers it back
after a closed tab or a crash. See
[Running locally](running-locally.md#your-session-is-kept-safe).

## Export data

### Export Matlab

**Export Matlab** writes `logged_data.mat` with these variables, one
column per channel, with every measurement's columns side by side:

| Variable | Contents |
| -------- | -------- |
| `time_axis_all`, `time_data_all` | time in seconds, and the time series |
| `freq_axis_all`, `freq_data_all` | frequency in Hz, and the complex FFTs |
| `tf_axis_all`, `tf_data_all` | frequency in Hz, and the complex transfer functions |

Measurements with different sample rates or lengths are interpolated
onto one common axis: the finest resolution and the widest span, with
zeros beyond the end of a shorter record. A kind you have not computed
is left out. The first export in the browser can take a few seconds
while the analysis engine starts.

### Export CSV

**Export CSV** writes one file for each kind of data present:
`logged_data-time.csv`, `logged_data-freq.csv` and `logged_data-tf.csv`.

- The first column is the axis (seconds, or hertz), then one column per
  channel, with every measurement's columns side by side. All
  measurements of a kind must have the same number of samples, or the
  export stops with an error.
- Time values are real numbers. In the frequency and transfer function
  files every cell, the axis included, is a complex number written as
  `(re+imj)`. Read them with `np.loadtxt(file, delimiter=',', dtype=complex)`.
- The file starts with `#` comment lines giving each data column's
  calibration factor and unit. To get engineering units, multiply data
  column *k* (counting from 0 after the axis column) by `cal_factors[k]`.
  `np.loadtxt`, `np.genfromtxt` and `pandas.read_csv(..., comment='#')`
  skip these lines:

    ```
    # pydvma export: RAW data, calibration NOT applied.
    # Column 1 is the shared axis (s); the rest are data columns.
    # Multiply data column k by cal_factors[k] for engineering units.
    # cal_factors: 10,0.5
    # units: m/s2,N
    ```

  A channel with no unit shows `-`. A transfer function column has the
  ratio of its output and input factors, and a unit such as `(m/s2)/N`.

**From Python**, use `dvma.export_to_matlab(dataset, filename='data')`
and `dvma.export_to_csv(dataset.time_data_list, filename='time')`. For
the same data the CSV is identical to the app's. See
[Import and export](../user-guide/import-export.md).

## Export figures

The **Export** stage writes the plot you are looking at. Set:

- **figure format**: **PNG** (a raster image at three times the on-screen
  size, ticked by default) and **PDF** (vector). Tick both to write both;
- **background**: **white** (the default), **transparent** or **dark**.
  **Dark** recolours the axes and labels for a dark background and keeps
  your data lines, which suits slides. It has no connection with the
  app's own light or dark theme, and a figure looks the same in either;
  and
- **filename**: by default `pydvma_figure_` followed by the date and
  time.

Then press **Export**. The figure shows what the plot shows: the legend,
when it is on, at its place on screen and without hidden lines; the
coherence overlay and its right-hand axis, when they are on; both panes
of a Bode plot; and the heat map of a sonogram.

## Where files go

The folder button in the header names your working folder, or reads
**Downloads**. Click it to choose a folder. In Chrome, Edge and other
Chromium-based browsers the app then writes saves, exports, figures and
the autosave into that folder. Other browsers, or no folder chosen,
download each file through the browser instead.

## Opening files

Press **Load Data** in the header. The web logger opens:

- **`.dvma`** files, read directly;
- older **`.npy`** files saved by pydvma 1.4.0 and earlier (see
  [older files](dvma-format.md#older-npy-files)); and
- **`.mat`** files from the original JW logger: spectra and transfer
  functions, with coherence columns recognised automatically, and time
  captures. See [From the Qt logger](migration.md#files-carry-over).

The `.mat` and `.csv` files written by **Export Matlab** and **Export
CSV** cannot be reopened. Use `.dvma` to keep a session you want to
come back to.

**Loading adds; it does not replace.** With data already loaded, a new
file's measurements appear alongside the current ones, in the tray and
the legend. **Save Dataset** then writes them all to one `.dvma`. To
drop a measurement, press its tray **×**. To start again from nothing,
reload the page. A modal fit inside an added file is ignored, and the
session keeps its own fit.
