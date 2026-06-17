# Basic Examples

Collection of basic examples for common tasks.

## Complete workflow: acquire → analyse → plot

A full command-line session from a notebook or script — acquire (with
and without a played output, using either the built-in generator or a
hand-built NumPy array), compute spectra, PSDs/CSDs and transfer
functions, then plot. Every call below is part of the public API; the
numbered examples further down drill into individual steps.

### 1. Imports and settings

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

settings = dvma.MySettings(
    channels=2,          # ch0 = reference/input, ch1 = response/output
    fs=10000,
    stored_time=1.0,
    output_channels=1,   # one AO drive (only used when you play an output)
)
# device_driver defaults to 'soundcard'; set 'nidaq' for an NI device.
# Playing an output needs an output-capable device (soundcard out or NI AO).
```

### 2. Acquire — three ways

Each `log_data` call returns a fresh `DataSet` holding one `TimeData`
(shape `(n_samples, channels)`) in `dataset.time_data_list`.

```python
# (a) plain capture, no excitation
dataset = dvma.log_data(settings, test_name='plain')

# (b) drive the built-in generator (band-limited Gaussian noise).
#     signal_generator returns (t, output); output is (N, output_channels) in volts.
t, output = dvma.signal_generator(settings, sig='gaussian',
                                  T=settings.stored_time, amplitude=0.1,
                                  f=[20, 2000])          # bandpass corners (Hz)
dataset = dvma.log_data(settings, output=output, test_name='driven_noise')

# (c) drive a custom NumPy waveform (multi-tone), in volts.
#     Format: 2-D (N_samples, output_channels), sampled at settings.output_fs,
#     within +/- settings.output_vmax(). (See the acquisition guide for the
#     full contract — a raw array gets no auto fade or safety clamp.)
fs_out = settings.output_fs                              # = settings.fs unless overridden
tt = np.arange(0, settings.stored_time, 1 / fs_out)
drive = 0.2 * np.sin(2 * np.pi * np.outer(tt, [110.0, 370.0, 990.0])).sum(axis=1)
drive = np.clip(drive, -settings.output_vmax(), settings.output_vmax())
output = drive[:, None]                                  # -> (N, 1)
dataset = dvma.log_data(settings, output=output, test_name='driven_multitone')
```

To ensemble-average several repeats (e.g. impact tests), accumulate the
`TimeData` objects into one dataset:

```python
dataset = dvma.DataSet()
for i in range(5):
    d = dvma.log_data(settings, output=output, test_name=f'rep_{i}')
    dataset.add_to_dataset(d.time_data_list[0])
```

### 3. Spectra, PSDs/CSDs and transfer functions

`DataSet` has high-level `*_set` methods that run an analysis over every
`TimeData` in `time_data_list` and store the result back on the dataset:

```python
# Linear spectra (one-sided complex FFT) -> dataset.freq_data_list
dataset.calculate_fft_set(window='hann')

# Cross-spectrum matrix via Welch -> dataset.cross_spec_data_list.
# Pxy[i,i] is the channel-i auto-spectrum (the PSD; scaling='spectrum', V^2),
# Pxy[i,j] the cross-spectrum (CSD), Cxy[i,j] the coherence in [0, 1].
dataset.calculate_cross_spectrum_matrix_set(window='hann', N_frames=8, overlap=0.5)

# Transfer functions H = Pxy[in,out]/Pxy[in,in], one column per non-input
# channel -> dataset.tf_data_list. ch_in selects the reference channel.
dataset.calculate_tf_set(ch_in=0, window='hann', N_frames=8, overlap=0.5)
```

For an ensemble (a multi-capture `time_data_list`) average across the set
instead — these give a single averaged result:

```python
dataset.calculate_cross_spectra_averaged(window='hann')   # -> 1-item cross_spec_data_list
dataset.calculate_tf_averaged(ch_in=0, window='hann')     # -> 1-item tf_data_list
```

!!! note "Two different frequency axes"
    `calculate_fft_set` transforms the whole block, so its axis has
    `n_samples//2 + 1` bins. The cross-spectrum and TF use Welch
    segmenting (`N_frames`, `overlap`), so their `freq_axis` is shorter
    and is the one to use when plotting `Pxy`/`Cxy`/`tf_data`.

### 4. Plot

The built-in plotters open one interactive figure per data type and
apply `channel_cal_factors` automatically (so they read in engineering
units when you set `channel_sensitivities`). They need the GUI extras
(`qtpy` + `PyQt5`) installed:

```python
dataset.plot_time_data()
dataset.plot_freq_data()   # needs calculate_fft_set() first
dataset.plot_tf_data()     # magnitude + phase + coherence; needs calculate_tf_set()
```

Cross-spectra (PSD/CSD) have **no** built-in plot — read the arrays off
the `CrossSpecData` and plot them yourself (this also works without the
GUI extras). The diagonal of `Pxy` is the PSD, the off-diagonal the CSD:

```python
csd  = dataset.cross_spec_data_list[0]
f    = csd.freq_axis
psd0 = np.abs(csd.Pxy[0, 0, :])    # PSD of channel 0  (V^2)
psd1 = np.abs(csd.Pxy[1, 1, :])    # PSD of channel 1
cs01 = csd.Pxy[0, 1, :]            # CSD ch0->ch1 (complex)
coh  = csd.Cxy[0, 1, :]            # coherence in [0, 1]

fig, (axp, axc) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
axp.semilogy(f, psd0, label='PSD ch0')
axp.semilogy(f, psd1, label='PSD ch1')
axp.semilogy(f, np.abs(cs01), '--', label='|CSD 0-1|')
axp.set_ylabel('Power (V$^2$)'); axp.legend(); axp.grid(True, which='both', alpha=0.3)
axc.plot(f, coh)
axc.set_xlabel('Frequency (Hz)'); axc.set_ylabel('Coherence'); axc.set_ylim(0, 1)
axc.grid(True, alpha=0.3)
plt.tight_layout(); plt.show()
```

