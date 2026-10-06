# Import and Export

Save and load whole datasets in pydvma's own format, and export the
arrays to MATLAB, CSV or pandas.

Give each function a filename, either as `filename=` (as below) or
positionally, as in `dvma.load_data('my_test.dvma')`. It is required:
pydvma has no file dialog.

The examples start from a synthetic impulse test:

```python
import pydvma as dvma

data = dvma.create_test_impulse_data(noise_level=0.01)
data.calculate_fft_set(window='hann')
data.calculate_tf_set(ch_in=0, window='hann', N_frames=4)
```

## Save and Load a DataSet (native format)

```python
dvma.save_data(data, filename='my_test.dvma', overwrite_without_prompt=True)
data = dvma.load_data(filename='my_test.dvma')
```

`save_data` adds `.dvma` unless the name already ends in `.dvma` or
`.npy`. If the file already exists it asks before overwriting, unless you
pass `overwrite_without_prompt=True`.

`.dvma` is a zip of plain arrays and JSON (see the
[file layout](../web-logger/dvma-format.md)). Loading one runs no code, so
it is safe to share, and the web logger opens it too. `load_data` recognises
a `.dvma` file by its content, so a renamed file still loads. It also opens
`.mat` files from Jim Woodhouse's MATLAB logger (see below) and `.npy`
pickle files saved by pydvma 1.4 and earlier. Only open a `.npy` file you
or your lab made, because unpickling can run code. A filename ending in
`.npy` makes `save_data` write that pickle format instead.

To save part of a dataset, name the measurements (by position in
`time_data_list`). The file gets those measurements and everything
computed from them:

```python
dvma.save_data(data, filename='first.dvma', sets=[0], overwrite_without_prompt=True)

subset = data.subset([0])     # the same selection, kept in memory (shared, not copied)
```

## Export to MATLAB

```python
dvma.export_to_matlab(data, filename='my_test.mat', overwrite_without_prompt=True)
```

