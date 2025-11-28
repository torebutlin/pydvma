# Modal Analysis

This guide covers modal analysis capabilities in pydvma.

## Overview

Modal analysis identifies the natural frequencies, damping ratios, and mode shapes of structures. pydvma provides tools for:

- Natural frequency identification
- Damping estimation from decay measurements
- Single-degree-of-freedom (SDOF) fitting
- Mode shape visualization

## Damping from Free Decay (Sonogram Method)

### Overview

The sonogram-based damping estimation analyzes free decay responses to extract modal parameters. This is particularly useful for impact tests or other transient responses.

### Basic Usage

```python
import pydvma as dvma

# Load or record time data (e.g., from impact test)
time_data = dataset.time_data_list[0]

# Calculate damping from sonogram
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data,
    n_chan=0,       # Channel to analyze
    nperseg=512,    # FFT segment length
    start_time=None # Auto-detect start, or specify time
)

# Results
print(f"Natural frequencies: {fn} Hz")
print(f"Q factors: {Qn}")
print(f"Damping ratios: {1/(2*Qn)}")
```

### Understanding the Results

The function returns three values:

- **fn**: Natural frequencies in Hz
- **Qn**: Quality factors (Q = 1/(2ζ) where ζ is damping ratio)
- **fit_data**: Dictionary containing fit visualization data

```python
# Calculate damping ratio from Q factor
zeta = 1 / (2 * Qn)

# Calculate damped natural frequency
fn_damped = fn * np.sqrt(1 - zeta**2)
```

### Visualization

The fit data can be visualized to assess fit quality:

```python
import matplotlib.pyplot as plt

# fit_data contains:
# - 't': time axis
# - 'fits': list of fit dictionaries

for fit in fit_data['fits']:
    plt.figure()
    plt.plot(fit['t_fit'], fit['real_data'], 'x',
             label='Data')
    plt.plot(fit['t_fit'], fit['real_fit'], '-',
             label=f"Fit: {fit['f_peak']:.1f} Hz, Q={fit['Qn']:.0f}")
    plt.xlabel('Time (s)')
    plt.ylabel('Log amplitude')
    plt.legend()
    plt.title('Damping Fit')
    plt.show()
```

### Method Details

The algorithm:

1. Computes a sonogram (short-time Fourier transform)
2. Identifies frequency peaks in the initial spectrum
3. Tracks the decay of each peak over time
4. Fits an exponential decay model to extract damping
5. Returns natural frequencies and damping ratios

### Tips for Good Results

**Segment Length Selection**
```python
# Longer segments = better frequency resolution
nperseg = 1024  # Good for closely spaced modes

# Shorter segments = better time resolution
nperseg = 256   # Good for rapidly decaying signals
```

**Data Quality**
- Ensure good signal-to-noise ratio
- Use appropriate sensor range to avoid clipping
- Record sufficient decay duration (several periods)
- Minimize background noise

**Start Time**
```python
# Auto-detect (default)
fn, Qn, fit_data = dvma.calculate_damping_from_sono(time_data, n_chan=0)

# Specify start time manually
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data,
    n_chan=0,
    start_time=0.01  # Start analysis at 0.01 seconds
)
```

## SDOF Modal Fitting

### Single Channel Modal Fitting

Fit modal parameters from FRF data for a single channel:

```python
# Calculate transfer function
tf_data = dvma.calculate_tf(time_data, ch_in=0)

# Select frequency range around a mode
freq_range = [180, 220]  # Hz

# Perform single-channel modal fit (returns scipy.optimize.OptimizeResult)
result = dvma.modal_fit_single_channel(
    tf_data,
    freq_range=freq_range,
    channel=0,
    measurement_type='acc'  # 'acc', 'vel', or 'dsp'
)

# Access fitted parameters
fn, zeta, modal_constant = result.x[0], result.x[1], result.x[2]
print(f"Natural frequency: {fn:.2f} Hz")
print(f"Damping ratio: {zeta:.4f}")
print(f"Modal constant: {modal_constant}")
```

The optimized parameter vector is ordered as `[fn, zeta, an, phase, Rk, Rm]`.

### Multi-Channel Modal Fitting

For fitting modes across all channels from a list of transfer functions:

```python
# Fit modes for all channels
modal_data_list = dvma.modal_fit_all_channels(
    tf_data_list,
    freq_range=[180, 220],
    measurement_type='acc'  # 'acc', 'vel', or 'dsp'
)

# Review results for each measurement
for i, modal_data in enumerate(modal_data_list):
    print(f"Channel {i}:")
    print(f"  Natural frequency: {modal_data.fn:.2f} Hz")
    print(f"  Damping ratio: {modal_data.zeta:.4f}")
```

## Mode Shape Analysis

### Extracting Mode Shapes

From multi-point FRF measurements:

```python
# Measure FRFs at multiple locations
tf_list = dvma.TfDataList()

for location in measurement_points:
    # Record and calculate TF
    data = dvma.log_data(settings, test_name=f"point_{location}")
    tf = dvma.calculate_tf(data.time_data_list[0], ch_in=0)
    tf_list.append(tf)

# Extract mode shape at natural frequency
fn_mode = 150  # Hz
mode_shape = []
for tf_data in tf_list:
    # Find index closest to fn_mode
    idx = np.argmin(np.abs(tf_data.freq_axis - fn_mode))
    # Extract complex amplitude at that frequency
    mode_shape.append(tf_data.tf_data[idx, 0])

mode_shape = np.array(mode_shape)
```

