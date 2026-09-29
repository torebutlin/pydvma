# Data Acquisition

This guide covers recording from Python with `dvma.log_data`, using sound
cards and NI hardware. For point-and-click recording, start the web
logger from your notebook with `dvma.launch(settings)`
([Running locally](../web-logger/running-locally.md)).

Set every option when you create `MySettings`, as in the examples below.
[Python basics](../getting-started/basic-usage.md#settings) explains why
assigning to `settings.fs` and the like afterwards goes wrong.

## Hardware Support

- **Sound cards and audio interfaces**, through the sounddevice library
  (`pip install "pydvma[soundcard]"`). On macOS, pydvma also asks
  CoreAudio for the device's true rate ladder and pins its clock to the
  capture rate while the stream runs, restoring it afterwards.
- **National Instruments DAQ**, through NI-DAQmx (`pip install "pydvma[ni]"`).

## Soundcard Acquisition

### Basic Setup

```python
import pydvma as dvma

settings = dvma.MySettings(
    device_driver='soundcard',
    fs=44100,            # a typical soundcard rate
    stored_time=2.0,     # seconds per recording
    channels=2,
)
```

### Listing Available Devices

Start here, before writing any settings:

```python
dvma.list_available_devices()
```

It reports one block per *physical* device rather than one line per
enumeration slot, and for each one it says what pydvma actually knows:

```text
  Line (U24XL with SPDIF I/O)   [ESI U24 XL]
    calibration : CHARACTERISED  full scale 1.8819 V peak, fixed gain
    hardware    : clocks 8000/16000/32000/44100/48000 Hz
    >> index 27  Windows WDM-KS       delivers 44100/48000     24-bit, refuses rates it cannot clock
       index 23  Windows WASAPI       delivers 8000/16000/32000/44100/48000
       index 10  Windows DirectSound  delivers 44100
       index 1   MME                  delivers 44100
```

From the command line, the same report without starting a server:

```bash
pydvma-serve --list-devices
```

Three things in there are worth reading carefully.

**`calibration`: are the readings volts, or not?** Channel counts and
sample rates come from the driver and are equally reliable for any
interface. The voltage scale does not. `CHARACTERISED` means the model
is in pydvma's device table, so `VmaxSC` is derived and readings are
real volts. `NEEDS GAIN` means the model is known but has an analogue
knob no audio API can read: state it with `input_gain_db`.
`uncalibrated` means the default `VmaxSC = 1.0` is a *placeholder*, so
readings are full-scale units. Fix it from the maker's spec, or measure
it with [`verify_input_scaling`](../api/verify.md) against a source of
known level.

**`hardware` vs `delivers`: one interface, several backends.** On
Windows a single device is published once per host API, and they are
not equivalent. The `>>` marks the one pydvma recommends.

**The index moves.** It is a position in an enumeration, not an
identity, so prefer to name the device:

```python
settings = dvma.MySettings(device='U24XL', fs=48000, channels=2)
# note: using 'Line (U24XL with SPDIF I/O)' via Windows WDM-KS
#       (24-bit, refuses rates it cannot clock); 4 backends available
#       - device index 27
```

`device=` takes a case-insensitive substring, picks the best backend for
the rate you asked for, and records the name and host API so a later
capture follows the hardware if the list reorders. Ask for a rate the
recommended backend cannot clock and it moves to one that can, and says
so:

```python
dvma.MySettings(device='U24XL', fs=8000)
# note: ... via Windows WASAPI ... [not the default backend:
#       Windows WDM-KS cannot clock 8000 Hz] - device index 23
```

It refuses rather than guess if the name matches two different devices.
An index still works if you want one (`device_index=27`), and
`list_available_devices(raw=True)` prints the plain index-ordered list.

!!! tip "Name the MODEL to make settings portable between machines"
    An OS names the same device differently: the ESI U24 XL is
    `U24XL with SPDIF I/O` on macOS and `Line (U24XL with SPDIF I/O)` on
    Windows, and a Scarlett 2i2 is generic `Analogue 1 + 2 (Focusrite USB
    Audio)` on Windows, which does not contain the model at all. Name the
    model instead and it resolves on either:

    ```python
    dvma.MySettings(device='ESI U24 XL', fs=48000)
    # note: using 'Line (U24XL with SPDIF I/O)' (matched by model, not
    #       device name) via Windows WDM-KS ...
    ```

    Model matching ignores case and punctuation (`'esi-u24-xl'` works),
    is tried only when the raw name matches nothing, and is reported in
    the note. It works for any model in `pydvma._soundcard_specs`. If
    nothing matches, the error lists the devices that are present.

To query a configured device directly:

```python
from pydvma import streams

streams.soundcard_device_name(settings)   # e.g. 'Scarlett 2i2 4th Gen'
streams.native_input_rates(settings)      # e.g. [44100, 48000, 88200, 96000, ...]
```

`soundcard_device_name` resolves an unset `device_index` the same way the
recorder does, so a query and the stream that follows describe the same
device. `native_input_rates` returns an empty list where the platform
cannot answer (anything but macOS and Windows), meaning "capability
unknown".

!!! warning "`check_input_settings` is not a capability probe on macOS"
    It approves every rate CoreAudio is willing to *resample* to, which
    is all of them: a Scarlett 2i2 accepts a 3 kHz request while its
    hardware ladder starts at 44.1 kHz. The conversion is then silent,
    with as little as 12 dB of alias rejection. Ask the hardware with
    `native_input_rates` instead. pydvma does, and captures at a rate the
    device really runs (see [Sample Rate Selection](#sample-rate-selection)).

### Recording

```python
data = dvma.log_data(settings, test_name='recording_01')
time_data = data.time_data_list[0]       # shape (samples, channels)
```

`log_data` returns a `DataSet` holding one `TimeData`. To collect several
recordings in one dataset, add each `TimeData` with
`data.add_to_dataset(new_data.time_data_list[0])`; the
[impact test example](../examples/basic.md#impact-test-with-averaging)
does this in a loop.

## National Instruments DAQ

### Requirements

- NI-DAQmx driver installed
- the nidaqmx Python package (`pip install "pydvma[ni]"`)
- Windows or Linux (NI provides no macOS driver)

### Configuration

```python
settings = dvma.MySettings(
    device_driver='nidaq',
    device_index=0,       # from list_available_devices(); see below
    fs=10000,
    stored_time=2.0,
    channels=4,
    VmaxNI=10,            # input range, ±10 V
)
```

#### Finding your device index

`device_index` is an index into the NI device list **as nidaqmx
enumerates it, with each cDAQ chassis collapsed to a single entry**.
Don't guess. The plain listing shows the chassis modules and channel
counts, in exactly the order `device_index` expects:

```python
dvma.list_available_devices(raw=True)
# ...
# Devices available using device_driver='nidaq', by index:
# 0: cDAQ1 (cDAQ-9174, chassis) AI=4 AO=2 modules=['cDAQ1Mod1', 'cDAQ1Mod2']
# 1: Dev1 (USB-6003, device) AI=8 AO=2
```

Here the chassis is `device_index=0` and the USB-6003 is `device_index=1`.
(`dvma.get_devices_NI()` returns a *flat* list that names the chassis and
each module separately, so its indices do **not** match `device_index`.)

`dvma.suggest_ni_settings(device_index)` returns safe ranges, rate and
terminal mode for whatever is at that index (see below).

### Terminal Configuration

Set `NI_mode` to one of:

| `NI_mode` | Terminal configuration |
| --------- | ---------------------- |
| `'DAQmx_Val_RSE'` | referenced single-ended (default) |
| `'DAQmx_Val_Diff'` | differential |
| `'DAQmx_Val_NRSE'` | non-referenced single-ended |
| `'DAQmx_Val_PseudoDiff'` | pseudo-differential (required by DSA modules such as the 9234) |

```python
settings = dvma.MySettings(device_driver='nidaq', NI_mode='DAQmx_Val_Diff')
```

### cDAQ chassis with multiple modules

A CompactDAQ chassis is addressed as a **single device**: use the one
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
counting AI channels (and vice versa for output).

#### Sensible defaults: `suggest_ni_settings`

`suggest_ni_settings(device_index)` inspects the device and returns safe,
in-range values (terminal configuration, full-scale ranges, sample rate)
you can pass straight to `MySettings`:

```python
kwargs = dvma.suggest_ni_settings(0)        # for the chassis at index 0
settings = dvma.MySettings(channels=8, **kwargs)
```

For the lab cDAQ (two 9234s and a 9260 AO) this gives
`NI_mode='DAQmx_Val_PseudoDiff'`, `VmaxNI=5`, `output_VmaxNI≈4.24`, and a
rate on the 9234's discrete ladder.

#### NI 9234 / DSA module constraints

Delta-sigma (DSA) modules like the 9234 differ from the multiplexed
USB-600x/621x devices, and pydvma depends on several of their quirks:

- **Pseudo-differential only.** Set `NI_mode='DAQmx_Val_PseudoDiff'`;
  other terminal modes are rejected.
- **Fixed ±5 V range.** A `VmaxNI` other than `5` is accepted by the
  driver but does not change the hardware range.
- **Simultaneous sampling.** Every channel has its own ADC, so all
  channels (across modules, via the chassis timebase) are sampled at
  the same instant. There is no inter-channel skew, unlike the
  multiplexed USB DAQs.
- **Automatic anti-alias filter.** It is locked to the sample rate and
  not configurable. AC coupling adds a high-pass at about 0.5 Hz.
- **Discrete sample-rate ladder.** The driver rounds `fs` to the nearest
  rate the module can run, rather than running arbitrary rates.

#### Non-standard / gappy layouts

The count-based `channels=N` assumes each module is filled from `ai0`
upward. For a non-contiguous set (skip a channel, start partway into a
module, mix channels across modules), give an explicit DAQmx
physical-channel string instead:

```python
settings = dvma.MySettings(
    device_driver='nidaq',
    channels=5,                                              # must match the string
    input_channels_spec='cDAQ1Mod1/ai0:3,cDAQ1Mod4/ai1',     # inputs
    output_channels_spec='cDAQ1Mod2/ao0',                    # outputs
)
```

When set, these override the automatically built channel strings
verbatim (nidaqmx backend only).

## Triggered Acquisition

### Pre-trigger Recording

Useful for capturing transient events like impacts:

```python
settings = dvma.MySettings(
    fs=10000,
    stored_time=1.0,
    channels=2,
    chunk_size=1000,          # must be at least pretrig_samples
    pretrig_samples=1000,     # samples to keep before the trigger
    pretrig_threshold=0.5,    # trigger level (see the units below)
    pretrig_channel=0,        # channel to monitor
    pretrig_timeout=20,       # seconds to wait FOR THE TRIGGER
)
```

When recording starts, pydvma continuously buffers data. When the signal
exceeds the threshold, it saves the pre-trigger samples plus the
post-trigger duration. The first sample above the threshold lands at
exactly index `pretrig_samples` of the returned capture.

`pretrig_timeout` bounds the wait for the trigger **event** only. Once
the signal crosses, the post-trigger data is given `stored_time + 5`
seconds of its own to arrive, so a capture longer than the timeout is
never cut short. If nothing crosses in time, `log_data` does not raise.
It returns the most recent `stored_time * fs` samples, exactly as an
untriggered log would.

Two constraints on `pretrig_samples`: it must not exceed `chunk_size`
(that is all the pre-trigger context the buffer keeps), and it must be
less than `stored_time * fs` (or there is no post-trigger data left to
record). Both raise a `ValueError` naming the offending pair, when you
create `MySettings` or when you call `log_data`.

`pretrig_threshold` is a magnitude in the units the recorder stores. On
NI that is volts. On a soundcard it is volts **once `VmaxSC` is set**,
and full-scale units while it is left at its default of 1.0. So the
default threshold of 0.05 means "5% of full scale" on an uncalibrated
device but 50 mV on a calibrated one, which may sit close to the noise
floor. Set it to a sensible fraction of the signal you expect.

### Capture integrity

Long captures are as safe as short ones: both recorders keep their
buffers as circular rings, so the work per chunk is fixed however long
`stored_time` is. If the host nevertheless falls behind the hardware
(PortAudio flags dropped input, or a DAQmx task overwrites unread
samples once its input buffer overflows), the loss is **counted** rather
than hidden. `acquisition.LAST_CAPTURE_OVERFLOWS` holds the number of
events in the last capture, `log_data` prints a warning, and the web
logger shows a "capture integrity" message. A capture with a non-zero
count has gaps, and transfer functions or coherence computed from it are
not trustworthy, so repeat it.

Not every gap is flagged by the host. A USB audio driver that loses a
USB packet zero-fills it, and PortAudio never sees an overflow: the
capture simply contains stretches of exact digital silence (measured on
a Scarlett 2i2 at anything from 8 samples to 188 ms). So `log_data` also
scans every capture for runs of at least `acquisition.DROPOUT_MIN_RUN`
frames in which every channel is exactly zero
(`acquisition.exact_zero_dropouts`). A live analogue input never produces
that, because its noise floor keeps the converter busy. The result is
left in `acquisition.LAST_CAPTURE_DROPOUTS` as `(count, seconds)`, with a
warning. Leading zeros are not counted (they are the fresh-stream startup
shortfall, handled separately), nor is an effectively silent record,
where a 16-bit host legitimately delivers zeros. Dropouts of this kind
point at the USB link: try another port or cable, without a hub.

**A busy computer is the usual cause.** A USB audio interface streams
without retries and with a small driver buffer, so a computer that is
short of memory can lose packets (the zero-filled dropouts above) or
garble samples on every channel at once. That shows up as transfer
function coherence collapsing on the weaker channel, often for only a few
seconds. An NI device over USB or PCI does not garble samples, because
its driver retries and buffers seconds of data. It can still lose data
when the host falls behind, on long, high-rate or decimated captures,
and then the loss is a gap, counted as above. In both cases, close other
applications, keep several gigabytes of memory free, restart the kernel
between batches, and shorten long high-rate captures before suspecting
the interface or the cables.

## Output Generation

Generate signals during acquisition, for example for transfer function
measurements. The built-in generator makes `'gaussian'` noise, `'uniform'`
noise or a `'sweep'`, and returns `(t, output)` where `output` has shape
`(samples, settings.output_channels)`.

```python
settings = dvma.MySettings(
    fs=10000,
    stored_time=1.0,
    channels=2,
    output_channels=1,     # one output channel
)
```

`amplitude` is in **volts**, and means different things for each signal:

| `sig` | `amplitude` is |
| ----- | -------------- |
| `'gaussian'` | the standard deviation (rms) of the noise |
| `'uniform'` | the peak, so values lie in ±`amplitude` |
| `'sweep'` | the peak of the sine |

With `f=[f1, f2]`, noise is band-pass filtered between `f1` and `f2`, and
`amplitude` is then the rms of the filtered result. The waveform fades in
and out over its first and last tenth (at most 0.1 s).

The output can never exceed `±settings.output_vmax()` (`output_VmaxNI`
on NI, `output_VmaxSC` on a soundcard). If the waveform would, the
generator scales the **whole waveform** down to fit, so its rms drops,
rather than raising an error. Check `np.abs(output).max()` if the level
matters.

### Gaussian White Noise Output

```python
# about 0.1 V rms white noise
t, output = dvma.signal_generator(
    settings,
    sig='gaussian',
    T=settings.stored_time,
    amplitude=0.1,      # volts, rms
)

# Record with the output playing
data = dvma.log_data(settings, output=output)
```

### Sine Sweep (Chirp) Output

```python
# a 0.5 V peak sine sweep from 10 Hz to 1000 Hz
t, output = dvma.signal_generator(
    settings,
    sig='sweep',
    T=settings.stored_time,
    amplitude=0.5,      # volts, peak
    f=[10, 1000],       # start and end frequencies, Hz
)

data = dvma.log_data(settings, output=output)
```

### Custom NumPy output

`signal_generator` is convenient but limited to three shapes, a single
amplitude and an optional band. For anything else (a multi-tone, a
measured or imported waveform, different drives on each channel, an MLS
sequence, a stepped sine) build the array yourself and pass it to
`log_data(..., output=...)`. The format is small but strict:

| Requirement | Detail |
| ----------- | ------ |
| **Shape** | 2-D `(N_samples, output_channels)`: one **column per AO channel**, even for a single channel (use `arr[:, None]`). The column count must equal `settings.output_channels`. |
| **Units** | **Volts**. There is no ±1 normalisation: a value of `2.5` means 2.5 V at the terminal. |
| **Sample rate** | The array is clocked out at `settings.output_fs` (default `fs`). Build the time base with `1 / settings.output_fs`, and make it about `stored_time` long to span the capture. A sound card has **one clock for input and output**, so when the stimulus plays out of the device you are capturing on, `log_data` resamples the array onto the capture rate and rewrites `output_fs` to match (`streams.output_shares_input_clock`). The physical signal is preserved (a sweep sweeps the frequencies it was generated for) but the sample grid you built is not the one that plays. Separate devices, and NI, keep independent clocks. |
| **Range** | Every sample must lie within ±`settings.output_vmax()`. On NI, out-of-range samples are rejected by DAQmx (error -200077). |
| **dtype** | Any float. It is cast internally (to volts on NI, to ±1 `float32` on the soundcard). |

!!! warning "A hand-built array gets no ramp and no safety clamp"
    `signal_generator` fades its waveform in and out and scales it to fit
    the full scale for you. A raw array gets **neither**: you own both. A
    discontinuity at the first or last sample will click and can ring
    the structure, so window the ends yourself for transient-sensitive
    work, and keep the signal inside ±`output_vmax()`.

```python
import numpy as np

fs = settings.output_fs         # output clock (defaults to settings.fs)
T = settings.stored_time        # match the capture length
vmax = settings.output_vmax()   # full-scale output, in volts
t = np.arange(0, T, 1 / fs)

# any waveform you like, in volts: here a multi-tone of 100, 220 and
# 505 Hz, 0.3 V peak each
tones = np.array([100.0, 220.0, 505.0])
y = 0.3 * np.sin(2 * np.pi * np.outer(t, tones)).sum(axis=1)

# raised-cosine fade over the first and last 10 ms, to avoid a click
n_ramp = int(0.01 * fs)
ramp = 0.5 * (1 - np.cos(np.linspace(0, np.pi, n_ramp)))
y[:n_ramp] *= ramp
y[-n_ramp:] *= ramp[::-1]

# stay inside the rails: nothing clamps a custom array
y = np.clip(y, -vmax, vmax)

output = y[:, None]             # (N, 1): a single output channel
data = dvma.log_data(settings, output=output)
```

**Multiple output channels.** Use one column per channel, with
`output_channels` set to match. For example a 50 Hz sine on the first
output and an independent noise drive on the second:

```python
settings2 = dvma.MySettings(fs=10000, stored_time=1.0, channels=2, output_channels=2)

a = 0.5 * np.sin(2 * np.pi * 50 * t)
b = np.clip(0.1 * np.random.randn(t.size), -vmax, vmax)
output = np.column_stack([a, b])      # (N, 2): columns map to ao0, ao1
data = dvma.log_data(settings2, output=output)
```

!!! tip "Record the drive as a reference channel"
    The drive is not recorded unless you wire it back into an input. Set
    `use_output_as_ch0=True` in `MySettings` and the played `output` is
    prepended as channel 0 of the returned data. That suits transfer
    functions, where you want the excitation captured alongside the
    response rather than assumed. The prepended column passes through
    uncalibrated (cal factor 1).

## Volts and Full Scale

Recorded data and generated output are in **volts** wherever pydvma
knows the hardware's scale. Time series, FFTs, transfer functions and
output signals are all in volts, and become engineering units when
`channel_cal_factors` is applied for display.

### NI inputs and outputs

* `settings.VmaxNI` (default `5` V) is the input range limit. NI devices
  are read directly in volts, so it does not scale the data. It sets the
  limits of the AI task (`min_val=-VmaxNI`, `max_val=+VmaxNI`), and a
  signal beyond it clips. Pick the smallest range that covers your
  signal, since smaller ranges give better resolution. DAQmx rounds your
  request **up** to a range the hardware really has (a 9234 is fixed at
  ±5 V and accepts any value; a 6212 asked for ±1 V runs at ±2 V).
  pydvma reads back the range in use, prints a note if it differs, and
  stores it in `settings.VmaxNI`.
* `settings.output_VmaxNI` (default `VmaxNI`) is the AO task's full
  scale. An NI 9260 is limited to ±4.24 V, and asking DAQmx for more
  fails with error -200077. A `signal_generator` waveform above
  `output_VmaxNI` is scaled down to fit (see
  [Output Generation](#output-generation)).
  `suggest_ni_settings(device_index)` returns safe defaults for a device.

### Soundcard inputs and outputs

`sounddevice` delivers samples as ±1 normalised float32. pydvma scales
those to volts with a calibration constant, so downstream code sees
voltages:

* `settings.VmaxSC` (default `1.0`) is the input full-scale voltage: the
  voltage at the jack that reads a normalised 1.0. The default treats
  normalised samples as volts at unit scale, which is no calibration.
  Set it to the measured full-scale voltage and acquisitions become
  calibrated.
* `settings.output_VmaxSC` (default `VmaxSC`) is the output full-scale
  voltage: `output_signal` divides the requested waveform by it to
  recover the ±1 that sounddevice expects. Because it follows `VmaxSC`,
  a derived input full scale (below) moves the output scaling with it.
  On interfaces whose output level is set by an analogue knob (the
  Scarlett's front-panel Output control), output voltage is only
  repeatable at a marked knob position.

#### Deriving `VmaxSC` from the preamp gain

On a characterised interface you do not have to measure the full scale.
It follows in closed form from the interface's published maximum input
level `L` (in dBu at minimum gain) and the preamp gain `G` you have set:

```
V_fullscale_peak = sqrt(2) * 0.7746 * 10 ** ((L - G) / 20)
```

pydvma cannot read `G`, because it is a front-panel control no audio API
exposes. State it, and `VmaxSC` is derived for you:

```python
settings = dvma.MySettings(
    device_driver='soundcard',
    input_gain_db=9,        # what the front panel / Focusrite Control says
    input_mode='line',      # 'line', 'inst' or 'mic'
)
```

This applies to the default input device. Add `device='Scarlett 2i2'` to
name the interface. On a Scarlett 2i2 4th Gen `L` is 22 dBu on **line**,
12 on **inst** and 16 on **mic**, and the derivation was confirmed
against hardware to 0.10 dB, so no calibration run is needed. A stated
gain **takes precedence over an explicit `VmaxSC`**. It applies only to
interfaces characterised in `pydvma._soundcard_specs`, and any other
device keeps the `VmaxSC` you gave it. Changing the gain on the hardware
invalidates the calibration, so state it again when you do.

#### Fixed-gain interfaces: nothing to state

A characterised interface with **no analogue gain anywhere in its input
path** has a constant full scale, so `VmaxSC` is derived automatically
with no stated gain at all. The ESI U24 XL is the first: the default
settings come out calibrated in volts (+4.7 dBu, which is 1.88 V peak,
confirmed against hardware to 0.07 dB). An explicit `VmaxSC` still wins,
since that is your own calibration.

On macOS the capture stream also pins two settings such a device *does*
have, restoring them when the stream closes. The class-compliant
**input volume control** is set to 0 dB (on the U24 XL it is a purely
digital gain, so any other value silently rescales the data), and a
capture format parked at 16-bit is raised to **24-bit** (macOS defaults
some interfaces to 16 and resets the choice on every sample rate change).

!!! note "Not every channel a soundcard reports is an input"
    A Focusrite Scarlett 2i2 4th Gen advertises four inputs, but only
    1 and 2 are the analogue Mic/Line/Inst inputs: **3 and 4 are a
    digital loopback of its own output mix**. Recorded unknowingly they
    look like a plausible pair of channels wired to nothing.
    `pydvma._soundcard_specs.channel_roles(name, channels)` reports the
    role of each input for a characterised device, and the web logger
    warns as soon as the channel count reaches one.

### IEPE / ICP excitation (NI DSA modules)

The NI 9234 (and other DSA modules with built-in excitation) can power
IEPE/ICP accelerometers directly. Set the excitation current for each
channel:

```python
settings = dvma.MySettings(
    device_driver='nidaq',
    channels=4,
    iepe_excit_current_A=[0.002, 0.002, 0.0, 0.0],   # 2 mA on channels 0 and 1
)
```

A channel with a current above 0 is switched to AC coupling. The
recorder waits about 2 s after the task starts, so the sensor's DC bias
can settle through the AC-coupling high-pass before it reads. Later
`log_data` calls with matching hardware settings reuse the live task and
skip the wait.

On a multi-module chassis the list is indexed in the same slot order as
the captured columns (see
[cDAQ chassis with multiple modules](#cdaq-chassis-with-multiple-modules)),
and each current is checked against the module that actually supplies
that channel. An accelerometer on the second AI module is enabled by
setting the current at its column index, e.g.
`iepe_excit_current_A[5] = 0.002` for `Mod4/ai1` in the table above.

!!! warning "IEPE must-knows"
    - **Only enable excitation on channels with an actual ICP/IEPE
      sensor.** A charge or voltage input (a force hammer, a signal
      generator, a loopback from an AO output) must stay at `0.0`:
      forcing 2 mA into a non-ICP input can damage it, and into an AO
      terminal it is driven back into the output.
    - **The legal currents on the 9234 are exactly `0.0` or `0.002` A**
      (off or 2 mA). Any other value raises a clear error.
    - **The list is positional, one entry per channel** in captured
      column (slot) order. A scalar applies to every channel.
    - `iepe_excit_current_A > 0` needs `device_driver='nidaq'` and a DSA
      module. Soundcard inputs have no configurable excitation.
    - **The web logger's IEPE switch applies to every channel.** Python's
      per-channel list is the way to mix ICP and non-ICP channels. See
      [IEPE excitation](../web-logger/ni-hardware.md#iepe-excitation).

### Worked example: IEPE accelerometers on a cDAQ

An end-to-end recipe for the most common DSA setup: ICP/IEPE
accelerometers powered straight from an NI 9234 in a cDAQ chassis, with
per-channel calibration so results come out in engineering units. The
chassis is at `device_index=0`, its first module (`cDAQ1Mod1`) is a
4-channel 9234, and you have two 100 mV/g accelerometers on `ai0` and
`ai1` plus a 2.3 mV/N force hammer on `ai2`:

```python
import pydvma as dvma

# 1. Confirm the chassis index, and get safe range, rate and mode for it.
dvma.list_available_devices(raw=True)     # the chassis is index 0
base = dvma.suggest_ni_settings(0)         # PseudoDiff, VmaxNI=5, a 9234-legal fs, ...

# 2. Three channels: IEPE on the two accelerometers only, and
#    per-channel sensitivities in volts per engineering unit.
settings = dvma.MySettings(
    channels=3,
    iepe_excit_current_A=[0.002, 0.002, 0.0],  # the hammer is not ICP
    channel_sensitivities=[0.1, 0.1, 0.0023],  # 100 mV/g, 100 mV/g, 2.3 mV/N
    stored_time=2.0,
    **base,            # device_driver='nidaq', device_index=0, NI_mode, VmaxNI, fs, ...
)

# 3. Record. log_data powers the ICP sensors, switches their channels to
#    AC coupling, and waits about 2 s for the bias to settle first.
data = dvma.log_data(settings, test_name='hammer_test_01')

# 4. Samples are stored in volts. The cal factors [10, 10, 434.8] are
#    attached, so plots, FFTs and transfer functions read in
#    engineering units.
time_data = data.time_data_list[0]
print(time_data.channel_cal_factors)        # [ 10.  10. 434.78]
time_data.units = ['g', 'g', 'N']           # optional axis labels
data.plot_time_data()
```

This relies on three things covered above:

- **Index by capture column, not by terminal label.** `channels=3` uses
  `cDAQ1Mod1/ai0:2`, so list position 0 is `ai0`, 1 is `ai1` and 2 is
  `ai2`. The same index applies to `iepe_excit_current_A`,
  `channel_sensitivities` and `pretrig_channel`.
- **IEPE only where there is an ICP sensor.** The hammer's channel stays
  at `0.0`.
- **`suggest_ni_settings` covers the 9234 housekeeping** (`PseudoDiff`,
  `VmaxNI=5`, an `fs` on the module's ladder). Override any of its keys
  by listing them after `**base`.

### Clipping detection

`log_data` compares the captured data with `0.95 * input_vmax()` (`VmaxNI`
on NI, `VmaxSC` on a soundcard) and prints `WARNING: Data may be clipped`
if any sample comes within 5 % of the limit. The check uses the raw peak,
before any digital low-pass.

On a soundcard the check is only as meaningful as `VmaxSC`. With the
default `1.0` it compares against a nominal unit scale. Derive `VmaxSC`
from a stated `input_gain_db` (above) and the threshold becomes the
interface's real full-scale voltage, so the warning fires when the
converter is genuinely near clipping.

## Calibration and Scaling

Two multiplicative stages stand between the converter and a plotted
engineering value. `VmaxSC` (or, on NI, the volts read directly) turns
the converter's reading into **volts**, and is fixed when you log.
`channel_cal_factors` then turns volts into **engineering units** at
display and fit time, from the per-channel `channel_sensitivities`. It
can change at any time afterwards, because the stored samples stay in
volts. [Calibration and units](../web-logger/calibration.md) explains the
idea and what it changes in each view. This section covers the Python
side.

### Sensor sensitivity

Pass per-channel sensitivity, in volts per engineering unit, to
`MySettings` when you record. `log_data` stores its reciprocal as
`TimeData.channel_cal_factors`, and plotting and modal fitting multiply
by those factors, so results read in engineering units (g, m/s², N, and
so on) with no scaling afterwards.

```python
settings = dvma.MySettings(
    channels=3,
    channel_sensitivities=[0.1, 0.1, 0.0023],  # V/g, V/g, V/N
)
data = dvma.log_data(settings)
data.time_data_list[0].channel_cal_factors      # [10, 10, 434.78]
```

A single value applies to every channel. The default `1.0` means no
calibration, and every value must be non-zero, so use `1.0`, not `0.0`,
to leave a channel uncalibrated. Sensitivities come off the sensor's
calibration sheet, usually in millivolts, so divide by 1000. See the
[tip on calibration sheets](../web-logger/calibration.md#calibrate-a-channel).

#### Setting or correcting calibration after logging

If you recorded without sensitivities, or entered a wrong value, set the
**cal factor** directly on the data list. It is the *reciprocal* of the
sensitivity (engineering units per volt), because it multiplies the
stored volts: a 100 mV/g accelerometer (0.1 V/g) has a cal factor of 10.

```python
# One channel of one set (set and channel indices are both 0-based)
data.time_data_list.set_calibration_factor(10, n_set=0, n_chan=0)

# Inspect, or set every set at once
factors = data.time_data_list.get_calibration_factors()
data.time_data_list.set_calibration_factors_all(factors)
```

`freq_data_list` and `tf_data_list` have the same three methods. A
spectrum or transfer function copies the factors when it is computed, so
after changing a time data list, recompute them (or set the factors on
their lists too).

### Engineering-unit labels

`TimeData.units` is a list with one string per channel. It passes through
to `calculate_fft`, `calculate_cross_spectrum_matrix` and
`calculate_sonogram`, and `calculate_tf` builds `(out_unit)/in_unit` for
each output channel, with a compound unit in brackets, as in `(m/s2)/N`:

```python
time_data = data.time_data_list[0]
time_data.units = ['g', 'g', 'N']       # set after recording if you did not pass units
```

## Monitoring and Visualization

### Live monitoring

The **[web logger](../web-logger/index.md)** has a live oscilloscope and
FFT of the incoming signal. Use its
[Live monitoring](../web-logger/live-monitoring.md) view to check levels
and trigger settings before committing to a recording.

For a one-off look at the live buffer from Python, use
`dvma.stream_snapshot` while a stream is running, for example straight
after a `log_data` call:

```python
from pydvma import streams

snapshot = dvma.stream_snapshot(streams.REC)     # a TimeData of the live buffer
```

## Best Practices

### Sample Rate Selection

Choose a sample rate at least 2.56 times the highest frequency you care
about. That matches the digital anti-alias filter pydvma uses, whose
passband ends at `fs/2.56`. Typical choices:

- **Audio and vibration**: 10 to 50 kHz
- **Ultrasonic**: 100 kHz and up (on hardware that supports it)
- **Slow processes**: 1 to 10 Hz

The rate you pick is the rate the **data** comes back at. It is not
always the rate the **converter** runs at. Hardware only runs the rates
it has: a sound card's ladder starts at 44.1 kHz, so `fs=3000` is
captured at 44.1 kHz and decimated to 3 kHz behind pydvma's own
anti-alias filter (`analysis.resample_to_fs`: passband to `fs/2.56`,
96 dB stopband at `fs/2`, zero phase). `streams.select_capture_fs` makes
that choice and names the rule it applied, and the rate the converter
really ran at comes back as `lpf_capture_fs` on the returned settings.

These settings control it:

| Field             | Default  | What it means                                |
| ----------------- | -------- | -------------------------------------------- |
| `fs`              | `44100`  | The rate the logged data ends up at. Not necessarily a rate the hardware runs |
| `capture_fs`      | `None`   | Force the converter's rate (Hz). It must be at least `fs`, and is rounded up to a real rate where the ladder is known |
| `lpf_on`          | `False`  | Digital low-pass: capture above `fs` deliberately (anti-aliasing plus about 10·log₁₀(M) dB of broadband-noise process gain), then resample down |
| `oversample`      | `'auto'` | How far above `fs` to capture: `'lowest'` (the first rate at or above 2.56 × `fs`) or `'highest'` (as fast as the device goes) |
| `lpf_capture_fs`  | none     | Written onto the returned settings: the rate the converter really ran at, whenever it differed from `fs` |

`'auto'` chooses on the physical fact. It picks `'lowest'` where the
converter anti-aliases in silicon (any audio interface, and NI DSA
modules like the 9234), because content above the capture Nyquist is
already gone before the ADC and capturing faster rejects nothing extra.
It picks `'highest'` on a filterless multiplexed device (USB-6003/6212),
where a high capture rate is the only alias protection there is.

### Duration Selection

The frequency spacing of a spectrum from one frame is `1/stored_time`. To
get a spacing `df`, record for at least this long:

```python
df = 1.0                        # Hz spacing wanted
N_frames, overlap = 1, 0.5      # frames averaged in the analysis (1 = a single frame)
stored_time = (N_frames + 1) * (1 - overlap) / df       # 1 s here; 4.5 s for N_frames=8
```

Averaging frames makes each one shorter, so it needs a longer record for
the same spacing (see
[Averaging for Better Estimates](analysis.md#averaging-for-better-estimates)).

### Anti-aliasing

Know which kind of front end you have. A delta-sigma converter (any
audio interface, and NI DSA modules such as the 9234) anti-aliases in
silicon at its own rate, so content above the capture Nyquist is gone
before the ADC. `streams.hardware_antialiases(settings)` reports this per
device. A multiplexed SAR device (NI USB-6003/6212) has no such filter,
and anything above Nyquist folds into your band at sampling time, where
no later filtering can separate it. There, set `lpf_on=True` so the
capture runs fast and pydvma filters before dropping the rate, or choose
a sample rate high enough that nothing real lives above `fs/2`.

## Troubleshooting

### No Signal Detected

1. Check connections and that the sensor is powered (IEPE sensors need
   excitation on an NI 9234).
2. Run `dvma.list_available_devices()` and check `device` or
   `device_index`, and that `channels` matches what you wired. On a
   Scarlett 2i2, inputs 3 and 4 are not analogue inputs.
3. Check the input range or gain.
4. Test with a known signal source.

### Clipping or Saturation

`log_data` prints `WARNING: Data may be clipped` when a sample comes
within 5 % of the input limit.

- Reduce the signal amplitude, or the preamp gain.
- Raise `VmaxNI`, or on a soundcard check `VmaxSC` matches the gain.
- Check the sensor's sensitivity and range.

### High Noise Floor

- Ground properly, and shield cables for low-level signals.
- Keep signal cables away from power cables.
- Use differential inputs where the hardware has them.
- Reduce the gain if you can, and check for ground loops.

### Trigger Not Working

- The trigger fires when the magnitude of the signal on `pretrig_channel`
  exceeds `pretrig_threshold`, in the units the recorder stores (volts
  once `VmaxSC` is set). Check the level against your signal.
- Check `pretrig_channel`, and that the signal reaches it.
- If nothing crosses within `pretrig_timeout`, `log_data` returns an
  untriggered capture rather than raising.
- A `ValueError` about `pretrig_samples` means it exceeds `chunk_size`, or
  leaves no post-trigger data.

### Warnings about gaps or dropouts

A capture integrity or dropout warning means samples were lost. See
[Capture integrity](#capture-integrity) and repeat the recording.

## Next Steps

- Learn about [Data Analysis](analysis.md)
- Explore the [Examples](../examples/basic.md)
