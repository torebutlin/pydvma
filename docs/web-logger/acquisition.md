# Acquisition and setup

The web logger acquires data in the **Setup** and **Acquire** stages.
Setup is where you choose the device, sample rate, channels and duration
(plus National Instruments options when running through the bridge);
Acquire is where you record, optionally with a pretrigger and an output
stimulus.

Which capabilities you see depends on the mode you are in (see
[the three modes](index.md)):

- In the **Pages app** (browser Web Audio) you can capture from a
  soundcard.
- Through the **local bridge** (`pydvma-serve`) you additionally get
  NI-DAQ hardware, an output stimulus, and pretrigger arming.

## Setup

Setup starts in **Basic** mode; the **Full ▾** button reveals advanced
settings.

### Basic controls

| Control | What it does |
| ------- | ------------ |
| **input device** | Pick the acquisition device. Defaults to the system default; **↻** refreshes the list. In the browser, device *names* only appear once you grant microphone access. |
| **sample rate** | Choose from the rates the device can *deliver*. In the browser this is the standard ladder (8k / 16k / 22.05k / 44.1k / 48k / 96k) constrained by the device; through the bridge it is the device's own ladder — the rates the hardware genuinely runs, plus the standard rates *below* its floor, which pydvma delivers by capturing natively and decimating. Rates above the ceiling, or between rungs, are not offered, because nothing can produce them. Unsupported rates are shown disabled, and a note reads `captures at 44100 Hz, resampled to 8000 Hz` when the rate you pick is not one the converter itself runs. |
| **channels** | Number of input channels (1 up to the device maximum). Not every input a device reports is an analogue one: a Focusrite Scarlett 2i2 4th Gen advertises four, but 3–4 are a digital loopback of its own output mix. Setup says so — `channels 3+ are the device's digital loopback, not inputs` — as soon as the count reaches them. |
| **duration** | Capture length: 0.5, 1, 2, 5, 10, 30 or 60 s. |

Defaults are 44.1 kHz, 1 channel, 2 s.

!!! note "Browser (Web Audio) mode — allow the microphone"
    A browser hides audio device names until you grant permission. Click
    **Allow microphone access** to reveal device names and each device's
    capability ranges. Capture works either way, but you cannot pick a
    named device without it.

### Full (advanced) controls

**Full ▾** adds:

- **device capabilities** — a read-only readout of the selected device's
  channel count, sample-rate range and latency. The rates the hardware
  itself runs (its `native_rates`) are reported separately from the rates
  the picker offers, which also include the lower ones pydvma reaches by
  capturing natively and decimating.
- **processing (off = raw measurement)** — three toggles, all **off by
  default**: **echo cancel**, **noise suppress**, **auto gain**. These
  are browser audio-processing features that silently alter a signal;
  pydvma leaves them off so a measurement is not filtered behind your
  back. Turn them on only if you actually want them.
- **digital low-pass** — an **oversample + decimate** toggle, off by
  default (see below).
- **timing** — an optional latency hint (ms); blank uses the browser
  default.

### Capture rate and delivered rate

The **sample rate** you choose is the rate the logged data ends up at.
It is not always the rate the converter runs at: hardware only runs at
the rates it has. Where the two differ, pydvma captures at a rate the
device really supports and resamples to yours behind a linear-phase
anti-alias filter (passband to fs/2.56, ≥ 96 dB stopband at fs/2 — the
same guard-band convention a delta-sigma module's hardware anti-alias
filter uses; zero-phase, so transfer functions and modal fits are
unaffected).

Three things put the two rates apart:

- **The device cannot run at your fs.** Sound-card rate ladders start at
  44.1 kHz, so a 3 kHz log is captured at 44.1 kHz and decimated. This
  happens with the digital low-pass **off** — pydvma does the conversion
  itself rather than leave it to the operating system, whose own
  resampler is silent, is only as good as the ratio between the rate you
  asked for and whatever rate the last application left the device at,
  and was measured at as little as 12 dB of alias rejection with up to
  4.3 dB of passband droop.
- **The digital low-pass is on**, which runs the capture above fs
  deliberately (below).
