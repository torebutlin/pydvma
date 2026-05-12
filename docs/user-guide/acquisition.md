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
settings.device_driver = 'soundcard'
settings.fs = 44100  # Typical soundcard sample rate
settings.stored_time = 2.0
settings.channels = 2
```

### Listing Available Devices

```python
import sounddevice as sd

# List all available devices
print(sd.query_devices())

# Set specific device by index
settings.device_index = 1  # Use the index from sd.query_devices()
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
- nidaqmx Python package (`pip install nidaqmx`)
- Windows operating system

### Configuration

```python
settings = dvma.MySettings()
settings.device_driver = 'nidaq'
settings.device_index = 0  # Device index (typically 0 for first NI device)
settings.fs = 10000
settings.stored_time = 2.0
settings.channels = 4

# Voltage range (maximum voltage)
settings.VmaxNI = 10  # ±10V range
```

### Terminal Configuration

```python
# Referenced Single-Ended (default)
settings.NI_mode = 'DAQmx_Val_RSE'

# Differential
settings.NI_mode = 'DAQmx_Val_Diff'

# Non-referenced single-ended
settings.NI_mode = 'DAQmx_Val_NRSE'
```

## Triggered Acquisition

### Pre-trigger Recording

Useful for capturing transient events like impacts:

```python
settings.pretrig_samples = 2000  # Samples to keep before trigger

# Set trigger parameters
settings.pretrig_threshold = 0.5  # Voltage threshold
settings.pretrig_channel = 0      # Channel to monitor
settings.pretrig_timeout = 20     # Timeout in seconds
```

When recording starts, the system continuously buffers data. When the trigger condition is met (signal exceeds threshold), it saves the pre-trigger samples plus the post-trigger duration.

## Output Generation

Generate signals during acquisition (e.g., for transfer function measurements). The built-in generator supports `sig='gaussian'`, `'uniform'`, or `'sweep'` and returns `(t, output)` where `output` has shape `(samples, settings.output_channels)`.

`amplitude` is in **volts**; the generator clamps the waveform to `±settings.output_vmax()` (= `output_VmaxNI` on NI, `output_VmaxSC` on the soundcard) so it can never drive the hardware past its rails.

### Gaussian White Noise Output

```python
# Generate ~0.1 V RMS white noise
t, output = dvma.signal_generator(
    settings,
    sig='gaussian',
    T=settings.stored_time,
    amplitude=0.1     # volts
)

# Record with output
dataset = dvma.log_data(settings, output=output)
```

### Sine Sweep (Chirp) Output

```python
# Generate ±0.5 V sine sweep from f1 to f2
t, output = dvma.signal_generator(
    settings,
    sig='sweep',
    T=settings.stored_time,
    amplitude=0.5,     # volts (peak)
    f=[10, 1000]       # start and end frequencies (Hz)
)

# Record with output
dataset = dvma.log_data(settings, output=output)
```

### Custom Waveform

```python
import numpy as np

# Create custom single-channel waveform (2D array expected)
t = np.arange(0, settings.stored_time, 1 / settings.output_fs)
carrier = 0.5 * np.sin(2 * np.pi * 50 * t)
output = carrier[:, None]  # (samples, channels)

# Example: multi-tone signal
tones = np.array([100, 200, 500])
multitone = 0.2 * np.sin(2 * np.pi * tones[:, None] * t).sum(axis=0)
output = multitone[:, None]

# Record with custom output
dataset = dvma.log_data(settings, output=output)
```

## Calibration and Scaling

### Sensor sensitivity

Pass per-channel sensitivity (in V/eu — volts per engineering unit) to
`MySettings` at acquisition time. `log_data` inverts it into
`TimeData.channel_cal_factors`, and plotting / modal fitting multiply
by those factors automatically, so the displayed values are in
engineering units (g, m/s², N, ...) without any post-hoc scaling.

```python
settings = dvma.MySettings(
    channels=3,
    channel_sensitivities=[0.1, 0.1, 0.0023],  # V/g, V/g, V/N
)
dataset = dvma.log_data(settings)
# dataset.time_data_list[0].channel_cal_factors is [10, 10, 434.78]
```

A scalar `channel_sensitivities=X` broadcasts to all channels. Default
`1.0` means "no calibration applied" (cal_factor = 1).

### Engineering-unit labels

`TimeData.units` accepts a per-channel list of strings; it propagates
through `calculate_fft`, `calculate_cross_spectrum_matrix`, and
`calculate_sonogram`, and `calculate_tf` builds units like
``"<out_unit>/<in_unit>"`` per output channel.

```python
# Set units after acquisition if you didn't pass them via MySettings
time_data.units = ['g', 'g', 'N']
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
settings.stored_time = 1.0 / df  # Minimum duration needed
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
