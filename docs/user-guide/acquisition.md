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

#### Finding your device index

`device_index` is an index into the NI device list **as nidaqmx
enumerates it, with each cDAQ chassis collapsed to a single entry**.
Don't guess — print the list (its `nidaq` section is indexed exactly the
way `device_index` expects):

```python
dvma.list_available_devices()
# ...
# Devices available using device_driver='nidaq', by index:
# 0: cDAQ1 (cDAQ-9174, chassis) AI=4 AO=2 modules=['cDAQ1Mod1', 'cDAQ1Mod2']
# 1: Dev1 (USB-6003, device) AI=8 AO=2
```

Here the chassis is `device_index=0` and the USB-6003 is `device_index=1`.
(`dvma.get_devices_NI()` exists too but returns a *flat* list that lists
the chassis and each module separately, so its indices do **not** match
`device_index` — use `list_available_devices()` for choosing the index.)

`dvma.suggest_ni_settings(device_index)` then returns safe ranges, rate
and terminal mode for whatever is at that index (see below).

### Terminal Configuration

```python
# Referenced Single-Ended (default)
settings.NI_mode = 'DAQmx_Val_RSE'

# Differential
settings.NI_mode = 'DAQmx_Val_Diff'

# Non-referenced single-ended
settings.NI_mode = 'DAQmx_Val_NRSE'
```

### cDAQ chassis with multiple modules

A CompactDAQ chassis is addressed as a **single device** — use the one
`device_index` for the chassis, not one per module. `channels=N` is
then consumed across the chassis's AI modules **in slot order**, so a
chassis with two 4-channel AI modules (e.g. two NI 9234s) gives eight
channels that span both modules automatically:

```python
settings = dvma.MySettings(
    device_driver='nidaq',
    device_index=0,        # the chassis (one logical device)
    channels=8,            # spans both AI modules
    NI_mode='DAQmx_Val_PseudoDiff',   # required by the 9234 (see below)
    VmaxNI=5,              # the 9234 is fixed at ±5 V
    fs=12800,
)
```

The captured array's columns follow slot order. With a chassis whose
slots are `Mod1` (4-ch AI), `Mod2` (AO), `Mod4` (4-ch AI), the AI task
skips the AO-only module and maps:

| Column | Physical channel |
| ------ | ---------------- |
| 0–3    | `Mod1/ai0`–`ai3` |
| 4–7    | `Mod4/ai0`–`ai3` |

So an accelerometer wired to the second module's `ai1` is **column 5**
of `time_data`, and any per-channel setting (`iepe_excit_current_A`,
`channel_sensitivities`, `pretrig_channel`) is indexed the same way.
`AO`-only modules in the middle of the chassis are simply skipped when
counting AI channels (and vice-versa for output).

#### Sensible defaults: `suggest_ni_settings`

`suggest_ni_settings(device_index)` inspects the configured device and
returns safe, in-range values (terminal config, full-scale ranges,
sample rate) you can splat straight into `MySettings`:

```python
kwargs = dvma.suggest_ni_settings(0)        # for chassis at index 0
settings = dvma.MySettings(channels=8, **kwargs)
```

For the lab cDAQ (two 9234s + a 9260 AO) this yields
`NI_mode='DAQmx_Val_PseudoDiff'`, `VmaxNI=5`, `output_VmaxNI≈4.24`, and a
rate on the 9234's discrete ladder.

#### NI 9234 / DSA module constraints

Delta-sigma (DSA) modules like the 9234 differ from the multiplexed
USB-600x/621x devices, and pydvma enforces or depends on several of
their quirks:

- **Pseudo-differential only** — set `NI_mode='DAQmx_Val_PseudoDiff'`.
  Other terminal modes are rejected.
- **Fixed ±5 V range** — `VmaxNI` other than `5` is silently accepted
  by the driver but does not change the hardware range.
- **Simultaneous sampling** — every channel has its own ADC, so all
  channels (across both modules, via the chassis timebase) are sampled
  at the same instant; there is no inter-channel skew like the
  multiplexed USB DAQs.
- **Automatic anti-alias filter** — the brick-wall AA filter is locked
  to the sample rate and is not user-configurable. AC coupling adds a
  ~0.5 Hz high-pass.