The `.mat` file holds the time, frequency and transfer function arrays.
Values are the raw stored numbers, with no calibration applied; the
calibration travels with them as `time_cal_factors`, `time_units` and the
`freq_` and `tf_` equivalents. See
[What each output holds](../web-logger/export.md#what-each-output-holds)
for the full list of variables.

`dvma.export_to_matlab_jwlogger(data, filename='my_test.mat')` writes the
layout of Jim Woodhouse's MATLAB logger instead, and
`dvma.import_from_matlab_jwlogger` reads it back. That layout has one
spectral block and one sample rate: transfer functions are written in
preference to FFTs, and in a file holding time data too the spectra are
put on the time data's frequency grid.

## Export to CSV

Each call writes one file for one kind of data:

```python
dvma.export_to_csv(data.time_data_list, filename='my_time.csv', overwrite_without_prompt=True)
dvma.export_to_csv(data.freq_data_list, filename='my_freq.csv', overwrite_without_prompt=True)
dvma.export_to_csv(data.tf_data_list, filename='my_tf.csv', overwrite_without_prompt=True)
```

The file starts with `#` comment lines giving each column's calibration
factor and unit, and the values are raw. In the frequency and transfer
function files every cell is a complex number, so read them with
`np.loadtxt('my_tf.csv', delimiter=',', dtype=complex)`. The
[export page](../web-logger/export.md#export-csv) describes the layout.

## Import JW logger files

`load_data` reads `.mat` files written by Jim Woodhouse's MATLAB logger,
for both time captures and transfer function files:

```python
jw_data = dvma.load_data(filename='my_jw_capture.mat')
```

The `.mat` files that `export_to_matlab` writes are export-only: loading
one stops with an error saying so. Keep the `.dvma` file for anything you
want to reopen. `dvma.import_from_matlab_jwlogger(filename=...)` does the
same import directly.

For a transfer function file the frequency axis is built from the file's
`npts` (FFT length) and `freq` (sample rate): `npts/2 + 1` bins, spaced
`freq/npts`, up to `freq/2`. Coherence traces stored as extra columns
(real values between 0 and 1) are attached as the transfer function's
`tf_coherence`, not imported as data channels, so they never enter a
modal fit. JW admittance measurements are velocity over force, so fit them
with `measurement_type='vel'`.

## Import Vibration Apps transfer functions

The **Transfer function** app in the
[Vibration Apps](https://torebutlin.github.io/vibration_apps/apps/frf/)
(used in 3C6) measures speaker to microphone in a browser and saves every
measurement it holds as one CSV, with each measurement's time data too
when its "time data" box is ticked. `load_data` recognises that file by
its first line, whatever it is named:

```python
va = dvma.load_data(filename='measurements.csv')
for tf in va.tf_data_list:
    print(tf.test_name, len(tf.freq_axis))
```

Each measurement, named `m<no> <name>` with the app's card number, gives:

- a **`TimeData`**, when the file has its time data (never for a stepped
  sine): channel 0 is what was played, channel 1 the microphone, already
  lined up for the loop delay as the app analysed them. pydvma's own
  analysis can be run on it and compared with the app's result.
- a **`TfData`**: H1 on the measurement's own frequencies (a noise test's
  FFT bins within the band; a stepped sine's points, not evenly spaced),
  uncalibrated (microphone full scale per speaker full scale), with the
  loop delay already out of the phase. Its `tf_coherence` is None for a
  result of one frame, where the app leaves it empty (it is 1 by
  definition). The file's H2 and H_power columns are not imported.
- a **`CrossSpecData`**, from the app's auto-spectra (`Gxx`, `Gyy`) with
  H1 and the coherence, in pydvma's convention: a power spectrum, with
  `enbw_hz` to turn it into a density (the app's numbers).

The three share one `id_link`, so the web app shows each measurement as
one set. `timestamp` is when the measurement was made (UTC), and the TF's
`source_settings['vibration_apps']` keeps every setting the app wrote
plus its notes (test signal, loop delay, quality figures), so they
survive saving as `.dvma`.

An H1 with no phase anywhere (a magnitude from the powers alone) gets
`(|H| only, no phase)` added to its name and a warning: its phase and any
modal fit to it mean nothing. A measurement the app was hiding when it
saved is imported all the same. Any other CSV, including one written by
`export_to_csv`, stops with an error.
`dvma.import_from_vibration_apps_csv(filename=...)` does the same import
directly.

Each measurement has its own frequency axis. They can still be fitted
together (one list): each is fitted on its own points, with the poles
shared; see
[Fitting one mode across channels](modal-analysis.md#fitting-one-mode-across-channels).
Fit them one at a time when the poles should differ (a measurement with
an added mass, say).

## Working with many files

Load each file and analyse it in a loop:

```python
import os

folder = 'measurements'
results = []
for name in sorted(os.listdir(folder)):
    if not name.endswith('.dvma'):
        continue
    dataset = dvma.load_data(filename=os.path.join(folder, name))
    time_data = dataset.time_data_list[0]          # assumes two or more channels
    results.append({
        'file': name,
        'freq_data': dvma.calculate_fft(time_data, window='hann'),
        'tf_data': dvma.calculate_tf(time_data, ch_in=0, window='hann', N_frames=4),
    })
```

## Into pandas

pandas is not a pydvma dependency, but a capture converts easily:

```python
import pandas as pd

time_data = data.time_data_list[0]
frame = pd.DataFrame(
    time_data.time_data * time_data.channel_cal_factors,    # engineering units
    index=pd.Index(time_data.time_axis, name='time (s)'),
    columns=[f'ch{i}' for i in range(time_data.time_data.shape[1])],
)
print(frame.describe())
```

## Figures

`dvma.save_fig` writes a figure as PNG and PDF. See
[Saving figures](plotting.md#saving-figures).
