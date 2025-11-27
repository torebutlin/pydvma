# Basic Usage

This page covers fundamental concepts and common usage patterns in pydvma.

## Core Concepts

### Data Structure Hierarchy

pydvma uses a hierarchical data structure:

- **DataSet**: Top-level container holding all data
- **TimeData**: Time-domain measurements
- **FreqData**: Frequency-domain data (from FFT)
- **TfData**: Transfer function data
- **SonoData**: Sonogram/spectrogram data

Each data type includes:
- The data itself
- Axis information (time/frequency)
- Settings and metadata
- Unique identifiers for traceability

### Settings Object

The `MySettings()` object controls acquisition and analysis parameters:

```python
settings = dvma.MySettings()

# Acquisition settings
settings.fs = 10000          # Sampling frequency (Hz)
settings.stored_time = 2.0   # Duration (seconds)
settings.channels = 2        # Number of channels
settings.pretrig_samples = 1000  # Pre-trigger samples

# Device settings
settings.device_driver = 'soundcard'  # or 'nidaq'
settings.device_index = None  # None for default device
```

## Working with Different Data Types

### Time Data

```python
# Access time data from dataset
time_data = dataset.time_data_list[0]

# Data components
t = time_data.time_axis        # Time vector
y = time_data.time_data        # Signal data (samples x channels)
fs = time_data.settings.fs     # Sampling frequency

# Channel indexing
channel_0 = y[:, 0]  # First channel
channel_1 = y[:, 1]  # Second channel
```

### Frequency Data

```python
# Calculate FFT
freq_data = dvma.calculate_fft(time_data, window='hann')

# Data components
f = freq_data.freq_axis        # Frequency vector
Y = freq_data.freq_data        # Complex frequency data
magnitude = np.abs(Y)          # Magnitude spectrum
phase = np.angle(Y)            # Phase spectrum
```

### Transfer Function Data

```python
# Calculate transfer function (input on channel 0)
tf_data = dvma.calculate_tf(time_data, ch_in=0, window='hann')

# Data components
f = tf_data.freq_axis              # Frequency vector
H = tf_data.tf_data               # Complex transfer function
coherence = tf_data.tf_coherence  # Coherence function

# Plot FRF
magnitude = np.abs(H[:, 0])
plt.loglog(f, magnitude)
```

## Windowing

Windows reduce spectral leakage in FFT analysis:

```python
# No window (rectangular)
freq_data = dvma.calculate_fft(time_data, window=None)

# Hann window (good general purpose)
freq_data = dvma.calculate_fft(time_data, window='hann')

# Blackman window (better frequency resolution)
freq_data = dvma.calculate_fft(time_data, window='blackman')
```

Common windows:
- `None` or `'boxcar'`: Rectangular (no window)
- `'hann'`: Good general purpose
- `'hamming'`: Similar to Hann
- `'blackman'`: Better frequency resolution, more smoothing

## Averaging

### Frame Averaging for Better SNR

```python
# Calculate transfer function with averaging
tf_data = dvma.calculate_tf(
    time_data,
    ch_in=0,
    window='hann',
    N_frames=8,      # Average over 8 frames
    overlap=0.5      # 50% overlap between frames
)
```

### Ensemble Averaging

For repeated measurements (e.g., impact hammer tests):

```python
# Create list of measurements
time_data_list = dvma.TimeDataList()
for i in range(10):
    # Record 10 impacts
    data = dvma.log_data(settings, test_name=f"impact_{i}")
    time_data_list.append(data.time_data_list[0])

# Calculate averaged transfer function
tf_data_avg = dvma.calculate_tf_averaged(
    time_data_list,
    ch_in=0,
    window='hann'
)
```

## Integration and Differentiation

Convert between acceleration, velocity, and displacement:

```python
# Start with acceleration data
freq_data = dvma.calculate_fft(time_data_accel)

# Integrate to velocity (multiply by 1/(iω))
freq_data_vel = dvma.multiply_by_power_of_iw(
    freq_data,
    power=-1,
    channel_list=[0, 1]  # Channels to process
)

# Integrate again to displacement (multiply by 1/(iω)²)
freq_data_disp = dvma.multiply_by_power_of_iw(
    freq_data,
    power=-2,
    channel_list=[0, 1]
)

# Differentiate (multiply by iω)
freq_data_diff = dvma.multiply_by_power_of_iw(
    freq_data,
    power=1,
    channel_list=[0, 1]
)
```

## Time Range Selection

Analyze specific portions of your data:

```python
# Define time range
time_range = np.array([0.5, 1.5])  # From 0.5s to 1.5s

# Calculate FFT for selected range
freq_data = dvma.calculate_fft(time_data, time_range=time_range)

# Works for transfer functions too
tf_data = dvma.calculate_tf(time_data, ch_in=0, time_range=time_range)
```

## Best Match Scaling

When comparing multiple datasets, automatically scale them to match:

```python
# Create list of transfer functions
tf_list = dvma.TfDataList()
tf_list.append(tf_data_1)
tf_list.append(tf_data_2)
tf_list.append(tf_data_3)

# Get scale factors (relative to set 0, channel 0)
factors = dvma.best_match(
    tf_list,
    freq_range=[100, 500],  # Frequency range for matching
    set_ref=0,              # Reference dataset
    ch_ref=0                # Reference channel
)

# Apply scaling
for i, factor in enumerate(factors):
    tf_list[i].tf_data *= factor[:, None]
```

## Next Steps

- Learn about specific tasks in the [User Guide](../user-guide/acquisition.md)
- Explore [Examples](../examples/basic.md) for complete workflows
- Dive into the [API Reference](../api/analysis.md) for detailed function documentation
