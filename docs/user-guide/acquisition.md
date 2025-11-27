# Data Acquisition

This guide covers data acquisition using different hardware interfaces.

## Hardware Support

pydvma supports multiple acquisition hardware:

- **Soundcards**: Using the sounddevice library
- **National Instruments DAQ**: Using NI-DAQmx (Windows only)

## Soundcard Acquisition

### Basic Setup

```python
import pydvma as dvma

settings = dvma.MySettings()
settings.device = 'soundcard'
settings.fs = 44100  # Typical soundcard sample rate
settings.duration = 2.0
settings.channels = 2
```

### Listing Available Devices

```python
import sounddevice as sd

# List all available devices
print(sd.query_devices())

# Set specific device
settings.input_device_name = 'USB Audio Device'
```

### Recording

```python
# Using the GUI
logger = dvma.Logger(settings)

# Programmatically
dataset = dvma.log_data(settings, test_name="recording_01")
```

## National Instruments DAQ

### Requirements

- NI-DAQmx driver installed
- pydaqmx Python package
- Windows operating system

### Configuration

```python
settings = dvma.MySettings()
settings.device = 'nidaq'
settings.device_name = 'Dev1'  # Your device name
settings.fs = 10000
settings.duration = 2.0
settings.channels = 4

# Specify physical channels
settings.channel_names = ['ai0', 'ai1', 'ai2', 'ai3']

# Voltage range
settings.voltage_range = [-10, 10]
```

### Terminal Configuration

```python
# Single-ended (default)
settings.terminal_config = 'RSE'  # Referenced Single-Ended

# Differential
settings.terminal_config = 'DIFF'

# Non-referenced single-ended
settings.terminal_config = 'NRSE'
```

## Triggered Acquisition

### Pre-trigger Recording

Useful for capturing transient events like impacts:

```python
settings.pretrig_samples = 2000  # Samples to keep before trigger

# Set trigger parameters
settings.trigger_level = 0.5     # Voltage threshold
settings.trigger_channel = 0     # Channel to monitor
settings.trigger_slope = 'rising'  # or 'falling'
```

When recording starts, the system continuously buffers data. When the trigger condition is met, it saves the pre-trigger samples plus the post-trigger duration.

### Post-trigger Delay

```python
settings.posttrig_delay = 0.1  # Delay in seconds after trigger
```

## Output Generation

Generate signals during acquisition (e.g., for transfer function measurements):

### Sine Wave Output

```python
settings.output_enabled = True
settings.output_type = 'sine'
settings.output_frequency = 100  # Hz
settings.output_amplitude = 0.5  # Voltage
settings.output_channel = 0
```

### Chirp Output

```python
settings.output_type = 'chirp'
settings.output_f_start = 10     # Start frequency (Hz)
settings.output_f_end = 1000     # End frequency (Hz)
settings.output_amplitude = 0.5
```

### White Noise Output

```python
settings.output_type = 'white_noise'
settings.output_amplitude = 0.1
```

### Custom Waveform

```python
import numpy as np

# Create custom signal
t = np.linspace(0, settings.duration, int(settings.fs * settings.duration))
custom_signal = 0.5 * np.sin(2 * np.pi * 50 * t)

settings.output_type = 'custom'
settings.output_signal = custom_signal
```

## Calibration and Scaling

### Sensor Sensitivity

Apply sensor sensitivity calibration:

```python
# Accelerometer sensitivity: 100 mV/g
sensitivity_accel = 100e-3  # V/g

# After recording
time_data.time_data[:, 0] /= sensitivity_accel  # Convert to g
```

### Engineering Units

```python
# Store channel information
time_data.channel_names = ['Accel_X', 'Accel_Y', 'Force']
time_data.channel_units = ['g', 'g', 'N']
```

## Multiple Measurements

### Recording Multiple Datasets

```python
# Create dataset to hold multiple measurements
dataset = dvma.DataSet()

for i in range(10):
    # Record
    data = dvma.log_data(settings, test_name=f"test_{i:02d}")

    # Add to dataset
    dataset.time_data_list.append(data.time_data_list[0])
```

### Batch Processing

```python
# Process all measurements
for i, time_data in enumerate(dataset.time_data_list):
    # Calculate FFT for each
    freq_data = dvma.calculate_fft(time_data)
    dataset.freq_data_list.append(freq_data)
```

## Monitoring and Visualization

### Real-time Preview

The Logger GUI provides real-time visualization:

```python
logger = dvma.Logger(settings)
# Use the "Preview" button to see signals in real-time
```

### Oscilloscope View

Monitor input signals before recording:

```python
# In the GUI, use the "Oscilloscope" tab
# Adjust trigger levels and time scales interactively
```

## Best Practices

### Sample Rate Selection

Choose appropriate sample rates:

- **Audio/vibration**: 10-50 kHz
- **Ultrasonic**: 100+ kHz
- **Slow processes**: 1-10 Hz

Remember Nyquist: sample at least 2× the highest frequency of interest.

### Duration Selection

```python
# For frequency resolution Δf
df = 1.0  # Hz resolution desired
settings.duration = 1.0 / df  # Minimum duration needed
```

### Anti-aliasing

Ensure hardware anti-aliasing filters are enabled or use appropriate sample rates to avoid aliasing.

### Grounding and Shielding

- Use proper grounding to reduce noise
- Shield cables for low-level signals
- Keep signal cables away from power cables

## Troubleshooting

### No Signal Detected

1. Check connections
2. Verify device settings
3. Check input range/sensitivity
4. Test with known signal source

### Clipping/Saturation

- Reduce input signal amplitude
- Adjust voltage range settings
- Check sensor sensitivity

### High Noise Floor

- Improve grounding
- Use differential inputs
- Shield cables
- Reduce gain if possible
- Check for ground loops

### Trigger Not Working

- Adjust trigger level
- Check trigger channel
- Verify signal amplitude
- Try different trigger slope

## Next Steps

- Learn about [Data Analysis](analysis.md)
- Explore [Examples](../examples/basic.md)
