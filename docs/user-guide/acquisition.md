# Data Acquisition

This guide covers data acquisition using different hardware interfaces.

## Hardware Support

pydvma supports multiple acquisition hardware:

- **Soundcards**: Using the sounddevice library (on macOS, capture also
  goes through `pydvma._coreaudio`, which queries the device's true rate
  ladder and pins its hardware clock to the capture rate for the
  duration of the stream, restoring it afterwards)
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

**`calibration` — are the readings volts, or not?** Channel counts and
sample rates come from the driver and are equally reliable for any
interface. The voltage scale does not. `CHARACTERISED` means the model
is in pydvma's device table, so `VmaxSC` is derived and readings are
real volts. `NEEDS GAIN` means the model is known but has an analogue
knob no audio API can read — state it with `input_gain_db`.
`uncalibrated` means the default `VmaxSC = 1.0` is a *placeholder*, so
readings are full-scale units; fix it from the maker's spec, or measure
it with [`verify_input_scaling`](../api/verify.md) against a source of
known level.

**`hardware` vs `delivers` — one interface, several backends.** On
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
`raw=True` gives the old flat listing.

!!! tip "Name the MODEL to make settings portable between machines"
    The name an OS gives a device is not portable. The same ESI U24 XL
    is `U24XL with SPDIF I/O` to macOS and `Line (U24XL with SPDIF I/O)`
    to Windows; a Scarlett 2i2 is `Scarlett 2i2 4th Gen` on macOS but
    generic `Analogue 1 + 2 (Focusrite USB Audio)` on Windows, which
    does not contain the model at all. So a settings file naming the raw
    device only works on the machine it was written on.

    Name the model instead and it resolves on either:

    ```python
    dvma.MySettings(device='ESI U24 XL', fs=48000)
    # note: using 'Line (U24XL with SPDIF I/O)' (matched by model, not
    #       device name) via Windows WDM-KS ...
    ```

    Model matching ignores case and punctuation (`'esi-u24-xl'` works),
    is tried only when the raw name matches nothing, and is reported in
    the note so you can see which route resolved. It works for any model
    in `pydvma._soundcard_specs`; the error lists the recognised ones.

To query a configured device directly:

```python
from pydvma import streams

streams.soundcard_device_name(settings)   # 'Scarlett 2i2 4th Gen'
streams.native_input_rates(settings)      # [44100, 48000, 88200, 96000, ...]
```

`soundcard_device_name` resolves an unset `device_index` through
PortAudio's default input the same way the recorder does, so a
capability query and the stream that follows always describe the same
device. `native_input_rates` returns an empty list where the platform
cannot answer (anything but macOS today), meaning "capability unknown".

