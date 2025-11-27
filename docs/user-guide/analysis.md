# Data Analysis

This guide covers the analysis functions available in pydvma.

## Frequency Domain Analysis

### Fast Fourier Transform (FFT)

Convert time-domain signals to frequency domain:

```python
import pydvma as dvma
import numpy as np

# Calculate FFT
freq_data = dvma.calculate_fft(
    time_data,
    time_range=None,  # Use all data, or specify [t_start, t_end]
    window='hann'     # Window function
)

# Access results
f = freq_data.freq_axis
Y = freq_data.freq_data  # Complex spectrum

# Plot magnitude spectrum
import matplotlib.pyplot as plt
plt.figure()
plt.plot(f, np.abs(Y[:, 0]))
plt.xlabel('Frequency (Hz)')
plt.ylabel('Magnitude')
plt.yscale('log')
plt.xlim([0, 1000])
```

### Power Spectral Density

```python
# Calculate power spectral density
psd = np.abs(Y)**2
psd_db = 10 * np.log10(psd)

plt.plot(f, psd_db[:, 0])
plt.xlabel('Frequency (Hz)')
plt.ylabel('PSD (dB)')
```

### Window Functions

Different windows for different applications:

```python
# Rectangular - no windowing, best frequency resolution
freq_data = dvma.calculate_fft(time_data, window=None)

# Hann - good general purpose, reduces spectral leakage
freq_data = dvma.calculate_fft(time_data, window='hann')

# Hamming - similar to Hann
freq_data = dvma.calculate_fft(time_data, window='hamming')

# Blackman - excellent frequency selectivity
freq_data = dvma.calculate_fft(time_data, window='blackman')
```

## Transfer Function Analysis

### Single Transfer Function

Calculate frequency response functions:

```python
# Calculate transfer function (input on channel 0)
tf_data = dvma.calculate_tf(
    time_data,
    ch_in=0,          # Input channel index
    time_range=None,  # Time range to use
    window='hann',    # Window function
    N_frames=1,       # Number of frames to average
    overlap=0.5       # Overlap fraction (0 to 1)
)

# Access results
f = tf_data.freq_axis
H = tf_data.tf_data           # Complex transfer function
coh = tf_data.tf_coherence    # Coherence function

# Plot FRF magnitude
plt.figure()
plt.loglog(f, np.abs(H[:, 0]))
plt.xlabel('Frequency (Hz)')
plt.ylabel('|H(f)|')
plt.grid(True)
```

### Coherence Function

Assess measurement quality:

```python
# Plot coherence
plt.figure()
plt.semilogx(f, coh[:, 0])
plt.xlabel('Frequency (Hz)')
plt.ylabel('Coherence')
plt.ylim([0, 1])
plt.grid(True)
```

Good coherence (close to 1) indicates:
- Low noise
- Linear system
- Good causality

Low coherence can indicate:
- High noise levels
- Non-linear behavior
- Uncorrelated signals
- Time delays/wraparound

### Averaging for Better Estimates

```python
# Frame averaging - split data into overlapping segments
tf_data = dvma.calculate_tf(
    time_data,
    ch_in=0,
    N_frames=8,    # 8 segments
    overlap=0.5    # 50% overlap
)
```

### Ensemble Averaging

For repeated measurements:

```python
# Multiple impact tests
time_data_list = dvma.TimeDataList()
for i in range(10):
    data = dvma.log_data(settings, test_name=f"impact_{i}")
    time_data_list.append(data.time_data_list[0])

# Averaged transfer function
tf_data_avg = dvma.calculate_tf_averaged(
    time_data_list,
    ch_in=0,
    window='hann'
)
```

## Cross-Spectrum Analysis

### Cross-Spectral Matrix

For multi-channel analysis:

```python
# Calculate cross-spectrum matrix
cross_spec = dvma.calculate_cross_spectrum_matrix(
    time_data,
    time_range=None,
    window='hann',
    N_frames=1,
    overlap=0.5
)

# Access cross-spectral density matrix
Pxy = cross_spec.Pxy  # Complex cross-spectrum [chan x chan x freq]
Cxy = cross_spec.Cxy  # Coherence matrix

# Auto-spectrum for channel 0
P00 = cross_spec.Pxy[0, 0, :]
```

### Cross-Spectrum Averaging

```python
# Averaged cross-spectrum from multiple measurements
cross_spec_avg = dvma.calculate_cross_spectra_averaged(
    time_data_list,
    time_range=None,
    window='hann'
)
```

## Time-Frequency Analysis

### Sonogram (Spectrogram)

Analyze how frequency content changes over time:

