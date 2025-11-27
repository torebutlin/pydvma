# Quick Start

This guide will help you get started with pydvma quickly.

## Opening the Template

The easiest way to get started is to use the provided Jupyter notebook template:

1. Navigate to your pydvma installation directory
2. Open `pydvma_template.ipynb` in Jupyter

Alternatively, you can start from scratch in any Jupyter notebook or Python script.

## Basic Setup

### Import and Configure

```python
import pydvma as dvma
import matplotlib.pyplot as plt
import numpy as np

# For interactive plots in Jupyter
%matplotlib qt
```

### Create Settings

```python
# Create default settings
settings = dvma.MySettings()

# Customize as needed
settings.fs = 10000  # Sampling frequency in Hz
settings.duration = 2.0  # Duration in seconds
settings.channels = 2  # Number of channels
```

### Launch the Logger

```python
# Create and launch the logger GUI
logger = dvma.Logger(settings)
```

This opens an interactive GUI where you can:

- Configure acquisition parameters
- Preview signals in real-time
- Record time-series data
- Perform FFT analysis
- Calculate transfer functions
- View sonograms
- Export data

## Your First Measurement

### Using the GUI

1. **Set up your hardware** - Connect your sensors/microphones
2. **Configure channels** - Use the channel settings in the GUI
3. **Preview signals** - Check signal levels before recording
4. **Record data** - Click the record button
5. **Analyze** - Switch between Time, FFT, and TF views

### Programmatic Recording

You can also record data programmatically:

```python
# Record data
dataset = dvma.log_data(settings, test_name="test_01")

# Access the recorded data
time_data = dataset.time_data_list[0]
t = time_data.time_axis
y = time_data.time_data

# Plot
plt.plot(t, y)
plt.xlabel('Time (s)')
plt.ylabel('Amplitude')
plt.show()
```

## Basic Analysis

### Compute FFT

```python
# Calculate FFT
freq_data = dvma.calculate_fft(time_data, window='hann')

# Plot
plt.figure()
plt.plot(freq_data.freq_axis, np.abs(freq_data.freq_data))
plt.xlabel('Frequency (Hz)')
plt.ylabel('Magnitude')
plt.xlim([0, 1000])
plt.yscale('log')
plt.show()
```

### Calculate Transfer Function

```python
# For multi-channel data, calculate transfer function
# Channel 0 is input, others are outputs
tf_data = dvma.calculate_tf(time_data, ch_in=0, window='hann')

# Plot magnitude
plt.figure()
plt.plot(tf_data.freq_axis, np.abs(tf_data.tf_data[:, 0]))
plt.xlabel('Frequency (Hz)')
plt.ylabel('|H(f)|')
plt.yscale('log')
plt.show()
```

### Generate Sonogram

```python
# Calculate sonogram (spectrogram)
sono_data = dvma.calculate_sonogram(time_data)

# Plot
plt.figure()
plt.pcolormesh(sono_data.time_axis, sono_data.freq_axis,
               20*np.log10(np.abs(sono_data.sono_data[:, :, 0])))
plt.ylabel('Frequency (Hz)')
plt.xlabel('Time (s)')
plt.colorbar(label='Magnitude (dB)')
plt.show()
```

## Saving and Loading Data

### Export to Matlab

```python
# Export dataset to Matlab format
dvma.export_to_matlab(dataset)
```

### Export to CSV

```python
# Export time data to CSV
dvma.export_to_csv(dataset.time_data_list)
```

## Next Steps

- Explore the [User Guide](../user-guide/acquisition.md) for more detailed information
- Check out [Examples](../examples/basic.md) for common use cases
- Review the [API Reference](../api/analysis.md) for function details
