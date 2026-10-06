# Modal Analysis

This guide covers modal analysis from Python: natural frequency, damping
and modal constants from impact tests and other transients.

## Overview

pydvma provides tools for:

- damping from a free decay, from a sonogram or a wavelet transform
- band decay times (EDT, T20, T30, T60) from the Schroeder integral
- fitting a single mode to transfer function data, across several channels

The [web logger](../web-logger/modal-fitting.md) uses the same fitter and
adds multi-mode fitting, refinement and a reconstruction overlay.

The examples start from a synthetic impulse test (channel 0 is the hammer
force, channel 1 the response). Use your own data in its place:

```python
import matplotlib.pyplot as plt
import numpy as np
import pydvma as dvma

data = dvma.create_test_impulse_data(noise_level=0.001)
time_data = data.time_data_list[0]
```

## Damping from Free Decay (Sonogram Method)

### Overview

The sonogram method estimates modal parameters from a free decay. It is
suited to impact tests and other transient responses.

### Basic Usage

```python
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data,
    n_chan=1,        # the response channel (channel 0 here is the force)
    nperseg=512,     # FFT segment length
    start_time=None, # see "Start time" below
)

print(f"Natural frequencies: {fn} Hz")
print(f"Q factors: {Qn}")
print(f"Damping ratios: {1 / (2 * Qn)}")
```

Choose `n_chan` carefully. It is 1 unless you say otherwise, and on the
force channel of an impact test the function finds no peaks and returns
empty arrays.

### Understanding the Results

The function returns three values:

- **fn**: natural frequencies in Hz, one per detected mode
- **Qn**: quality factors, `Q = 1/(2ζ)` where ζ is the damping ratio
- **fit_data**: a dictionary of the data behind each fit, for plotting

`fn` is the undamped natural frequency; the fit corrects the frequency it
measures for damping. To get back the damped frequency:

```python
zeta = 1 / (2 * Qn)
fn_damped = fn * np.sqrt(1 - zeta**2)
```

### Visualization

`fit_data['fits']` holds one dictionary for each mode, so you can check
the quality of every fit:

```python
for fit in fit_data['fits']:
    plt.figure()
    plt.plot(fit['t_fit'], fit['real_data'], 'x', label='Data')
    plt.plot(fit['t_fit'], fit['real_fit'], '-',
             label=f"Fit: {fit['f_peak']:.1f} Hz, Q={fit['Qn']:.0f}")
    plt.xlabel('Time (s)')
    plt.ylabel('Log amplitude')
    plt.legend()
    plt.title('Damping fit')
    plt.show()
```

### Method Details

The algorithm:

1. Computes a Hann-window sonogram (a short-time Fourier transform).
2. Finds frequency peaks in the spectrum at the start time.
3. Tracks the decay of each peak over time.
4. Fits an exponential decay, with a noise floor, to the log magnitude,
   and a straight line to the phase.
5. Returns natural frequencies and Q factors.

### Tips for Good Results

**Segment length.** A longer `nperseg` gives better frequency resolution,
which suits closely spaced modes (try 1024). A shorter one gives better
time resolution, which suits rapidly decaying signals (try 256).

**Data quality.**

- Ensure a good signal-to-noise ratio.
- Use a sensor range that avoids clipping.
- Record several periods of the decay.
- Minimise background noise.

**Start time.** `start_time=None` starts the analysis just after the
trigger when the capture used a pretrigger (at `2 * pretrig_samples / fs`).
Without a pretrigger it starts at the beginning of the record, which for a
hammer hit includes the impact. For untriggered records, give the time
after the impact yourself:

```python
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data, n_chan=1, start_time=0.01)      # start analysis at 0.01 s
```

**Peak threshold.** Peak picking scans the magnitude spectrum at the
start time. The threshold is a fraction of that slice's minimum to maximum
range. By default it is chosen automatically (`10 * median / max`). Pass
`peak_threshold` to control it directly:

