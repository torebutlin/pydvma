# Acquisition and setup

You record in two stages. **Setup** is where you choose the device, sample
rate, channels and duration, plus a trigger and, for NI hardware, the NI
options. **Acquire** is where you press **Log Data**, with an optional
pretrigger and output signal.

In the browser you record from your computer's soundcard, with a
pretrigger and an output stimulus available. When the app is
[served locally](running-locally.md) you also reach NI-DAQ hardware and
audio interfaces with calibrated volts. The table at the
[end of this page](#what-runs-where) lists the differences.

## Setup

Setup opens with the basic controls. **Full ▾** reveals the advanced
ones, and **Basic** hides them again. The defaults are 44.1 kHz, 1
channel and 2 s.

### Basic controls

- **input device**: the device to record from. **Default** names the
  device it resolves to when served locally, for example
  `Default — ESI U24 XL`, so you know which hardware a capture will use.
  **↻** refreshes the list.
    - If a device appears under several host APIs (typically on
      Windows), only the recommended one is listed. Tick **all backends**
      to see them all.
    - Served locally, pydvma remembers the device by name. If the list is
      renumbered while you work, it finds your device again and says so;
      if the device has been unplugged, the capture is refused instead of
      recording from a different input.
- **sample rate**: type any rate (`3000`, `3k`, `48 kHz`) or pick one from
  the arrow list. Served locally the list holds the rates the device runs,
  plus lower standard rates that pydvma delivers by capturing faster and
  decimating; in the browser it holds standard rates. If the device can't
  run your rate itself, a note says so:
  `captures at 48000 Hz, resampled to 3000 Hz`. A rate above the device's
  maximum gets a warning and runs slower.
- **channels**: the number of input channels, from 1 up to the device
  maximum. Not every input a device reports is a real one: a Scarlett 2i2
  4th Gen advertises four, but 3 and 4 are a digital loopback of its own
  output mix. Setup warns you when you reach them.
- **duration**: the capture length in seconds. Type any value (`40`,
  `2.5`, `500ms`, `1m`) or pick a preset (0.5, 1, 2, 5, 10, 30 or 60 s).
- **trigger**: **arm**, the **threshold**, and **on ch**, the channel to
  watch (shown when you have more than one channel). The threshold box
  shows its unit. Where the input's full scale is known it is in volts,
  with a hint such as `= 5 % of full scale`. Otherwise it is a multiple of
  full scale (`× full scale`). Leave it blank for the default: 5 % of full
  scale in volts, or 0.05 × full scale. The group appears whenever the
  source can trigger. Arming here and on the Acquire card is the same
  switch. The rest of the trigger settings are under **Full**.

!!! note "Browser: allow the microphone"
    A browser hides device names until you allow microphone access. Press
    **Allow microphone access to see device names**. Capture works without
    it, but you can't pick a named device.

### Full controls

**Full ▾** adds groups under the headings **device**, **rates**,
**levels**, **trigger** and **NI-DAQ**. Read-only readouts are shown as
plain text rather than as controls.

**device** (browser only)

- **device capabilities**: the channel count, sample-rate range and
  latency the browser reports for the input, once you have allowed
  microphone access.
- **processing (off = raw measurement)**: **echo cancel**, **noise
  suppress** and **auto gain**. All three are off by default. Browsers
  turn them on for voice calls, and they change the signal, so leave them
  off for measurement.
- **timing**: a latency hint in milliseconds. Blank uses the browser's
  default.

**rates**

- **digital low-pass**: the **oversample + decimate** switch, off by
  default. See [Digital low-pass](#digital-low-pass).
- **capture rate** (served locally): **strategy** (**auto**, **lowest** or
  **highest**) and **hardware rate**, the rate the converter runs at, taken
  from the device's own list. **auto** is almost always right. The
  **hardware rate** box appears only when the device publishes a list of
  rates. See [Capture rate and delivered rate](#capture-rate-and-delivered-rate).

**levels**

- What you see first depends on the interface (served locally). A
  characterised interface with a preamp shows **input gain (for calibrated
  volts)** and an input mode. A fixed-gain interface shows its full scale
  as a note. An interface pydvma has no profile for shows **full scale
  (for calibrated volts)**, where you enter the measured full scale in
  volts peak. The full scale is what turns raw samples into volts, and
  pydvma can't read the preamp gain from the hardware. See
  [Soundcard input gain and full scale](calibration.md#soundcard-input-gain-and-full-scale).
- **input level**: the peak of each channel while the monitor is running,
  in volts when the full scale is known and in dBFS otherwise, for example
  `ch0 0.5123 V pk`. It ends with one line of advice: **clipping — turn
  the input gain down**, **close to clipping — turn the gain down a
  little**, **very low — turn the input gain up**, **no signal — check the
  cable and the source**, or **levels look good**. Start the monitor and
  check it before every capture. A clipped record looks plausible in the
  time trace but its spectrum is wrong.

**trigger**

- **pretrigger context**: how many samples to keep before the crossing.
  Blank uses 100.
- **timeout**: how many seconds to wait for a crossing. The default is 20.
  If it runs out, the capture happens anyway and is simply not aligned to
  a trigger.

### Capture rate and delivered rate

The **sample rate** you choose is the rate the logged data ends up at.
The converter doesn't always run at that rate, because hardware only runs
the rates it has. Where the two differ, pydvma captures at a rate the
device does run and resamples to yours behind a linear-phase anti-alias
filter: passband to fs/2.56 and at least 96 dB of stopband at fs/2. The
filter has zero phase, so transfer functions and modal fits are
unaffected. Setup shows the real capture rate as a note, for example
`captures at 44100 Hz, resampled to 8000 Hz`.

The two rates differ in three cases:

- **The device can't run your rate.** A soundcard's lowest rate is well
  above 3 kHz, so a 3 kHz log is captured at the device's lowest suitable
  rate and decimated. pydvma does this itself
  with a known filter, rather than leaving it to the operating system's
  resampler, which can filter poorly. The sample-rate suggestions include
  these low targets for this reason.
- **The digital low-pass is on**, which captures above your rate on
  purpose (below).
- **You set a hardware rate** explicitly.

An NI delta-sigma module instead rounds an off-list rate to the nearest
one it runs, and every axis uses the true rate. See
[NI hardware](ni-hardware.md#sample-rate-ladders-and-coercion).

### Digital low-pass

The **digital low-pass** switch runs the capture faster than your sample
rate on purpose, then filters away the extra band as it resamples down.
Your **sample rate** keeps its meaning: it is still the rate of the
logged data. Two reasons to use it:

- **Anti-aliasing.** The NI USB-6003 and USB-6212 have no analogue
  anti-alias filter, so at a low sample rate anything above fs/2 folds
  into your band. Capturing fast and filtering digitally removes it, which
  gives these devices the anti-alias behaviour that a delta-sigma module
  such as the NI 9234 has in hardware.
- **Lower noise.** Rejecting out-of-band noise reduces broadband noise by
  about 10·log₁₀(oversample factor) dB.

How far above your rate it captures depends on the converter:

- An audio interface, or an NI delta-sigma module, filters in hardware. It
  captures at the lowest rate at or above 2.56 × fs (the resampler's
  passband runs to fs/2.56), because capturing faster rejects nothing
  extra and only makes more data.
- A converter with no anti-alias filter captures as fast as it can go.

**strategy** in **capture rate** overrides this: **lowest** or
**highest**.

Served locally, the server does the whole chain. In the browser, the page
records at the audio system's native rate and the analysis engine
resamples afterwards. If there is no room to capture faster (your rate is
already the lowest the device runs or, for a device with no published
list of rates, its maximum is below 2 × fs), the log goes ahead
unfiltered and says so.

### NI-DAQ options {#ni-daq-options-bridge-only}

When the app is served locally with NI hardware, **Full** gains an
**NI-DAQ** group: **terminal configuration**, **NI voltage range (±V)**
for the input (**in**) and output (**out**), and **IEPE off** or **IEPE 2
mA**. These are hidden in the browser, which can't reach NI hardware. See
[NI-DAQ controls in Setup](ni-hardware.md#ni-daq-controls-in-setup) for
what each does and how the devices differ.

!!! warning "IEPE applies to every channel"
    The IEPE switch powers every input channel. Don't use it with a
    non-IEPE sensor on another channel; see
    [IEPE excitation](ni-hardware.md#iepe-excitation) for how to mix them.

## Acquire

The **Acquire** stage records a capture.

- The **settings** chip summarises the pending capture:
  `fs · channels · duration · device · pretrigger`, plus the output
  stimulus when it is on. Click the chip, or **Edit**, to go back to
  Setup.
- **Log Data** records. While it records, a progress bar fills against
  the capture duration next to a readout such as `12.4 / 30.0 s`. An
  armed log that is waiting for its trigger shows a waiting state instead
  of a bar, because the clock starts only when the capture does.
- **Cancel** stops a capture part-way. The button reads **Cancelling…**
  until the capture has stopped. Nothing is added to your data, and a message
  says the log was cancelled.
- When a capture finishes, it is added to the tray and the app moves to
  the **Time** stage.

### Output stimulus

You can play an excitation signal while you record, which is what you need
for a transfer-function measurement. In the **output** group:

- turn the switch **on**;
- choose the signal type: **sweep** (a linear chirp from f1 to f2),
  **white** (band-limited uniform noise) or **gaussian** (band-limited
  Gaussian noise);
- set **amp (V)** and the band **f1** and **f2** (the defaults are 0.3,
  10 Hz and 500 Hz);
- leave **match capture** ticked to play the stimulus for the whole
  capture, or untick it and set **dur (s)** for a different length; and
- optionally choose the output **device** and **out ch**, when devices are
  listed (**same as input** is the default).

While the output is on, the **Log Data** button shows an **OUT** badge.

The amplitude depends on where you run:

- **Served locally**: volts, limited to the device's output rail. A
  frequency above half the sample rate is rejected with a message. With
  no output device chosen, the stimulus plays from the input device
  itself whenever it can (a USB interface plays from its own outputs), or
  from the system default output for a microphone-only input. Playing and
  recording on one device uses a single duplex stream.
- **In the browser**: a 0 to 1 peak level, because a browser has no
  calibrated output (the box is labelled V regardless). Choosing an output
  device needs a Chromium-based browser; others use the default output.

A soundcard has one clock for input and output. So when the stimulus plays
from the device you are recording on, pydvma resamples it onto the capture
rate, and a sweep still sweeps the same frequencies. Separate input and
output devices keep their own clocks, and so does NI, subject to the
device's output rate limit.

### Pretrigger

To catch a transient such as an impact, turn on **arm** (in Setup's
trigger group or on the Acquire card; it is one switch) and set the
threshold. The capture starts when the absolute value of the trigger
channel exceeds the threshold, and keeps the samples from before it. Once
armed, the Acquire card also shows **samples** and **timeout (s)**, the
same values as in Setup's **Full** view.

While you wait, the card shows **armed — waiting for trigger…** with the
threshold. Then it shows **triggered — capturing**, with the progress bar
running, or **trigger timeout — capturing buffered data** if nothing
crossed in time. The crossing sample sits at the pretrigger sample count
you asked for.

The threshold is in volts when the full scale is known (the default is 5 %
of it) and otherwise a fraction of full scale (0.05). In the browser it is
always a fraction of full scale. The scripting equivalent is in the
[Python acquisition guide](../user-guide/acquisition.md#triggered-acquisition).

## Calibration

Set each channel's sensitivity and unit from the tray, using **cal** on a
dataset's card, not from Setup. See [Calibration and units](calibration.md).
Calibration is applied when data is displayed and fitted, so you can set
or correct it after recording. What the stored samples mean is fixed
when you record: NI hardware records volts directly, and a soundcard
records volts only when its full scale is known, from the input gain or
full scale in Setup's **levels** group.

## What runs where

| Feature | In the browser | Served locally |
| ------- | -------------- | -------------- |
| Soundcard capture | ✅ | ✅ |
| NI-DAQ capture | — | ✅ |
| Browser audio-processing switches (off by default) | ✅ | — |
| Output stimulus | ✅ (0 to 1 amplitude) | ✅ (volts, limited to the rail) |
| Pretrigger | ✅ (threshold as a fraction of full scale) | ✅ (threshold in volts when full scale is known) |
| IEPE, terminal configuration, NI voltage range | — | ✅ (NI) |
| Digital low-pass | ✅ (the analysis engine resamples) | ✅ |
| Capture rate strategy and hardware rate | — | ✅ |
| Calibrated volts from a stated gain, a fixed-gain interface, or an entered full scale | — | ✅ |

## From Python

Each Setup control has a `MySettings` argument, so a Python script can
set the same things. The rate the converter really ran at is recorded in
the capture's settings as `lpf_capture_fs` when it differs from `fs`.

| Setup control | `MySettings` argument |
| ------------- | --------------------- |
| input device | `device` (a name), or `device_driver` and `device_index` |
| sample rate | `fs` |
| channels | `channels` |
| duration | `stored_time` |
| trigger: threshold, on ch, pretrigger context, timeout | `pretrig_threshold`, `pretrig_channel`, `pretrig_samples` (`None` means no pretrigger), `pretrig_timeout` |
| digital low-pass | `lpf_on` |
| strategy, hardware rate | `oversample`, `capture_fs` |
| input gain, input mode, full scale | `input_gain_db`, `input_mode`, `VmaxSC` |
| IEPE excitation, terminal configuration, NI voltage range | `iepe_excit_current_A`, `NI_mode`, `VmaxNI`, `output_VmaxNI` |
| output group | `dvma.signal_generator(...)`, then `dvma.log_data(settings, output=y)` |

See the [Python acquisition guide](../user-guide/acquisition.md).

Next: [Live monitoring](live-monitoring.md), to check levels before you
record.