The same array-access pattern works for the transfer function — magnitude,
phase and coherence straight from the `TfData` (see
[Example 2](#example-2-transfer-function-measurement) below for the full plot):

```python
tf = dataset.tf_data_list[0]
H  = tf.tf_data[:, 0]          # complex FRF, first output channel
coh = tf.tf_coherence[:, 0]    # its coherence
# |H| = np.abs(H);  phase = np.angle(H, deg=True);  axis = tf.freq_axis
```

## Example 1: Simple Measurement and FFT

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

# Setup
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 2.0
settings.channels = 1

# Record
dataset = dvma.log_data(settings, test_name="example_01")
time_data = dataset.time_data_list[0]

# Calculate FFT
freq_data = dvma.calculate_fft(time_data, window='hann')

# Plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

ax1.plot(time_data.time_axis, time_data.time_data[:, 0])
ax1.set_xlabel('Time (s)')
ax1.set_ylabel('Amplitude')
ax1.set_title('Time Domain')
ax1.grid(True)

ax2.semilogy(freq_data.freq_axis, np.abs(freq_data.freq_data[:, 0]))
ax2.set_xlabel('Frequency (Hz)')
ax2.set_ylabel('Magnitude')
ax2.set_title('Frequency Domain')
ax2.set_xlim([0, 2000])
ax2.grid(True)

plt.tight_layout()
plt.show()
```

## Example 2: Transfer Function Measurement

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

# Setup for 2-channel measurement
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 2.0
settings.channels = 2  # Channel 0: input, Channel 1: output

# Record
dataset = dvma.log_data(settings, test_name="tf_measurement")
time_data = dataset.time_data_list[0]

# Calculate transfer function
tf_data = dvma.calculate_tf(time_data, ch_in=0, window='hann',
                             N_frames=4, overlap=0.5)

# Plot
f = tf_data.freq_axis
H = tf_data.tf_data[:, 0]
coh = tf_data.tf_coherence[:, 0]

fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 10))

# Magnitude
ax1.loglog(f, np.abs(H))
ax1.set_ylabel('|H(f)|')
ax1.set_title('FRF Magnitude')
ax1.grid(True, which='both')

# Phase
ax2.semilogx(f, np.angle(H, deg=True))
ax2.set_ylabel('Phase (deg)')
ax2.set_title('FRF Phase')
ax2.grid(True)

# Coherence
ax3.semilogx(f, coh)
ax3.set_xlabel('Frequency (Hz)')
ax3.set_ylabel('Coherence')
ax3.set_ylim([0, 1])
ax3.set_title('Coherence')
ax3.grid(True)

plt.tight_layout()
plt.show()
```

## Example 3: Impact Test with Averaging

```python
import pydvma as dvma
import numpy as np

# Setup
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 1.0
settings.channels = 2
settings.pretrig_samples = 1000

# Collect multiple impacts
time_data_list = dvma.TimeDataList()
n_impacts = 5

for i in range(n_impacts):
    input(f"Press Enter for impact {i+1}/{n_impacts}...")
    data = dvma.log_data(settings, test_name=f"impact_{i}")
    time_data_list.append(data.time_data_list[0])

# Calculate averaged transfer function
tf_data = dvma.calculate_tf_averaged(time_data_list, ch_in=0)

# Results
print(f"Averaged {len(time_data_list)} measurements")
print(f"Average coherence: {np.mean(tf_data.tf_coherence):.3f}")
```

## Example 4: Sonogram Analysis

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

# Record data
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 5.0
dataset = dvma.log_data(settings, test_name="sono_test")
time_data = dataset.time_data_list[0]

# Calculate sonogram
sono_data = dvma.calculate_sonogram(time_data, nperseg=512, noverlap=256)

# Plot
plt.figure(figsize=(12, 6))
plt.pcolormesh(sono_data.time_axis,
               sono_data.freq_axis,
               20*np.log10(np.abs(sono_data.sono_data[:, :, 0])),
               shading='gouraud',
               cmap='viridis')
plt.ylabel('Frequency (Hz)')
plt.xlabel('Time (s)')
plt.colorbar(label='Magnitude (dB)')
plt.ylim([0, 2000])
plt.title('Sonogram')
plt.show()
```

## Example 5: Modal Analysis from Impact

```python
import pydvma as dvma
import numpy as np

# Record impact response
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 2.0
settings.channels = 2
settings.pretrig_samples = 1000

dataset = dvma.log_data(settings, test_name="modal_test")
time_data = dataset.time_data_list[0]

# Extract damping from free decay
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data,
    n_chan=1,
    nperseg=512
)

# Display results
print("Modal Analysis Results:")
print("-" * 40)
for i, (f, Q) in enumerate(zip(fn, Qn)):
    zeta = 1 / (2 * Q)
    print(f"Mode {i+1}:")
    print(f"  Natural frequency: {f:.2f} Hz")
    print(f"  Damping ratio: {zeta:.4f}")
    print(f"  Q factor: {Q:.1f}")
    print()
```