!!! warning "`check_input_settings` is not a capability probe on macOS"
    It approves every rate CoreAudio is willing to *resample* to, which
    is all of them: a Scarlett 2i2 accepts a 3 kHz request while its
    hardware ladder starts at 44.1 kHz. The conversion is then silent,
    and its quality depends on the ratio to whatever rate the last
    application left the device at — measured at as little as 12 dB of
    alias rejection, with up to 4.3 dB of passband droop. Ask the
    hardware with `native_input_rates` instead; pydvma does, and captures
    at a rate the device really runs (see
    [Sample Rate Selection](#sample-rate-selection)).

### Recording

```python
# Record programmatically
dataset = dvma.log_data(settings, test_name="recording_01")
```

For a point-and-click interface use the
[web logger](../web-logger/index.md); the old Qt `dvma.Logger` window was
removed (its last version is the `qt-final` git tag).

## National Instruments DAQ

### Requirements

- NI-DAQmx driver installed
- nidaqmx Python package (`pip install "pydvma[ni]"`)
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
settings.pretrig_threshold = 0.5  # Trigger level (see units below)
settings.pretrig_channel = 0      # Channel to monitor
settings.pretrig_timeout = 20     # Seconds to wait FOR THE TRIGGER
```

When recording starts, the system continuously buffers data. When the trigger condition is met (signal exceeds threshold), it saves the pre-trigger samples plus the post-trigger duration. The first sample above the threshold lands at exactly index `pretrig_samples` of the returned capture.

`pretrig_timeout` bounds the wait for the trigger **event** only. Once the signal crosses, the post-trigger data is given `stored_time + 5` seconds of its own to arrive, so a capture longer than the timeout is never cut short. If nothing crosses in time, `log_data` does not raise — it returns the most recent `stored_time * fs` samples, exactly as an untriggered log would.

Two constraints on `pretrig_samples`: it must not exceed `chunk_size` (that is all the pre-trigger context the buffer retains), and it must be less than `stored_time * fs` (or there is no post-trigger data left to record). Both raise a `ValueError` naming the offending pair.

`pretrig_threshold` is a magnitude in the units the recorder stores. On NI that is volts. On a soundcard it is volts **once `VmaxSC` is set**, and full-scale units while it is left at its default of 1.0 — so the default threshold of 0.05 means "5% of full scale" on an uncalibrated device but 50 mV on a calibrated one, which may sit close to the noise floor. Raise it to a sensible fraction of the signal you expect.

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
| **Sample rate** | The array is clocked out at `settings.output_fs` (defaults to `fs`). Build the time base with `1 / settings.output_fs`, and make it ≈ `stored_time` long to span the capture. A sound card has **one clock for input and output**, so when the stimulus plays out of the device you are capturing on, `log_data` resamples the array onto the capture rate and rewrites `output_fs` to match (`streams.output_shares_input_clock`). The physical signal is preserved — a sweep sweeps the frequencies it was generated for — but the sample grid you built is not the one that plays. Separate devices, and NI, keep independent clocks. |
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

fs   = settings.output_fs       # output clock (defaults to settings.fs;
                                # resampled onto the capture rate on a
                                # shared-clock soundcard)
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

### Output stimulus settings (`Output_Signal_Settings`)

`Output_Signal_Settings` bundles an output-stimulus definition (type,
amplitude, band). It is consumed by the **web logger's Acquire output
stimulus** — pre-fill it by handing a settings file to the local bridge
with `pydvma-serve --settings` (see
[From the Qt logger](../web-logger/migration.md)):

```python
oss = dvma.Output_Signal_Settings(
    type='gaussian',   # 'None' | 'sweep' | 'gaussian' | 'uniform'
    amp=0.1,           # peak amplitude in volts (clamped to output_vmax())
    f1=100,            # sweep start / noise lower band corner (Hz)
    f2=300,            # sweep end   / noise upper band corner (Hz)
)
```

Under the hood the same fields drive `signal_generator` — `type` becomes
`sig` and `[f1, f2]` becomes `f`.

A few notes:

- The four `type` values are exactly `'None'`, `'sweep'`, `'gaussian'`
  and `'uniform'`. `'None'` (the default) means output off.
- For fully scripted / headless output, use the array path shown above
  (`signal_generator` + `log_data(output=...)`); it is independent of
  `Output_Signal_Settings`.

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
  — identical numeric behaviour to a pre-v1.2 capture. Set it to your
  measured input sensitivity and acquisitions become calibrated.
* `settings.output_VmaxSC` (default = `VmaxSC`) is the output-side
  calibration: `output_signal` divides the requested voltage waveform
  by `output_VmaxSC` to recover the ±1 sounddevice expects. Because it
  follows `VmaxSC`, a derived input full scale (below) moves the output
  scaling with it — and on interfaces whose output level is set by an
  analogue knob (the Scarlett's front-panel Output control), output
  voltage is only repeatable at a marked knob position.

#### Deriving `VmaxSC` from the preamp gain

On a characterised interface you do not have to measure the input
sensitivity: the full-scale voltage follows in closed form from the
interface's published maximum input level `L` (in dBu at minimum gain)
and the preamp gain `G` you have set,

```
V_fullscale_peak = sqrt(2) * 0.7746 * 10 ** ((L - G) / 20)
```

pydvma cannot read `G` — it is a front-panel control no audio API
exposes — so state it, and `VmaxSC` is derived for you:

```python
settings = dvma.MySettings(
    device_driver='soundcard',
    input_gain_db=9,        # what the front panel / Focusrite Control says
    input_mode='line',      # 'line' | 'inst' | 'mic'
)
```

On a Scarlett 2i2 4th Gen `L` is 22 dBu on **line**, 12 on **inst** and
16 on **mic**; the derivation was confirmed against hardware to 0.10 dB,
so no per-device calibration run is needed. A stated gain **takes
precedence over an explicit `VmaxSC`**, and applies only to interfaces
characterised in `pydvma._soundcard_specs` — any other device keeps the
`VmaxSC` you gave it. Changing the gain on the hardware invalidates the
calibration, so re-state it when you do.

#### Fixed-gain interfaces: nothing to state

A characterised interface with **no analogue gain anywhere in its
input path** — the ESI U24 XL is the first — has a constant full
scale, so `VmaxSC` is derived automatically with no stated gain at
all: the default settings come out calibrated in volts (+4.7 dBu →
1.88 V peak on the U24 XL, confirmed against hardware to 0.07 dB). An
explicit `VmaxSC` still wins, since that is your own calibration.

On macOS the capture stream also pins two settings such a device *does*
have, restoring them when the stream closes: the class-compliant
**input volume control** is set to 0 dB (on the U24 XL it is a purely
digital ±dB gain, so any other value silently rescales the data), and
a capture format parked at 16-bit is raised to **24-bit** (macOS
defaults some interfaces to 16 and resets the choice on every sample
rate change).

!!! note "Not every channel a soundcard reports is an input"
    A Focusrite Scarlett 2i2 4th Gen advertises four inputs, but only
    1–2 are the analogue Mic/Line/Inst inputs: **3–4 are a digital
    loopback of its own output mix**. Recorded unknowingly they look
    like a plausible pair of channels wired to nothing.
    `pydvma._soundcard_specs.channel_roles(name, channels)` reports the
    role of each input for a characterised device, and the web logger
    warns as soon as the channel count reaches one.

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

On a soundcard the check is only as meaningful as `VmaxSC`: with the
default `1.0` it compares volts against a nominal unit scale. Derive
`VmaxSC` from a stated `input_gain_db` (above) and the threshold becomes
the interface's real full-scale voltage, so the warning fires when the
converter is genuinely near clipping.

### Quick reference

| Field                    | Path     | Default | What it means                            |
| ------------------------ | -------- | ------- | ---------------------------------------- |
| `VmaxNI`                 | input    | `5`     | NI AI full-scale (volts)                 |
| `VmaxSC`                 | input    | `1.0`   | Soundcard input cal: V at norm = 1       |
| `input_gain_db`          | input    | `None`  | Stated preamp gain (dB); derives `VmaxSC` on a characterised interface, and wins over an explicit one |
| `input_mode`             | input    | `'line'`| Which input the signal is on — `'line'`, `'inst'` or `'mic'`; sets the max input level used with `input_gain_db` |
| `output_VmaxNI`          | output   | `VmaxNI`| NI AO full-scale (volts)                 |
| `output_VmaxSC`          | output   | `VmaxSC`| Soundcard output cal: V at norm = 1      |
| `channel_sensitivities`  | input    | `1.0`   | V/eu per channel — see below             |
| `iepe_excit_current_A`   | input    | `0.0`   | IEPE excitation per channel (NI 9234 etc.) |

And the rates, which are **two** different things — the rate the data is
delivered at, and the rate the converter runs at:

| Field             | Default  | What it means                                |
| ----------------- | -------- | -------------------------------------------- |
| `fs`              | `44100`  | The rate the logged data ends up at. Not necessarily a rate the hardware runs |
| `capture_fs`      | `None`   | Force the converter's rate (Hz); must be ≥ `fs`, and is snapped up to a real rate where the ladder is known |
| `lpf_on`          | `False`  | Digital low-pass: capture above `fs` deliberately, then resample down |
| `oversample`      | `'auto'` | How far above: `'lowest'` (first rate ≥ 2.56 × `fs`) or `'highest'` (as fast as the device goes). `'auto'` picks `'lowest'` where the converter anti-aliases in silicon, else `'highest'` |
| `lpf_capture_fs`  | —        | Written onto the returned settings: the rate the converter really ran at, whenever it differed from `fs` |

## Calibration and Scaling

Two multiplicative stages stand between the converter and a plotted
engineering value, and they are set in different places at different
times. `VmaxSC` / `VmaxNI` turns the converter's normalised reading into
**volts**, and is fixed when you log — on a soundcard it is the input
full scale (measured, or derived from a stated `input_gain_db`; on NI it
is the voltage range you configured). `channel_cal_factors` then turns
volts into **engineering units** at display and fit time, from the
per-channel `channel_sensitivities` below, and can be changed at any
time afterwards because the stored samples stay in volts.

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

### Live monitoring

The **[web logger](../web-logger/index.md)** provides a live oscilloscope
and FFT of the incoming signal — use its
[Live monitoring](../web-logger/live-monitoring.md) view to check levels
and trigger settings before committing to a recording. (This replaced the
old Qt Oscilloscope window, which was removed with the Qt Logger.)

For a one-shot programmatic peek at the live buffer, use
`dvma.stream_snapshot(streams.REC)` while a stream is running (e.g.
immediately after a `log_data` call).

## Best Practices

### Sample Rate Selection

Choose appropriate sample rates:

- **Audio/vibration**: 10-50 kHz
- **Ultrasonic**: 100+ kHz
- **Slow processes**: 1-10 Hz

Remember Nyquist: sample at least 2× the highest frequency of interest.

The rate you pick is the rate the **data** comes back at; it is not
always the rate the **converter** runs at. Hardware only runs the rates
it has — a sound card's ladder starts at 44.1 kHz — so `fs = 3000` is
captured at 44.1 kHz and decimated to 3 kHz behind pydvma's own
anti-alias filter (`analysis.resample_to_fs`: passband to `fs/2.56`,
96 dB stopband at `fs/2`, zero-phase). `streams.select_capture_fs`
makes that choice and names the rule it applied; the rate the converter
really ran at comes back as `lpf_capture_fs` on the returned settings.

Two settings steer it. `lpf_on=True` runs the capture above `fs` on
purpose (anti-aliasing plus ~10·log₁₀(M) dB of broadband-noise process
gain), with `oversample` deciding how far above: `'lowest'` takes the
first rate at or above **2.56 × fs**, `'highest'` takes the fastest the
device offers, and the default `'auto'` picks between them on the
physical fact — `'lowest'` where the converter anti-aliases in silicon
(any audio interface, NI DSA modules like the 9234), because content
above the capture Nyquist is already gone before the ADC and capturing
faster rejects nothing extra, and `'highest'` on a filterless
multiplexed device (USB-6003/6212), where a high capture rate is the
only alias protection there is. `capture_fs` overrides the lot and
forces a rate outright.

### Duration Selection

```python
# For frequency resolution Δf
df = 1.0  # Hz resolution desired
settings.stored_time = 1.0 / df  # Minimum duration needed
```

### Anti-aliasing

Know which kind of front end you have. A delta-sigma converter (any
audio interface, NI DSA modules such as the 9234) anti-aliases in
silicon at its own rate, so content above the capture Nyquist is gone
before the ADC — `streams.hardware_antialiases(settings)` reports this
per device. A multiplexed SAR device (NI USB-6003/6212) has no such
filter, and anything above Nyquist folds into your band at sampling
time, where no later filtering can separate it. There, set `lpf_on=True`
so the capture runs fast and pydvma filters before dropping the rate —
or choose a sample rate high enough that nothing real lives above `fs/2`.

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