```python
# Permissive: keep every peak above 5 % of the slice's range
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data, n_chan=1, peak_threshold=0.05)

# fit_data also carries the picking context, for plotting or re-fitting:
# 'start_time', 'threshold' (the value actually used), the start-slice
# spectrum ('slice_freq', 'slice_mag') and the candidate peaks
# ('peaks_freq', 'peaks_mag'), as well as the per-mode fits in 'fits'.
```

### Damping from a wavelet transform

`calculate_damping_from_cwt` does the same fit on a wavelet (CWT) image.
Its constant-Q resolution separates closely spaced low-frequency modes
that a fixed sonogram window smears together:

```python
fn, Qn, fit_data = dvma.calculate_damping_from_cwt(
    time_data, n_chan=1, f_range=(20, 500))      # Hz; limits the band and the memory used
```

It takes the same `start_time` and `peak_threshold`. A long, high-rate
record needs an explicit `f_range`, or the transform is too large.

### Damping by band (Schroeder decay)

The band alternative to peak fitting gives room-acoustics style decay
metrics, from a band-pass filter bank and the Schroeder backward-integrated
energy-decay curve:

```python
out = dvma.calculate_damping_by_band(
    time_data,
    n_chan=1,
    bands='octave',        # 'all', 'octave', 'third-octave' or 'tenth-decade'
    start_time=None,       # None: as for the sonogram method
    f_range=None,          # None: 4/T to 0.4*fs
)

# Ladder arrays (NaN where a band's decay range was too small to fit):
out['fc']    # band centres, Hz, anchored at 1000 Hz
out['EDT']   # early decay time (0 to -10 dB fit, x6)
out['T20']   # -5 to -25 dB fit, x3
out['T30']   # -5 to -35 dB fit, x2
out['T60']   # reverberation time (T30 where it exists, else T20)
out['Qn']    # band-centred Q = pi*fc*T60 / (3 ln 10)

# out['band_data'][i] holds each band's decay curve and T60 fit line, for plotting.
```

Use `bands='all'` for a single broadband decay (one overall T60).

## SDOF Modal Fitting

### Fitting one mode across channels

`modal_fit_all_channels` fits a single-degree-of-freedom mode to the
transfer functions in a `TfDataList`. All channels share one natural
frequency and damping ratio, and each gets its own modal constant:

```python
tf_data = dvma.calculate_tf(time_data, ch_in=0, window=None)
tf_list = dvma.TfDataList([tf_data])

modal_data = dvma.modal_fit_all_channels(
    tf_list,
    freq_range=[80, 120],       # Hz, around the mode
    measurement_type='vel',     # what the output is, per unit of input
)

print(f"Natural frequency: {modal_data.fn[0]:.2f} Hz")
print(f"Damping ratio: {modal_data.zn[0]:.4f}")
print(f"Modal constants: {modal_data.an}")
```

`measurement_type` says what the transfer function's output is, per unit
of input force: `'acc'` (acceleration), `'vel'` (velocity) or `'dsp'`
(displacement). The synthetic response is the velocity of one mode
(100 Hz, damping ratio 0.0159, modal constant 1000 /kg) driven by the
hammer pulse, so it is fitted with `'vel'`, and the fit recovers exactly
those values with the modal constant's phase at 0°. A phase well away
from 0° or 180° usually means the wrong `measurement_type`.

The fit is one mode per call, so for several modes call it once for each,
with `freq_range` around that mode. In the returned `ModalData`, `fn` and
`zn` have one element per mode, and `an` has one row per mode with a
column for each channel. The fit uses each transfer function's calibration
factors, so the constants come out in engineering units. If the frequency
range is poor, the function prints "Poor quality fit"; adjust the range and
try again.

