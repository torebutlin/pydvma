# Python Basics

The ideas behind the Python interface: where your data lives, how
settings work, and how to save it. The [Quick Start](quickstart.md)
shows them in use; the [Python Interface](../user-guide/acquisition.md)
guides go into each area in depth.

## The DataSet

Every recording, loaded file and `session.data` is a **`DataSet`**: a
set of lists, one per kind of data.

```python
>>> data = dvma.create_test_impulse_data()
>>> data
<DataSet> class:

          time_data_list: [<TimeData>]
          freq_data_list: []
    cross_spec_data_list: []
            tf_data_list: []
         modal_data_list: []
          sono_data_list: []
          meta_data_list: []
```

Each capture adds one `TimeData` to `time_data_list`, and the analyses
fill the other lists:

| Object | Made by | Main arrays |
| ------ | ------- | ----------- |
| `TimeData` | recording, `log_data` | `time_axis` (s); `time_data`, shape (samples, channels) |
| `FreqData` | `calculate_fft` | `freq_axis` (Hz); `freq_data`, complex, (frequencies, channels) |
| `TfData` | `calculate_tf` | `freq_axis`; `tf_data`, complex, (frequencies, outputs); `tf_coherence`, same shape |
| `CrossSpecData` | `calculate_cross_spectrum_matrix` | cross-spectra and coherence between every channel pair |
| `SonoData` | `calculate_sonogram` | `freq_axis`, `time_axis`; `sono_data`, (frequencies, times, channels) |
| `ModalData` | modal fitting | natural frequencies `fn`, damping `zn`, modal constants `an` |

Every object also carries the `settings` it was recorded with, a
`test_name`, and per-channel `units` and `channel_cal_factors`
(see [calibration](#units-and-calibration) below).

```python
td = data.time_data_list[0]
t, y = td.time_axis, td.time_data     # y[:, 0] is the first channel
fs = td.settings.fs
```

## Two ways to compute

**On the whole DataSet.** The `*_set` methods process every `TimeData`
in the set and store the results in the DataSet, replacing whatever that
list held before. This is the quickest route and what the plotting
methods expect:

```python
data.calculate_fft_set(window='hann')           # fills data.freq_data_list
data.calculate_tf_set(ch_in=0, window='hann')   # fills data.tf_data_list
data.plot_freq_data()
data.plot_tf_data()
```

**On one object.** The functions in `dvma.` take a single `TimeData` and
return a new result without touching the DataSet, for when you want
control over what goes where:

```python
freq = dvma.calculate_fft(td, window='hann')
tf = dvma.calculate_tf(td, ch_in=0, window='hann', N_frames=8, overlap=0.5)
```

The [Data Analysis guide](../user-guide/analysis.md) covers windows,
averaging, time ranges, integration and scaling.

## Settings

`MySettings` holds everything about how to record: channels, sample
rate, duration, device, pretrigger and output. **Pass values as keyword
arguments when you create it:**

```python
settings = dvma.MySettings(channels=2, fs=8000, stored_time=2.0,
                           pretrig_samples=100)
```

!!! warning "Don't change settings by assignment"
    Some settings are worked out from others when `MySettings` is
    created. Assigning afterwards (`settings.fs = 10000`) changes only
    that one value and leaves the others stale; for example, the output
    sample rate stays at the old `fs`. Make a new `MySettings` instead.

The settings you will use most:

| Setting | Meaning | Default |
| ------- | ------- | ------- |
| `channels` | number of input channels | `2` |
| `fs` | sample rate, Hz | `44100` |
| `stored_time` | length of each recording, s | `2` |
| `device_driver` | `'soundcard'` or `'nidaq'` | `'soundcard'` |
| `device` | device name, e.g. `'Scarlett 2i2'` (or `device_index`); `None` means the default input | `None` |
| `pretrig_samples` | samples kept from before the trigger, at most `chunk_size` (default 100); `None` records immediately | `None` |
| `pretrig_threshold`, `pretrig_channel` | trigger level and channel | `0.05`, `0` |
| `output_channels` | number of output channels, used when you pass an `output=` signal to `log_data` | `1` |

`dvma.list_available_devices()` shows what you can put in `device`, and
`dvma.suggest_ni_settings(index)` returns safe settings for an NI device.
The [Data Acquisition guide](../user-guide/acquisition.md) covers the
rest, including NI voltage ranges and IEPE sensors.

## Saving and loading

```python
dvma.save_data(data, filename='my_test.dvma')
data = dvma.load_data(filename='my_test.dvma')
```

Always give a filename, as `filename=` or as the first argument after the
data (`dvma.load_data('my_test.dvma')` works too). Without one these
functions open a file dialog, which needs a Qt installation that pydvma no
longer provides, and without Qt they stop with an error asking for a
filename.

`.dvma` is pydvma's own format: a zip of plain arrays and JSON that
opens in the browser app, in any Python with pydvma, and in other tools.
`load_data` also opens `.npy` files saved by pydvma 1.4 and earlier (but
only open those if you trust where they came from, since the old format
can run code when loaded) and `.mat` files from the older MATLAB logger.

To use your data elsewhere:

```python
dvma.export_to_matlab(data, filename='my_test.mat')
dvma.export_to_csv(data.time_data_list, filename='my_test.csv')
```

See [Import and Export](../user-guide/import-export.md) for what each
format contains.

## Units and calibration

Recorded data is stored in **volts** from NI hardware and from
soundcards whose full scale pydvma knows. For other soundcards it is in
**full-scale units**, where ±1 is the loudest signal the input accepts.
Calibration never changes the stored numbers: each channel's
`channel_cal_factors` is a multiplier applied when plotting, and `units`
names the result (for example `'m/s²'`). See
[Calibration & Units](../web-logger/calibration.md).