- **Discrete sample-rate ladder** — the 9234 only runs at rates on its
  internal divider ladder; the driver coerces `fs` to the nearest
  legal value rather than running arbitrary rates.

#### Non-standard / gappy layouts

The count-based `channels=N` assumes each module is filled from `ai0`
upward. If you need a non-contiguous set (skip a channel, start partway
into a module, mix specific channels across modules), bypass the
builder with an explicit DAQmx physical-channel string:

```python
settings.input_channels_spec  = 'cDAQ1Mod1/ai0:3,cDAQ1Mod4/ai1'  # AI
settings.output_channels_spec = 'cDAQ1Mod2/ao0'                  # AO
```

When set, these override the auto-constructed channel strings verbatim
(nidaqmx backend only).

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

### Custom NumPy output

`signal_generator` is convenient but limited — three shapes
(`'gaussian'`, `'uniform'`, `'sweep'`), a single amplitude and an
optional band. For anything else (arbitrary multi-tone, a measured or
imported waveform, per-channel-different drives, an MLS sequence, a
stepped sine…) build the array yourself and pass it to
`log_data(..., output=...)`. The format `log_data` expects is small but
strict:

| Requirement | Detail |
| ----------- | ------ |
| **Shape** | 2-D `(N_samples, output_channels)` — one **column per AO channel**, even for a single channel (use `arr[:, None]`). The column count must equal `settings.output_channels`. |
| **Units** | **Volts** — there is no ±1 normalisation. A value of `2.5` means 2.5 V at the terminal. |
| **Sample rate** | The array is clocked out at `settings.output_fs` (defaults to `fs`). Build the time base with `1 / settings.output_fs`, and make it ≈ `stored_time` long to span the capture. |
| **Range** | Every sample must lie within ±`settings.output_vmax()` (`output_VmaxNI` on NI, `output_VmaxSC` on soundcard). On NI, out-of-range samples are rejected by DAQmx (error -200077). |
| **dtype** | Any float — cast internally (to volts on NI, to ±1 `float32` on the soundcard). |

!!! warning "A hand-built array gets no ramp and no safety clamp"
    `signal_generator` fades its waveform in/out and clamps to
    full-scale for you. A raw array does **neither** — you own both. A
    discontinuity at the first or last sample will click and can ring
    the structure, so window the ends yourself for transient-sensitive
    work, and keep the signal inside ±`output_vmax()`.

```python
import numpy as np

fs   = settings.output_fs       # output clock (defaults to settings.fs)
T    = settings.stored_time     # match the capture length
vmax = settings.output_vmax()   # full-scale output, in volts
t    = np.arange(0, T, 1 / fs)

# --- build any waveform you like, in volts ---
# multi-tone: 100 + 220 + 505 Hz, 0.3 V peak each
tones = np.array([100.0, 220.0, 505.0])
y = 0.3 * np.sin(2 * np.pi * np.outer(t, tones)).sum(axis=1)

# raised-cosine fade over the first/last 10 ms to avoid a click
n_ramp = int(0.01 * fs)
ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, n_ramp)))
y[:n_ramp]  *= ramp
y[-n_ramp:] *= ramp[::-1]

# stay inside the rails — there is no auto-clamp on a custom array
y = np.clip(y, -vmax, vmax)

output = y[:, None]             # -> (N, 1): a single AO channel
dataset = dvma.log_data(settings, output=output)
```

**Multiple output channels** — one column per channel, with
`settings.output_channels` set to match. For example a 50 Hz sine on
`ao0` and an independent noise drive on `ao1`:

```python
settings.output_channels = 2
a = 0.5 * np.sin(2 * np.pi * 50 * t)
b = np.clip(0.1 * np.random.randn(t.size), -vmax, vmax)
output = np.column_stack([a, b])   # (N, 2): columns map to ao0, ao1
dataset = dvma.log_data(settings, output=output)
```

!!! tip "Record the drive as a reference channel"
    Set `settings.use_output_as_ch0 = True` and the played `output` is
    prepended as channel 0 of the returned data — useful for transfer
    functions, where you want the excitation captured alongside the
    response rather than assumed. The prepended column passes through
    uncalibrated (cal factor 1).

### Output via the Logger GUI