### Plotting Mode Shapes

```python
import matplotlib.pyplot as plt
import numpy as np

# Define geometry (example: beam with measurement points)
x_positions = np.array([0, 0.1, 0.2, 0.3, 0.4, 0.5])  # meters

# Plot mode shape
plt.figure()
plt.plot(x_positions, np.abs(mode_shape), 'o-')
plt.xlabel('Position (m)')
plt.ylabel('Amplitude')
plt.title(f'Mode Shape at {fn_mode} Hz')
plt.grid(True)
plt.show()
```

### 2D Mode Shapes

For plate or surface measurements:

```python
# Define 2D grid of measurement points
x_grid = np.array([...])  # X coordinates
y_grid = np.array([...])  # Y coordinates
mode_shape_2d = np.array([...])  # Mode shape amplitudes

# Create contour plot
plt.figure(figsize=(10, 8))
plt.tricontourf(x_grid, y_grid, np.abs(mode_shape_2d), levels=20)
plt.colorbar(label='Amplitude')
plt.xlabel('X position (m)')
plt.ylabel('Y position (m)')
plt.title(f'Mode Shape at {fn_mode} Hz')
plt.axis('equal')
plt.show()
```

## Modal Assurance Criterion (MAC)

Compare mode shapes:

```python
def calculate_mac(mode1, mode2):
    """Calculate Modal Assurance Criterion between two mode shapes"""
    numerator = np.abs(np.dot(mode1.conj(), mode2))**2
    denominator = np.dot(mode1.conj(), mode1) * np.dot(mode2.conj(), mode2)
    return numerator / denominator

# Compare two mode shapes
mac_value = calculate_mac(mode_shape_1, mode_shape_2)
print(f"MAC value: {mac_value:.4f}")

# MAC close to 1: modes are similar
# MAC close to 0: modes are different
```

## Operating Deflection Shapes (ODS)

Visualize vibration at a specific frequency:

```python
# Calculate transfer functions at multiple points
tf_list = [...]  # List of TF measurements

# Extract ODS at operating frequency
f_operating = 120  # Hz
ods = []
for tf_data in tf_list:
    idx = np.argmin(np.abs(tf_data.freq_axis - f_operating))
    ods.append(tf_data.tf_data[idx, 0])
ods = np.array(ods)

# Animate ODS
plt.figure()
for phase in np.linspace(0, 2*np.pi, 50):
    ods_instant = np.real(ods * np.exp(1j*phase))
    plt.clf()
    plt.plot(x_positions, ods_instant, 'o-')
    plt.ylim([-np.max(np.abs(ods)), np.max(np.abs(ods))])
    plt.pause(0.05)
```

## Experimental Modal Analysis Workflow

### Complete Example

```python
import pydvma as dvma
import numpy as np
import matplotlib.pyplot as plt

# 1. Setup
settings = dvma.MySettings()
settings.fs = 10000
settings.stored_time = 1.0
settings.pretrig_samples = 1000
settings.channels = 2  # Force and response

# 2. Acquire data (multiple impacts)
time_data_list = dvma.TimeDataList()
n_averages = 5

for i in range(n_averages):
    input("Press Enter for next impact...")
    data = dvma.log_data(settings, test_name=f"impact_{i}")
    time_data_list.append(data.time_data_list[0])

# 3. Calculate averaged FRF
tf_data = dvma.calculate_tf_averaged(time_data_list, ch_in=0)

# 4. Plot FRF and coherence
f = tf_data.freq_axis
H = tf_data.tf_data[:, 0]
coh = tf_data.tf_coherence[:, 0]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

ax1.semilogy(f, np.abs(H))
ax1.set_ylabel('|H(f)| (m/s²/N)')
ax1.set_title('Frequency Response Function')
ax1.grid(True)
ax1.set_xlim([0, 500])

ax2.plot(f, coh)
ax2.set_xlabel('Frequency (Hz)')
ax2.set_ylabel('Coherence')
ax2.set_ylim([0, 1])
ax2.grid(True)
ax2.set_xlim([0, 500])

plt.tight_layout()
plt.show()

# 5. Identify modes
from scipy.signal import find_peaks

# Find peaks in FRF
magnitude = np.abs(H)
peaks, properties = find_peaks(magnitude, height=np.max(magnitude)*0.1)

natural_frequencies = f[peaks]
print("Identified natural frequencies:")
for fn in natural_frequencies:
    print(f"  {fn:.2f} Hz")

# 6. Extract damping (from time data)
fn, Qn, fit_data = dvma.calculate_damping_from_sono(
    time_data_list[0],
    n_chan=1,
    nperseg=512
)

print("\nDamping analysis:")
for i, (freq, Q) in enumerate(zip(fn, Qn)):
    zeta = 1/(2*Q)
    print(f"  Mode {i+1}: f={freq:.2f} Hz, ζ={zeta:.4f}, Q={Q:.1f}")
```

## References and Further Reading

- Ewins, D.J. (2000). Modal Testing: Theory, Practice and Application
- Maia, N.M.M. & Silva, J.M.M. (1997). Theoretical and Experimental Modal Analysis
- Inman, D.J. (2013). Engineering Vibration

## Next Steps

- Learn about [Plotting and Visualization](plotting.md)
- See complete [Examples](../examples/advanced.md)
- Check [API Reference](../api/modal.md)
