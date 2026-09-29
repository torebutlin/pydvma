# Worked Examples

Worked examples for common measurements.

## Complete workflow: acquire → analyse → plot

A full session from a notebook or script: acquire (with and without a
played output, using either the built-in generator or a hand-built NumPy
array), compute spectra and transfer functions, then plot. Every call
below is part of the public API.

### 1. Imports and settings

```python
import numpy as np
import pydvma as dvma

settings = dvma.MySettings(
    channels=2,          # ch0 = reference/input, ch1 = response/output
    fs=10000,
    stored_time=1.0,
    output_channels=1,   # one output channel (used when you play an output)
)
# device_driver defaults to 'soundcard'; use 'nidaq' for an NI device.
# Playing an output needs an output-capable device (soundcard output or NI AO).
```

### 2. Acquire: three ways

Each `log_data` call returns a fresh `DataSet` holding one `TimeData`
(shape `(n_samples, channels)`) in `data.time_data_list`.

```python
# (a) plain capture, no excitation
data = dvma.log_data(settings, test_name='plain')

# (b) drive the built-in generator (band-limited Gaussian noise).
#     signal_generator returns (t, output); output is (N, output_channels), in volts.
t, output = dvma.signal_generator(settings, sig='gaussian',
                                  T=settings.stored_time, amplitude=0.1,
                                  f=[20, 2000])          # band-pass corners (Hz)
data = dvma.log_data(settings, output=output, test_name='driven_noise')

# (c) drive a custom NumPy waveform (multi-tone), in volts.
#     Format: 2-D (N_samples, output_channels), sampled at settings.output_fs,
#     within ±settings.output_vmax(). See the acquisition guide for the
#     full contract: a raw array gets no automatic fade or safety clamp.
fs_out = settings.output_fs                              # = settings.fs unless overridden
tt = np.arange(0, settings.stored_time, 1 / fs_out)
drive = 0.2 * np.sin(2 * np.pi * np.outer(tt, [110.0, 370.0, 990.0])).sum(axis=1)
drive = np.clip(drive, -settings.output_vmax(), settings.output_vmax())
output = drive[:, None]                                  # (N, 1)
data = dvma.log_data(settings, output=output, test_name='driven_multitone')
```

The drive is not recorded automatically. Wire it into input 0, or set
`use_output_as_ch0=True` in `MySettings` to record it as channel 0. To
average several repeats, see [Impact test with averaging](#impact-test-with-averaging).

### 3. Spectra, power spectra and transfer functions

`DataSet` has `*_set` methods that run an analysis over every `TimeData`
in `time_data_list` and store the results on the dataset, replacing
whatever that list held before:

```python
# Linear spectra (one-sided complex FFT) -> data.freq_data_list
data.calculate_fft_set(window='hann')

# Cross-spectrum matrix (Welch) -> data.cross_spec_data_list.
# Pxy[i,i] is the channel-i power spectrum (scaling='spectrum', V^2); divide
# it by the item's enbw_hz for a PSD (V^2/Hz). Pxy[i,j] is the cross-spectrum,
# Cxy[i,j] the coherence in [0, 1].
data.calculate_cross_spectrum_matrix_set(window='hann', N_frames=8, overlap=0.5)

# Transfer functions H = Pxy[in,out]/Pxy[in,in], one column per non-input
# channel -> data.tf_data_list. ch_in selects the reference channel.
data.calculate_tf_set(ch_in=0, window='hann', N_frames=8, overlap=0.5)
```

For an ensemble (a `time_data_list` of several captures) average across
the set instead. These give a single averaged result:

```python
data.calculate_cross_spectra_averaged(window='hann')      # 1-item cross_spec_data_list
data.calculate_tf_averaged(ch_in=0, window='hann')        # 1-item tf_data_list
```

!!! note "Two different frequency axes"
    `calculate_fft_set` transforms the whole block, so its axis has
    `n_samples//2 + 1` bins. The cross-spectrum and TF use Welch
    segmenting (`N_frames`, `overlap`), so their `freq_axis` is shorter,
    and it is the one to use when plotting `Pxy`, `Cxy` or `tf_data`.

### 4. Plot

The built-in plotters open one matplotlib figure per data type and apply
`channel_cal_factors` automatically:

```python
data.plot_time_data()
data.plot_freq_data()      # needs calculate_fft_set() first
data.plot_tf_data()        # magnitude (dB) and coherence; needs calculate_tf_set()
```

Cross-spectra have no built-in plot. Plot `Pxy` and `Cxy` yourself, as in
[Power spectrum, PSD and CSD](../user-guide/plotting.md#power-spectrum-psd-and-csd).
[Plotting and Visualization](../user-guide/plotting.md) also covers the
options of the built-in plots and matplotlib recipes for every kind of
data.

## A notebook session: `dvma.launch`

The flow above records from the notebook. To record point-and-click in
the web logger and analyse in Python instead, start it with
`session = dvma.launch(settings)` and pull the captures with
`session.data`. [Running Locally](../web-logger/running-locally.md#from-python-dvmalaunch)
walks through the whole cycle.

## Impact test with averaging

Record several hammer hits and average their transfer function. The
recorder waits for each hit (`log_data` gives up after `pretrig_timeout`,
20 s by default) and keeps 1000 samples from before it:

```python
import numpy as np
import pydvma as dvma

settings = dvma.MySettings(
    channels=2,              # channel 0 is the hammer force, channel 1 the response
    fs=10000,
    stored_time=1.0,
    chunk_size=1000,         # at least pretrig_samples
    pretrig_samples=1000,    # samples kept from before the trigger
    pretrig_threshold=0.1,   # trigger level on channel 0: above the noise, below a hit
)

data = dvma.DataSet()
n_impacts = 5
for i in range(n_impacts):
    input(f"Press Enter, then hit {i + 1}/{n_impacts}...")
    hit = dvma.log_data(settings, test_name=f"impact_{i}")
    data.add_to_dataset(hit.time_data_list[0])

# Averaged transfer function. Use no window for hits that die away within the record.
tf_avg = dvma.calculate_tf_averaged(data.time_data_list, ch_in=0, window=None)

print(f"Averaged {len(data.time_data_list)} hits")
print(f"Average coherence: {np.mean(tf_avg.tf_coherence):.3f}")
```

To keep the average with the recordings, so you can plot and save it, let
the dataset store it:

```python
data.calculate_tf_averaged(ch_in=0, window=None)
data.plot_tf_data()
dvma.save_data(data, filename='impacts.dvma')
```

## Other examples

The remaining common measurements are covered in the guides:

- **FFT of one channel**: [Data Analysis](../user-guide/analysis.md#fast-fourier-transform-fft),
  and its plot in [Plotting](../user-guide/plotting.md#fft)
- **Transfer function and coherence**: [Data Analysis](../user-guide/analysis.md#transfer-function-analysis),
  and its plot in [Plotting](../user-guide/plotting.md#transfer-function)
- **Sonogram**: [Data Analysis](../user-guide/analysis.md#sonogram-spectrogram),
  and its plot in [Plotting](../user-guide/plotting.md#sonogram)
- **Damping from a free decay**: [Modal Analysis](../user-guide/modal-analysis.md#damping-from-free-decay-sonogram-method)
- **Filtering, zero padding and other edits to a record**:
  [Working with Time Data](../user-guide/analysis.md#working-with-time-data)
- **Looping over many saved files, or using pandas**:
  [Import and Export](../user-guide/import-export.md#working-with-many-files)
