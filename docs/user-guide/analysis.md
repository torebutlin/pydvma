# Data Analysis

This guide covers the analysis functions in pydvma. Each takes one
`TimeData` (or a list of them) and returns a new result object. On a
whole `DataSet`, the `*_set` methods such as `calculate_fft_set` run the
same functions over every measurement (see [Python basics](../getting-started/basic-usage.md)).
For plots of these results, see [Plotting and Visualization](plotting.md).

The examples start from a synthetic impulse test, where channel 0 is the
hammer force and channel 1 the response. Use your own data in its place:

```python
import numpy as np
import pydvma as dvma

data = dvma.create_test_impulse_data(noise_level=0.01)
time_data = data.time_data_list[0]
```

## Frequency Domain Analysis

### Fast Fourier Transform (FFT)

```python
freq_data = dvma.calculate_fft(time_data, window='hann')

f = freq_data.freq_axis      # Hz, n_samples // 2 + 1 bins
Y = freq_data.freq_data      # complex, shape (frequencies, channels)
```

`time_range=[t_start, t_end]` analyses part of the record, and
`window=None` (the default) uses no window. `Y` holds raw recorded values:
multiply by `freq_data.channel_cal_factors` for engineering units, as the
plotting functions do.

The result is the raw FFT of the windowed record. It is not divided by
the number of samples and not corrected for the window, so its level
depends on both: a 1 V sine gives a peak of `N/2` with no window, and half
that with a Hann window. Use it for frequencies and shapes. For levels,
use the power spectrum or PSD below.

### Power spectral density

Divide the auto-spectrum from the cross-spectrum matrix by the window's
effective noise bandwidth:

```python
cs = dvma.calculate_cross_spectrum_matrix(time_data, window='hann', N_frames=4)
psd = cs.Pxy[1, 1].real / cs.enbw_hz      # channel 1, unit²/Hz
```

