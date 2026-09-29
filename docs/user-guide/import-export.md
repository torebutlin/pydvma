# Import and Export

Save and load whole datasets in pydvma's own format, and export the
arrays to MATLAB, CSV or pandas.

Always pass `filename=` to these functions. Without one they try to open
a file dialog, which needs `pip install qtpy` plus a Qt binding such as
PyQt5. pydvma doesn't install either.

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
layout of Jim Woodhouse's MATLAB logger instead.

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

This importer cannot read the `.mat` files that `export_to_matlab` writes.
Keep the `.dvma` file for anything you want to reopen.

For a transfer function file the frequency axis is built from the file's
`npts` (FFT length) and `freq` (sample rate): `npts/2 + 1` bins, spaced
`freq/npts`, up to `freq/2`. Coherence traces stored as extra columns
(real values between 0 and 1) are attached as the transfer function's
`tf_coherence`, not imported as data channels, so they never enter a
modal fit. JW admittance measurements are velocity over force, so fit them
with `measurement_type='vel'`.

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