```python
# Calculate sonogram
sono_data = dvma.calculate_sonogram(
    time_data,
    nperseg=512,    # FFT segment length
    noverlap=256    # Overlap samples
)

# Access results
t = sono_data.time_axis
f = sono_data.freq_axis
S = sono_data.sono_data  # Complex spectrogram [freq x time x chan]

# Plot
plt.figure(figsize=(10, 6))
plt.pcolormesh(
    t, f,
    20*np.log10(np.abs(S[:, :, 0])),
    shading='gouraud'
)
plt.ylabel('Frequency (Hz)')
plt.xlabel('Time (s)')
plt.colorbar(label='Magnitude (dB)')
plt.ylim([0, 2000])
```

### Time-Frequency Resolution Trade-off

```python
# Better frequency resolution (worse time resolution)
sono_long = dvma.calculate_sonogram(time_data, nperseg=2048)

# Better time resolution (worse frequency resolution)
sono_short = dvma.calculate_sonogram(time_data, nperseg=256)
```

## Integration and Differentiation

### Frequency Domain Integration

Convert between kinematic quantities:

```python
# Get acceleration FFT
freq_data_accel = dvma.calculate_fft(time_data)

# Integrate to velocity: v = ∫a dt → V = A/(iω)
freq_data_vel = dvma.multiply_by_power_of_iw(
    freq_data_accel,
    power=-1,
    channel_list=[0]
)

# Integrate to displacement: x = ∫v dt → X = V/(iω)
freq_data_disp = dvma.multiply_by_power_of_iw(
    freq_data_accel,
    power=-2,
    channel_list=[0]
)
```

### For Transfer Functions

```python
# Acceleration/Force FRF
tf_data = dvma.calculate_tf(time_data, ch_in=0)

# Convert to receptance (displacement/force)
tf_receptance = dvma.multiply_by_power_of_iw(
    tf_data,
    power=-2,
    channel_list=[0]  # Output channels to convert
)

# Convert to mobility (velocity/force)
tf_mobility = dvma.multiply_by_power_of_iw(
    tf_data,
    power=-1,
    channel_list=[0]
)
```

## Impulse Response Cleaning

For impact hammer measurements:

```python
# Clean impulse data (remove after-ring)
time_data_clean = dvma.clean_impulse(
    time_data,
    ch_impulse=0  # Channel containing impulse
)

# Then calculate transfer function
tf_data = dvma.calculate_tf(time_data_clean, ch_in=0)
```

This function:
- Identifies the impulse
- Estimates pulse width
- Windows out noise after the response
- Preserves the actual response

## Peak Detection

Find peaks in frequency domain:

```python
import peakutils as pu

# Get magnitude spectrum
freq_data = dvma.calculate_fft(time_data)
magnitude = np.abs(freq_data.freq_data[:, 0])

# Find peaks
threshold = 0.3  # Relative threshold (0-1)
min_dist = 5     # Minimum samples between peaks
peak_indices = pu.indexes(magnitude, thres=threshold, min_dist=min_dist)

# Get peak frequencies
f = freq_data.freq_axis
peak_frequencies = f[peak_indices]
peak_magnitudes = magnitude[peak_indices]

print("Peak frequencies:", peak_frequencies)
```

## Data Scaling and Matching

### Match Multiple Datasets

```python
# Create list of transfer functions
tf_list = dvma.TfDataList()
tf_list.append(tf_1)
tf_list.append(tf_2)
tf_list.append(tf_3)

# Calculate scale factors
factors = dvma.best_match(
    tf_list,
    freq_range=[100, 500],  # Frequency range for matching
    set_ref=0,              # Reference dataset index
    ch_ref=0                # Reference channel
)

# Apply scaling
for i, factor in enumerate(factors):
    tf_list[i].tf_data *= factor[:, None]
```

## Advanced Topics

### Zero Padding

Increase frequency resolution through zero padding:

```python
# Pad time signal with zeros
n_pad = len(time_data.time_data) * 2
time_padded = np.vstack([
    time_data.time_data,
    np.zeros((n_pad, time_data.time_data.shape[1]))
])

# Update time data
import copy
time_data_padded = copy.copy(time_data)
time_data_padded.time_data = time_padded

# Calculate FFT
freq_data = dvma.calculate_fft(time_data_padded)
```

### Band-pass Filtering

```python
from scipy import signal

# Design filter
sos = signal.butter(4, [100, 1000], 'bandpass',
                    fs=time_data.settings.fs, output='sos')

# Apply filter
filtered = signal.sosfiltfilt(sos, time_data.time_data, axis=0)

# Update time data
time_data_filtered = copy.copy(time_data)
time_data_filtered.time_data = filtered
```

## Next Steps

- Learn about [Modal Analysis](modal-analysis.md)
- See [Examples](../examples/basic.md) for complete workflows
- Check [API Reference](../api/analysis.md) for detailed function documentation