!!! warning "Every transfer function in the list must share one frequency axis"
    `modal_fit_all_channels` picks the samples inside `freq_range` from the
    FIRST transfer function's axis and takes the same rows from every
    other one. Transfer functions on different axes (captures at different
    sample rates or frame lengths, or the separate measurements of a
    [Vibration Apps CSV](import-export.md#import-vibration-apps-transfer-functions))
    then give a wrong fit with no error. Fit those one at a time. The web
    app's **Fit** stage does align them, by interpolating every set onto
    the first set's frequencies.

### Fitting one channel

`modal_fit_single_channel` fits one mode to one column of a transfer
function and returns the optimiser's result:

```python
import pydvma as dvma

data = dvma.create_test_impulse_data()   # channel 0 force, channel 1 response
tf_data = dvma.calculate_tf(data.time_data_list[0], ch_in=0)

result = dvma.modal_fit_single_channel(
    tf_data,
    freq_range=[80, 120],     # Hz, around one mode
    channel=0,                # column of tf_data.tf_data
    measurement_type='vel',   # 'acc', 'vel' or 'dsp'
)

fn, zeta, an, phase, rk, rm = result.x
print(f"Natural frequency: {fn:.2f} Hz")
print(f"Damping ratio: {zeta:.4f}")
```

`result.x` is ordered `[fn, zeta, an, phase, rk, rm]`: the modal
constant's amplitude and phase (radians) follow the natural frequency
and damping ratio, then the two local residual terms. Unlike
`modal_fit_all_channels` above, the fit ignores the transfer function's
calibration factors.

## Beyond SDOF: not yet built in

Mode-shape extraction, the Modal Assurance Criterion (MAC) and Operating
Deflection Shape (ODS) plotting are common next steps after SDOF fitting.
pydvma doesn't provide them as functions yet. You can build them from the
arrays in `TfData` and `ModalData`: `modal_data.an` holds a modal
constant for every channel, and these are the ingredients of a mode shape.

## Experimental Modal Analysis Workflow

A complete workflow from a set of hammer hits to modal parameters. It
uses a synthetic ensemble so it runs as it stands. To use your own hits,
record them as in
[Impact test with averaging](../examples/basic.md#impact-test-with-averaging)
and use that dataset instead of `data`:

```python
from scipy.signal import find_peaks

# 1. Five hits (replace with your recorded dataset)
data = dvma.create_test_impulse_ensemble(N_ensemble=5, noise_level=0.05)

# 2. Averaged transfer function, force on channel 0
tf_data = dvma.calculate_tf_averaged(data.time_data_list, ch_in=0, window=None)
f = tf_data.freq_axis
H = tf_data.tf_data[:, 0]

# 3. Find the resonances below 500 Hz
below = f < 500
magnitude = np.abs(H[below])
peaks, _ = find_peaks(magnitude, height=0.1 * magnitude.max())
peak_frequencies = f[below][peaks]
print("Peaks (Hz):", peak_frequencies)

# 4. Fit each mode
tf_list = dvma.TfDataList([tf_data])
for f0 in peak_frequencies:
    modal_data = dvma.modal_fit_all_channels(
        tf_list, freq_range=[0.8 * f0, 1.2 * f0], measurement_type='vel')
    print(f"f = {modal_data.fn[0]:.2f} Hz, zeta = {modal_data.zn[0]:.4f}")

# 5. Cross-check the damping from the free decay of the first hit
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    data.time_data_list[0], n_chan=1, nperseg=512)

print("Damping from the decay:")
for i, (freq, Q) in enumerate(zip(fn, Qn)):
    print(f"  Mode {i + 1}: f = {freq:.2f} Hz, zeta = {1 / (2 * Q):.4f}, Q = {Q:.1f}")
```

For plots of the transfer function and coherence, see
[Plotting and Visualization](plotting.md#transfer-function).

## References and Further Reading

- Ewins, D.J. (2000). Modal Testing: Theory, Practice and Application
- Maia, N.M.M. & Silva, J.M.M. (1997). Theoretical and Experimental Modal Analysis
- Inman, D.J. (2013). Engineering Vibration

## Next Steps

- Learn about [Plotting and Visualization](plotting.md)
- See the worked [Examples](../examples/basic.md)
- Check the [API Reference](../api/modal.md)
