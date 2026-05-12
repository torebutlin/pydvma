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

## Voltage-Based I/O

Since v1.2 both acquired data and generated output are in **volts**
everywhere — there is no ±1 normalisation step. Time series, FFTs,
transfer functions, output signals: all in volts (and then in
engineering units once `channel_cal_factors` is applied for display).

### NI inputs and outputs

* `settings.VmaxNI` (default `5 V`) is the AI task's full-scale range:
  the recorder is configured with `min_val=-VmaxNI`, `max_val=+VmaxNI`,
  and DAQmx will reject samples outside that range with error -200077.
  Pick the smallest range that covers your signal — smaller ranges
  give better resolution.
* `settings.output_VmaxNI` (default = `VmaxNI`) is the AO task's full
  scale. NI 9260, for example, is hard-limited to ±4.24 V; any
  `signal_generator(amplitude=X)` you ask for above
  `settings.output_VmaxNI` is clamped automatically and a message
  prints. `suggest_ni_settings(device_index)` returns safe defaults
  for the configured device.

### Soundcard inputs and outputs

`sounddevice` itself delivers samples in ±1 normalised float32 — but
pydvma scales those to volts using a per-instance calibration constant
so the downstream code only ever sees voltages:

* `settings.VmaxSC` (default `1.0`) is the input-side calibration:
  the voltage at the jack corresponding to a normalised reading of
  1.0. Default `1.0` means "treat normalised as volts at unit scale"
  — identical numeric behaviour to a pre-v1.2 capture. Once you've
  measured your soundcard's input sensitivity, set this and
  acquisitions become calibrated.
* `settings.output_VmaxSC` (default = `VmaxSC`) is the output-side
  calibration: `output_signal` divides the requested voltage waveform
  by `output_VmaxSC` to recover the ±1 sounddevice expects.

### IEPE / ICP excitation (NI DSA modules)

The NI 9234 (and other DSA modules with internal excitation) can
power IEPE/ICP accelerometers directly. Set per-channel current via:

```python
settings = dvma.MySettings(
    device_driver='nidaq',
    channels=4,
    iepe_excit_current_A=[0.002, 0.002, 0.0, 0.0],  # 2 mA on ai0/ai1
)
```

Channels with `> 0` are switched to AC coupling and the recorder
blocks for ~2 s after task start to let the sensor's DC bias settle
through the AC-coupling HPF before reading. Subsequent `log_data`
calls with matching hardware settings reuse the live task and skip
the warm-up. The 9234 only accepts the discrete values `0.0` and
`0.002`; other values raise a clear error.

### Clipping detection

`log_data` checks the captured buffer against `0.95 * input_vmax()`
(where `input_vmax()` returns `VmaxNI` on NI / `VmaxSC` on soundcard)
and prints a `WARNING: Data may be clipped` message if any sample
sits within 5 % of the rails. The output-side `signal_generator`
applies the same kind of safety clamp at `output_vmax()` so any
hand-rolled waveform you pass via `output=...` is implicitly bounded.

### Quick reference

| Field                    | Path     | Default | What it means                            |
| ------------------------ | -------- | ------- | ---------------------------------------- |
| `VmaxNI`                 | input    | `5`     | NI AI full-scale (volts)                 |
| `VmaxSC`                 | input    | `1.0`   | Soundcard input cal: V at norm = 1       |
| `output_VmaxNI`          | output   | `VmaxNI`| NI AO full-scale (volts)                 |
| `output_VmaxSC`          | output   | `VmaxSC`| Soundcard output cal: V at norm = 1      |
| `channel_sensitivities`  | input    | `1.0`   | V/eu per channel — see below             |
| `iepe_excit_current_A`   | input    | `0.0`   | IEPE excitation per channel (NI 9234 etc.) |

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

### Oscilloscope view

The Logger GUI provides a live oscilloscope of the incoming signal —
launch the GUI and use the Oscilloscope view to monitor levels and
adjust trigger settings before committing to a recording.

```python
logger = dvma.Logger(settings)
```

For a one-shot programmatic peek at the live buffer without going via
the GUI, use `dvma.stream_snapshot(streams.REC)` while a stream is
running (e.g. immediately after a `log_data` call).

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
