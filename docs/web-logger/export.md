# Saving and exporting

The **Export** stage saves your session and writes files for other
tools:

- **Save Dataset** writes a `.dvma` file, which reopens with your data,
  calibration and results as you left them;
- **Export Matlab** and **Export CSV** write the same session for
  MATLAB, spreadsheets and other tools, and reopen like a `.dvma`; and
- **Export**, with the figure options, writes the current plot as a PNG
  or PDF.

**Save Dataset** and **Save Figure** are also in the header. **Save
Figure** opens this stage. **Load Data**, also in the header, opens
files.

## What each output holds

The three files hold the same information: an export is the document
**Save Dataset** writes, laid out for another tool.

| | `.dvma`, `.mat` and `.csv` |
| - | ------- |
| Time series | yes |
| FFT and transfer functions you have computed, with coherence | yes |
| Power, PSD and CSD you computed in the app | no |
| Sonograms | if you choose |
| Modal fit | yes |
| Channel labels and analysis settings | yes |
| Calibration factors and units | yes |
| Opens again in the web logger and in Python | yes |

Spectra and transfer functions are included only if you have computed
them, so press **Calc FFT** or **Calc TF** first. The table describes
what the app writes; a file made from Python can also hold
cross-spectra (an imported Vibration Apps file does).

**Export Matlab** and **Export CSV** write the values as recorded, not
as plotted, so they differ from the screen by each channel's
[calibration factor](calibration.md). Each measurement carries its own
factors and units beside its values, as in a `.dvma`.

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

**Export Matlab** and **Export CSV** each write one file,
`logged_data.mat` or `logged_data.csv`, holding what **Save Dataset**
would: your results are materialised first and, if you computed a
sonogram, you are asked whether to include it, exactly as for a save
([above](#your-results-are-saved-too)). The **▾** beside each exports a
chosen subset. **Load Data** reads either file back. The first export in
the browser can take a few seconds while the analysis engine starts.

Every measurement keeps its own axis, at its own sample rate and length;
nothing is interpolated. The values are raw: multiply by the item's
calibration factors for engineering units.

### Export Matlab

The `.mat` file (format `pydvma-mat 1`) holds three variables:

| Variable | Contents |
| -------- | -------- |
| `pydvma_items` | a cell array with one struct per item: `kind`, `test_name`, `units`, `fs`, `timestamp`, `channel_cal_factors`, and each array under its own name (`time_axis`, `time_data`, `freq_axis`, `tf_data`, `tf_coherence`, `Pxy`, `sono_data`, `M`, ...) |
| `pydvma_manifest` | every item's metadata and settings, as JSON text |
| `pydvma_format` | `'pydvma-mat 1'` |

In MATLAB:

```matlab
d = load('logged_data.mat');
d.pydvma_items{1}.kind           % 'TimeData'
t = d.pydvma_items{1}.time_axis;
x = d.pydvma_items{1}.time_data; % one column per channel, raw
meta = jsondecode(d.pydvma_manifest);
```

Files written by pydvma 2.6 and earlier held `time_data_all`,
`tf_data_all` and so on, every measurement interpolated onto one common
axis. They cannot be read back.

### Export CSV

The `.csv` file (format `pydvma-csv 1`) is one text file with a table
for each item:

```
# pydvma dataset (pydvma-csv 1)
# Written by pydvma 2.6.0. Load it back with pydvma.load_data, or Load Data in the web app.
# Values are RAW, calibration NOT applied: multiply a column by its item's channel_cal_factors.
# Each '# table' line below starts one table: its column names, then its rows.
# manifest: {"format": "dvma-dataset", ... }
# table 0: item 0, TimeData 'impulse'; units N, m/s2; cal_factors 1, 10 (time_axis, time_data)
time_axis,time_data[0],time_data[1]
0,0.0012,-0.0003
...
# table 1: item 1, TfData 'impulse'; units (m/s2)/N; cal_factors 10 (freq_axis, tf_data, tf_coherence)
freq_axis,tf_data[0].re,tf_data[0].im,tf_coherence[0]
...
```

- Each table's rows run along the item's axis. Complex values are
  `.re` and `.im` column pairs, and a cross-spectrum's or sonogram's
  extra dimensions spread across numbered columns (`Pxy[0][1].re`).
- Numbers are written as the shortest text that reads back to the same
  value, so nothing is lost.
- The `# manifest:` line holds the metadata and settings that let the
  file load back. A spreadsheet that re-saves the file and changes a
  table's size makes it unreadable; the error says which table.
- To read one table with pandas, give it the lines between its
  `# table` line and the next:

    ```python
    import io, pandas as pd
    lines = open('logged_data.csv').read().split('\n')
    start = next(i for i, l in enumerate(lines) if l.startswith('# table 1:'))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith('# table')), len(lines))
    tf = pd.read_csv(io.StringIO('\n'.join(lines[start + 1:end])))
    ```

Files written by pydvma 2.6 and earlier (one file per kind, starting
`# pydvma export: RAW data`) cannot be read back.

**From Python**, `dvma.export_to_matlab(data, filename='data')` and
`dvma.export_to_csv(data, filename='data')` write the same files, from
a whole dataset or one list (`data.tf_data_list`). See
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
- **`.mat`** and **`.csv`** files written by **Export Matlab** and
  **Export CSV**, or by Python's `export_to_matlab` and `export_to_csv`;
- older **`.npy`** files saved by pydvma 1.4.0 and earlier (see
  [older files](dvma-format.md#older-npy-files));
- **`.mat`** files from the original JW logger: spectra and transfer
  functions, with coherence columns recognised automatically, and time
  captures (see [From the Qt logger](migration.md#files-carry-over)); and
- **`.csv`** files saved by the Vibration Apps' **Transfer function**
  app (3C6): one set per measurement, holding its transfer function (H1
  with its coherence), its cross-spectrum and, when the file has it, its
  time data (see
  [Import Vibration Apps transfer functions](../user-guide/import-export.md#import-vibration-apps-transfer-functions)).

**Loading adds; it does not replace.** With data already loaded, a new
file's measurements appear alongside the current ones, in the tray and
the legend. **Save Dataset** then writes them all to one `.dvma`. To
drop a measurement, press its tray **×**. To start again from nothing,
reload the page. A modal fit inside an added file is ignored, and the
session keeps its own fit.