This density does not change with the frequency resolution, so it is the
one to read a noise floor from. [Cross-Spectrum Analysis](#cross-spectrum-analysis)
explains the difference from the power spectrum `Pxy` itself.

### Window Functions

`window` accepts any name that `scipy.signal.windows.get_window` does,
including tuples such as `('kaiser', 8)`:

```python
freq_rect = dvma.calculate_fft(time_data, window=None)        # rectangular
freq_hann = dvma.calculate_fft(time_data, window='hann')
freq_black = dvma.calculate_fft(time_data, window='blackman')
```

| Window | Main lobe (noise bandwidth, bins) | Highest sidelobe | Use for |
| ------ | --------------------------------- | ---------------- | ------- |
| `None` (rectangular) | 1.00 | -13 dB | transients that decay within the record, such as hammer impacts |
| `'hann'` | 1.50 | -31 dB | a good default for noise and other stationary signals |
| `'hamming'` | 1.36 | -43 dB | like Hann, with a lower first sidelobe that falls off more slowly |
| `'blackman'` | 1.73 | -58 dB | seeing a small peak next to a large one |
| `'flattop'` | 3.77 | -93 dB | reading peak amplitudes accurately |

A wider main lobe means poorer frequency resolution, and lower sidelobes
mean less leakage. Blackman has lower sidelobes but a wider main lobe
than Hann, so it separates close peaks less well.

Do not window an impact record with Hann or Blackman. They taper to zero
at the start, where the hammer pulse is, so they distort a transfer
function badly (on the test data above the peak of |H| changes by four
orders of magnitude). Leave `window=None` for hits that die away within
the record.

## Transfer Function Analysis

### Single Transfer Function

```python
tf_data = dvma.calculate_tf(
    time_data,
    ch_in=0,            # input (reference) channel
    time_range=None,    # or [t_start, t_end]
    window=None,        # an impact record: no window
    N_frames=1,         # number of frames to average
    overlap=0.5,        # overlap between frames, 0 to 1
)

f = tf_data.freq_axis
H = tf_data.tf_data            # complex, (frequencies, output channels)
coherence = tf_data.tf_coherence
```

`H` has one column for every channel except `ch_in`, in order, using the
H1 estimator (`Pxy[in, out] / Pxy[in, in]`). It is the raw ratio of the
recorded values. Multiply column `k` by `tf_data.channel_cal_factors[k]`
to get output units per input unit, as the plotting functions do.

### Coherence Function

Coherence, between 0 and 1, tells you how much of the output is linearly
related to the input. It is estimated by averaging frames, so it needs
`N_frames` greater than 1: with a single frame it is exactly 1 at every
frequency, whatever the data. Use 8 or more.

```python
noise = dvma.create_test_noise_data(added_noise_level=0.1).time_data_list[0]
tf_noise = dvma.calculate_tf(noise, ch_in=0, window='hann', N_frames=8)

f = tf_noise.freq_axis
coherence = tf_noise.tf_coherence[:, 0]
print(coherence[(f > 80) & (f < 120)].mean())      # near the resonance: close to 1
```

Good coherence (close to 1) indicates:

- low noise
- a linear system
- good causality

Low coherence can indicate:

- high noise levels (as away from the resonance above, where the response
  is small)
- non-linear behaviour
- uncorrelated signals
- time delays or wraparound

### Averaging for Better Estimates

`N_frames` cuts the record into about that many overlapping segments and
averages their spectra:

```python
tf_data = dvma.calculate_tf(time_data, ch_in=0, window='hann', N_frames=8, overlap=0.5)
print(len(tf_data.freq_axis))          # 1112 bins, against 5001 for one frame
```

Each segment is shorter, so the frequency spacing is coarser
(`fs / segment length`). More frames give a smoother estimate and a
meaningful coherence, at the cost of resolution.

### Ensemble Averaging

For repeated measurements, such as several hammer hits, average across
the records instead of within one:

```python
ensemble = dvma.create_test_impulse_ensemble(N_ensemble=5, noise_level=0.05)
tf_avg = dvma.calculate_tf_averaged(ensemble.time_data_list, ch_in=0, window=None)
```

The argument must be a `TimeDataList` (a `DataSet`'s `time_data_list` is
one). The records need the same channels and sample rate, and slightly
different lengths are cut to the shortest. Pass `window=None` for
impacts and `'hann'` for noise. The result is one `TfData`. See
[Basic Examples](../examples/basic.md#impact-test-with-averaging) for
recording the hits.

## Cross-Spectrum Analysis

### Cross-Spectral Matrix

For multi-channel analysis:

```python
cross_spec = dvma.calculate_cross_spectrum_matrix(
    time_data,
    time_range=None,
    window='hann',
    N_frames=8,
    overlap=0.5,
)

Pxy = cross_spec.Pxy      # complex, (channels, channels, frequencies)
Cxy = cross_spec.Cxy      # coherence matrix, same shape

P11 = Pxy[1, 1].real      # auto-spectrum of channel 1
enbw = cross_spec.enbw_hz # effective noise bandwidth of the window, in Hz
```

`Pxy[i, j]` is the cross-spectrum `conj(X_i) X_j` averaged over the
frames. As for transfer functions, `Cxy` is exactly 1 unless `N_frames`
is greater than 1.

!!! info "`Pxy` is a spectrum, not a density"
    `Pxy` uses scipy's `scaling='spectrum'`: each bin holds the
    mean-square amplitude in that bin, in `unit**2`. Its level scales
    with the frequency resolution, so a broadband noise floor read off it
    moves when `N_frames` changes.

    `enbw_hz` is the window's effective noise bandwidth,

    $$
    \mathrm{ENBW} = f_s\,\frac{\sum_k w_k^{2}}{\left(\sum_k w_k\right)^{2}}
    \quad\text{[Hz]},
    $$

    and dividing by it converts the spectrum to a spectral **density** in
    `unit**2/Hz`, whose level does not move with the resolution:

    ```python
    density = cross_spec.Pxy / cross_spec.enbw_hz
    ```

    Read a discrete tone off the spectrum (a sine of amplitude `A` peaks
    at `A**2 / 2`); read a noise floor off the density.

### Cross-Spectrum Averaging

To average the cross-spectra of several separate records, with each
record counting as one frame:

```python
cross_spec_avg = dvma.calculate_cross_spectra_averaged(
    ensemble.time_data_list, window='hann')
```

## Time-Frequency Analysis

### Sonogram (Spectrogram)

Analyse how frequency content changes over time:

```python
sono_data = dvma.calculate_sonogram(time_data, nperseg=512, noverlap=256)

t = sono_data.time_axis       # frame centres, s
f = sono_data.freq_axis       # Hz
S = sono_data.sono_data       # complex, (frequencies, times, channels)
```

The window is Hann. Left out, `nperseg` is a fiftieth of the record and
`noverlap` half of `nperseg`.

### Time-Frequency Resolution Trade-off

```python
# Better frequency resolution, worse time resolution
sono_long = dvma.calculate_sonogram(time_data, nperseg=2048)

# Better time resolution, worse frequency resolution
sono_short = dvma.calculate_sonogram(time_data, nperseg=256)
```

## Integration and Differentiation

### Frequency Domain Integration

Multiplying by `(iω)^power` converts between acceleration, velocity and
displacement. `multiply_by_power_of_iw` changes its argument in place and
returns the same object, so copy first if you want to keep the original
or to make several results from one spectrum:

```python
import copy

spectrum = dvma.calculate_fft(time_data)        # channel 1 as acceleration

# velocity: V = A / (iω)
velocity = dvma.multiply_by_power_of_iw(
    copy.deepcopy(spectrum), power=-1, channel_list=[1])

# displacement: X = A / (iω)²
displacement = dvma.multiply_by_power_of_iw(
    copy.deepcopy(spectrum), power=-2, channel_list=[1])
```

`channel_list` names the columns to convert. A negative power cannot be
evaluated at 0 Hz, so ignore the first bin of the result. The unit labels
are not updated, so relabel the result yourself. A positive power
differentiates.

### For Transfer Functions

The same function converts a transfer function between acceleration,
velocity and displacement per unit force:

```python
tf_acc = dvma.calculate_tf(time_data, ch_in=0)          # acceleration / force

receptance = dvma.multiply_by_power_of_iw(              # displacement / force
    copy.deepcopy(tf_acc), power=-2, channel_list=[0])
mobility = dvma.multiply_by_power_of_iw(                # velocity / force
    copy.deepcopy(tf_acc), power=-1, channel_list=[0])
```

Here `channel_list` selects output channels, as columns of `tf_data`.

## Impulse Response Cleaning

For impact hammer measurements, `clean_impulse` tidies the force channel:

```python
time_data_clean = dvma.clean_impulse(time_data, ch_impulse=0)    # returns a copy

tf_clean = dvma.calculate_tf(time_data_clean, ch_in=0, window=None)
```

Only the `ch_impulse` column changes. The function finds the peak and
estimates the pulse width from where the force falls below half its peak
(assuming a half-cosine pulse). It keeps that channel up to just after the
pulse, then fades it to zero with a long Hann ramp. Nothing before the
impact is zeroed, and the response channels are not touched. Noise or a
second hit after the pulse no longer reaches the transfer function. If
the cleaned channel differs markedly from the original, it warns about
multiple impacts or the wrong channel. Cleaning an already cleaned record
does nothing.

## Peak Detection

Find peaks in a spectrum with scipy:

```python
from scipy.signal import find_peaks

freq_data = dvma.calculate_fft(time_data)
magnitude = np.abs(freq_data.freq_data[:, 1])           # response channel

peaks, _ = find_peaks(magnitude, height=0.3 * magnitude.max(), distance=5)
print("Peak frequencies:", freq_data.freq_axis[peaks])
```

## Data Scaling and Matching

`best_match` finds the factor that scales each transfer function onto a
reference one over a frequency range:

```python
ensemble = dvma.create_test_impulse_ensemble(N_ensemble=3, noise_level=0.05)
tf_list = dvma.TfDataList(
    [dvma.calculate_tf(td, ch_in=0) for td in ensemble.time_data_list])

factors = dvma.best_match(
    tf_list,
    freq_range=[50, 150],   # Hz: a band where the TFs are clean
    set_ref=0,              # reference set
    ch_ref=0,               # reference channel
)

tf_list.set_calibration_factors_all([f.ravel() for f in factors])
```

`factors` has one array per set, shaped `(n_channels, 1)`: each
channel's factor relative to the reference channel. Leaving out
`freq_range` matches over the whole frequency axis, where noise at the
ends can skew the factors or even flip their sign, so give a band where
the transfer functions are clean.

The last line writes the factors as the sets' `channel_cal_factors`,
which **replaces any calibration those channels already had**. See
[Calibration and units](../web-logger/calibration.md) for what that
multiplier does.

## Working with Time Data

To analyse an edited copy of a record, build a new `TimeData` with
`dvma.TimeData`. Don't assign to the original, and don't use `copy.copy`:
a shallow copy shares its calibration array and `unique_id` with the
original, so a change to one shows in the other.

### Zero Padding

Padding a record with zeros puts the spectrum on a finer frequency grid.
It interpolates between the same information; it does not improve the
resolution, which depends on the length of the real record.

```python
n_pad = len(time_data.time_axis)
padded = np.vstack([time_data.time_data,
                    np.zeros((n_pad, time_data.time_data.shape[1]))])

time_data_padded = dvma.TimeData(
    np.arange(padded.shape[0]) / time_data.settings.fs,     # a longer time axis
    padded,
    time_data.settings,
    units=time_data.units,
    channel_cal_factors=np.array(time_data.channel_cal_factors, dtype=float),
    test_name=time_data.test_name,
)

freq_padded = dvma.calculate_fft(time_data_padded)          # 0.5 Hz bins instead of 1 Hz
```

### Band-pass Filtering

```python
from scipy import signal

sos = signal.butter(4, [50, 500], 'bandpass',
                    fs=time_data.settings.fs, output='sos')
filtered = signal.sosfiltfilt(sos, time_data.time_data, axis=0)   # zero phase

time_data_filtered = dvma.TimeData(
    time_data.time_axis,
    filtered,
    time_data.settings,
    units=time_data.units,
    channel_cal_factors=np.array(time_data.channel_cal_factors, dtype=float),
    test_name=time_data.test_name,
)

freq_filtered = dvma.calculate_fft(time_data_filtered)
```

## Next Steps

- Learn about [Modal Analysis](modal-analysis.md)
- See [Plotting and Visualization](plotting.md) for plots of these results
- Check the [API Reference](../api/analysis.md) for every function