- **A capture rate was set explicitly** — `MySettings(capture_fs=…)` for
  Python users — which forces the converter's rate outright.

Setup shows the real capture rate as a note (`captures at 44100 Hz,
resampled to 8000 Hz`), and the logged settings record it as
`lpf_capture_fs` whenever it differs from fs. On macOS pydvma also pins
the device's hardware clock to the capture rate for the duration of the
stream and restores it afterwards, because PortAudio never retunes the
clock itself.

### Digital low-pass

The **digital low-pass** toggle asks for the capture to be run *above*
fs on purpose, and for the extra band to be filtered away as the record
is resampled down. Your fs setting keeps its meaning throughout — it is
still the rate the logged data ends up at.

Why you might want it on:

- **Anti-aliasing.** Multiplexed-SAR hardware (NI USB-6003/6212) has
  **no analogue anti-alias filter**: logging directly at a low fs lets
  any content above fs/2 fold straight into your band. The
  oversample+decimate chain removes it before the rate drops —
  effectively giving those devices the anti-alias behaviour a DSA module
  (NI 9234) has in silicon.
- **Noise reduction.** Rejecting the out-of-band noise buys roughly
  10·log₁₀(oversample factor) dB of broadband-noise process gain.

How far above fs the capture runs follows from the converter, since that
is the fact the choice turns on (`MySettings(oversample=…)` overrides
it):

- A converter that **anti-aliases in silicon** — every audio interface,
  and NI DSA modules like the 9234 — captures at the lowest available
  rate at or above **2.56 × fs** (2.56 because the resampler's passband
  runs to fs/2.56). Content above the capture Nyquist is already gone
  before the ADC, so capturing faster rejects nothing extra; it only
  multiplies the data volume. Ask for `oversample='highest'` when the
  noise process gain matters more than the size of the record.
- A converter with **no anti-alias filter** (USB-6003/6212) captures as
  fast as it will go, because there a high capture rate is the only
  alias protection there is.

On the bridge the server runs the whole chain
(`MySettings(lpf_on=True)` for Python users); in the browser the page
records at the audio context's native rate and the engine resamples. If
there is no headroom to oversample into — your fs is already the lowest
rate the device can run, or, on a device with no published ladder, its
maximum is below 2·fs — the log proceeds unfiltered with a note.

!!! warning "Measurement audio, not a phone call"
    The default-off echo/noise/auto-gain toggles are the single most
    important reason to prefer these settings for measurement work — a
    browser's defaults are tuned for voice calls and will distort a
    calibrated measurement. Leave them off unless you have a reason not
    to.

### NI-DAQ options (bridge only)

When you open the app through `pydvma-serve --driver nidaq` and it
reports NI hardware, Setup's **Full** view gains an **NI-DAQ** group:

- **IEPE excitation** — off or 2 mA, for powering ICP/IEPE
  accelerometers (DSA modules only).
