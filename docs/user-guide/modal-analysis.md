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

For fitting a single mode across all channels from a list of transfer functions:

```python
# Fit a single mode for all channels (returns single ModalData object)
modal_data = dvma.modal_fit_all_channels(
    tf_data_list,
    freq_range=[180, 220],
    measurement_type='acc'  # 'acc', 'vel', or 'dsp'
)

# Review results (fn and zn are arrays, one element per fitted mode)
print(f"Natural frequency: {modal_data.fn[0]:.2f} Hz")
print(f"Damping ratio: {modal_data.zn[0]:.4f}")
print(f"Modal constants: {modal_data.an}")
```

## Beyond SDOF: not yet built in

Mode-shape extraction, the Modal Assurance Criterion (MAC), and
Operating Deflection Shape (ODS) plotting are common next steps after
SDOF fitting. pydvma doesn't ship those as helpers yet — they're on
the roadmap (see `TODO.md`: "mode-shape plotter", "MAC helper", "ODS
helper"). Starter recipes that operate on `TfData` / `ModalData`
output live in `dev/mode-shape-sketches.md`; they're suitable as a
basis when these are built up into proper APIs.

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