The desktop Logger drives output from its **"Generate output"** panel
rather than from a `signal_generator` / `log_data(output=...)` call.
Pre-fill that panel by passing an `Output_Signal_Settings` when you open
the Logger:

```python
oss = dvma.Output_Signal_Settings(
    type='gaussian',   # 'None' | 'sweep' | 'gaussian' | 'uniform'
    amp=0.1,           # peak amplitude in volts (clamped to output_vmax())
    f1=100,            # sweep start / noise lower band corner (Hz)
    f2=300,            # sweep end   / noise upper band corner (Hz)
)
logger = dvma.Logger(settings, output_signal_settings=oss)
```

The panel's **Type** drop-down, **Amplitude**, **f1** and **f2** fields
open populated from those values. **Preview** plots the waveform and its
FFT; **Generate output** plays it (the GUI refuses a maximum frequency
above Nyquist, `fs/2`). Under the hood it calls the same
`signal_generator` shown above — `type` becomes `sig` and `[f1, f2]`
becomes `f`.

A few notes:

- **Duration is a separate panel field**, so it is *not* part of
  `Output_Signal_Settings` — set it in the GUI (it is `T=` when
  scripting `signal_generator`).
- The four `type` values are exactly `'None'`, `'sweep'`, `'gaussian'`
  and `'uniform'`. `'None'` (the default) opens the Logger with output
  off — equivalent to omitting `output_signal_settings` entirely.
- `Output_Signal_Settings` is **GUI-only**. For scripted/headless output
  use the array path above; the two are independent.

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