- **terminal configuration** — default / RSE / NRSE / differential.
- **pretrigger** — samples (blank = free-run), threshold, and channel.
- **NI voltage range (±V)** — input and output full-scale, each clamped
  to the device's real rails (so you cannot request a voltage the
  hardware will refuse). A note appears when the output must be clamped
  below the default (e.g. the NI 9260's ±4.24 V rail).

These controls are **hidden in the browser Web Audio mode** — they need
the native NI driver behind the bridge. Full details, device
differences, and the sample-rate coercion behaviour are on the
[NI hardware page](ni-hardware.md).

!!! info "Discrete rate ladders"
    Most measurement hardware runs a fixed set of rates rather than a
    continuum — audio interfaces from 44.1 kHz upward, NI delta-sigma
    modules on their internal divider ladder — so the rate you ask for is
    not always one the device has. A DSA module snaps an off-ladder
    request to the nearest legal value; Setup and Acquire then show a
    note reading the real rate the device adopted, and every axis uses
    that true rate. Where pydvma covers the gap itself instead, the note
    reads `captures at 44100 Hz, resampled to 8000 Hz`. See
    [NI hardware](ni-hardware.md#sample-rate-ladders-and-coercion).

## Acquire

The Acquire stage records a capture.

- A **summary chip** shows the pending capture at a glance —
  `fs · channels · duration · device · pretrigger` (and the output
  stimulus when armed). Click it, or **Edit**, to jump back to Setup.
- **Log Data** records. While recording it shows progress and becomes a
  **Cancel** button.
- On success the recording is added to your dataset tray and the app
  switches to the **Time** stage.

### Output stimulus

You can play an excitation signal during the capture — useful for
transfer-function measurements. In the **output** group:

- turn output **on**;
- pick a **type**: **sweep** (a linear chirp from *f1* to *f2*),
  **white** (band-limited uniform noise), or **gaussian** (band-limited
  Gaussian noise);
- set the **amplitude**, the band **f1**/**f2**, and optionally the
  output **duration**, **device** and **channel**.

When output is armed the **Log Data** button carries an **OUT** badge.

On the **bridge** the stimulus is generated by pydvma's own
`signal_generator` (identical to the desktop logger), amplitude is in
volts clamped to the device's output rail, and a frequency above
Nyquist (`fs/2`) is rejected with a clear message. In the **browser**
the same signal definitions play through the audio output (amplitude
is a normalised 0–1 peak — there is no calibrated DAC in a browser);
output-device selection needs Chromium (`setSinkId`) and falls back to
the default output elsewhere.

A sound card has **one clock for input and output**, so when the
stimulus plays out of the same device you are capturing on, it cannot
run at its own rate: pydvma resamples the generated waveform onto the
capture rate (preserving the physical signal, so a sweep still sweeps
the frequencies it was generated for) and rewrites `output_fs` to match.
Separate input and output devices keep independent clocks and may differ
freely; so may NI, whose AO rate is configured independently of the AI
stream, subject to the device's own AO rate limit.

### Pretrigger

To catch a transient (an impact, say), enable **arm** in the pretrigger
group. When armed you set the number of **samples** to keep *before* the
trigger and a **timeout**. During the capture the app shows the trigger
lifecycle — *armed — waiting for trigger* → *triggered — capturing* (or
*trigger timeout — capturing buffered data* if nothing crosses in time).

The pretrigger crossing lands at exactly the requested pre-trigger
sample count — on the bridge this is hardware-verified; in the browser
the same windowing runs on the Web Audio stream (fixed 0.05 threshold
for now; a threshold control is a noted follow-up). See the scripting
equivalent in the
[Python acquisition guide](../user-guide/acquisition.md#triggered-acquisition).

## Calibration

Per-channel sensitivity and engineering units are set from the tray (the
**cal** button on a dataset card), not from Setup — see
[Calibration and units](calibration.md). Captures are always stored in
volts; that calibration is applied at display and fit time, so you can
set or correct it after recording without losing anything.

What the samples are *in volts* is fixed at capture time, and on an
audio interface that depends on the preamp gain — a front-panel control
no audio API exposes, so pydvma cannot read it. State it instead, with
`MySettings(input_gain_db=…, input_mode='line'|'inst'|'mic')` in Python
or in a `pydvma-serve --settings` file, and the input full scale
(`VmaxSC`) is derived from the interface's published maximum input level
— see
[Soundcard input gain](calibration.md#soundcard-input-gain-and-full-scale).
NI inputs take their full scale from the voltage range instead
(`VmaxNI`), which *is* in Setup's NI group.

## What runs where — quick reference

| Feature | Browser (Web Audio) | Local bridge |
| ------- | ------------------- | ------------ |
| Soundcard capture | ✅ | ✅ |
| NI-DAQ capture | — | ✅ (`[ni]`) |
| Echo/noise/auto-gain off by default | ✅ | ✅ |
| Output stimulus | ✅ (normalised amplitude) | ✅ (volts, rail-clamped) |
| Pretrigger | ✅ (fixed threshold) | ✅ |
| IEPE / terminal config / voltage rails | — | ✅ (NI) |
| Capture above/below fs, resampled to fs | ✅ (engine resamples) | ✅ |
| Stated preamp gain → calibrated volts | — | ✅ (characterised interfaces) |

Next: [Live monitoring](live-monitoring.md) to check levels before you
commit to a recording.