On a multi-module chassis the list is indexed in the same slot order
as the captured columns (see
[cDAQ chassis with multiple modules](#cdaq-chassis-with-multiple-modules)),
and each requested current is validated against the module that
actually supplies that channel — so an accelerometer on the second AI
module is enabled by setting the current at its column index, e.g.
`iepe_excit_current_A[5] = 0.002` for `Mod4/ai1`. **Do not enable IEPE
on a channel that is wired to an AO output** (e.g. a loopback test
channel): the excitation current is driven back into the AO terminal.
Leave loopback/driven channels at `0.0`.

!!! warning "IEPE must-knows"
    - **Only enable excitation on channels with an actual ICP/IEPE
      sensor.** A charge/voltage input (force hammer, signal generator,
      loopback to an AO) must stay at `0.0` — forcing 2 mA into a
      non-ICP input can damage it.
    - **Legal currents on the 9234 are exactly `0.0` or `0.002` A**
      (off / 2 mA). Any other value raises a clear error, validated
      against the module that actually owns each channel.
    - **The list is positional — one entry per channel** in
      captured-column (slot) order; a scalar broadcasts to every
      channel.
    - Enabling a channel switches it to **AC coupling** and adds a ~2 s
      bias-settle on the first capture.
    - `iepe_excit_current_A > 0` requires `device_driver='nidaq'` and a
      DSA module; soundcard inputs have no configurable excitation.

### Worked example: IEPE accelerometers on a cDAQ

End-to-end recipe for the most common DSA setup — ICP/IEPE
accelerometers powered straight off an NI 9234 in a cDAQ chassis, with
per-channel calibration so results come out in engineering units.
Suppose the chassis is at `device_index=0`, its first module
(`cDAQ1Mod1`) is a 4-channel 9234, and you have two 100 mV/g
accelerometers on `ai0`/`ai1` plus a 2.3 mV/N force hammer on `ai2`:

```python
import pydvma as dvma

# 1. Confirm the chassis index, and grab safe range/rate/mode for it.
dvma.list_available_devices()          # -> the chassis is index 0
base = dvma.suggest_ni_settings(0)      # PseudoDiff, VmaxNI=5, a 9234-legal fs, ...

# 2. Three channels: IEPE on the two accelerometers only, and
#    per-channel sensitivities in volts per engineering unit.
settings = dvma.MySettings(
    channels=3,
    iepe_excit_current_A=[0.002, 0.002, 0.0],  # 2 mA on ai0/ai1; hammer is not ICP
    channel_sensitivities=[0.1, 0.1, 0.0023],  # 100 mV/g, 100 mV/g, 2.3 mV/N
    stored_time=2.0,
    **base,            # device_driver='nidaq', device_index=0, NI_mode, VmaxNI, fs, ...
)

# 3. Record. log_data powers the ICP sensors, switches their channels to
#    AC coupling, and blocks ~2 s for the bias to settle before capturing.
dataset = dvma.log_data(settings, test_name='hammer_test_01')

# 4. Samples are stored in volts; cal factors [10, 10, 434.8] are attached,
#    so plots/FFTs/TFs read in engineering units automatically.
dataset.time_data_list[0].channel_cal_factors        # array([ 10. , 10. , 434.78])
dataset.time_data_list[0].units = ['g', 'g', 'N']    # optional axis labels
dataset.plot_time_data()
```

What this relies on, all covered above:

- **Index by capture column, not by terminal label.** `channels=3`
  consumes `cDAQ1Mod1/ai0:2`, so list position 0→`ai0`, 1→`ai1`,
  2→`ai2`. The same index drives `iepe_excit_current_A`,
  `channel_sensitivities` and `pretrig_channel`. If sensors span two AI
  modules the indices keep counting across the slot boundary (see
  [the channel-mapping table](#cdaq-chassis-with-multiple-modules)).
- **IEPE only where there's an ICP sensor.** The force hammer is a
  voltage/charge input, so its channel stays at `0.0` (DC-coupled, no
  excitation). Forcing 2 mA into a non-ICP input can damage it.
- **`suggest_ni_settings` does the 9234 housekeeping** (`PseudoDiff`,
  `VmaxNI=5`, an `fs` on the module's discrete ladder) so you don't have
  to recall the DSA constraints each time. Override any of its keys by
  listing them after `**base`.

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
`1.0` means "no calibration applied" (cal_factor = 1). Every value must
be non-zero (a zero sensitivity would mean an infinite cal factor), so
use `1.0`, not `0.0`, for "leave this channel uncalibrated".

!!! tip "Reading sensitivity off the cal sheet"
    Manufacturers usually print sensitivity in **mV per unit** — divide
    by 1000 to get the V/eu value pydvma expects. A `100 mV/g`
    accelerometer is `0.1`, a `10 mV/g` one is `0.01`, and a `2.3 mV/N`
    force transducer is `0.0023`. (A common slip is entering `100`
    instead of `0.1` — that would scale your results by 1000×.)

#### How calibration is stored and applied

`channel_sensitivities` is consumed **once, at logging time**: `log_data`
computes `channel_cal_factors = 1 / channel_sensitivities` and stores
them on the resulting `TimeData`. The raw `time_data` array is always
kept in **volts** — the cal factors are applied lazily, multiplied in
only when data is **displayed or fitted**:

- **Plotting** multiplies each channel by its cal factor, so the axes
  read in engineering units.
- **`calculate_fft`**, **`calculate_cross_spectrum_matrix`** and
  **`calculate_sonogram`** copy the cal factors (and `units`) onto the
  derived `FreqData`, so spectra are scaled the same way.
- **`calculate_tf`** inherits the calibration *ratio*: the stored
  per-output factor is `cal[ch_out] / cal[ch_in]`, so a transfer
  function is automatically in output-eu / input-eu (e.g. a `g/N`
  accelerance from a `g` response and an `N` drive).

Because the stored samples stay in volts, calibration is
non-destructive: you can change it after the fact without re-recording,
and `VmaxNI` clip-checking still works against the true voltage.

#### Setting or correcting calibration after logging

If you recorded without sensitivities (or fixed a wrong value), set the
**cal factor** directly on the data list. Note this is the *reciprocal*
of sensitivity (engineering-units per volt), because it is the
multiplier applied to the stored volts — a 100 mV/g accelerometer
(0.1 V/g) has a cal factor of 10:

```python
# One channel of one set (set index and channel index are both 0-based):
dataset.time_data_list.set_calibration_factor(10, n_set=0, n_chan=0)

# Inspect, or set a whole list at once:
factors = dataset.time_data_list.get_calibration_factors()
dataset.time_data_list.set_calibration_factors_all(factors)
```

The same `get_calibration_factors` / `set_calibration_factor` /
`set_calibration_factors_all` API exists on `freq_data_list` and
`tf_data_list` for adjusting already-computed spectra.

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
