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
| **sample rate** | Choose from the device's supported rates. In the browser this is the standard ladder (8k / 16k / 22.05k / 44.1k / 48k / 96k) constrained by the device; through the bridge it is the device's own rate ladder. Unsupported rates are shown disabled. |
| **channels** | Number of input channels (1 up to the device maximum). |
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
  channel count, sample-rate range and latency.
- **processing (off = raw measurement)** — three toggles, all **off by
  default**: **echo cancel**, **noise suppress**, **auto gain**. These
  are browser audio-processing features that silently alter a signal;
  pydvma leaves them off so a measurement is not filtered behind your
  back. Turn them on only if you actually want them.
- **digital low-pass** — an **oversample + decimate** toggle, off by
  default (see below).
- **timing** — an optional latency hint (ms); blank uses the browser
  default.

### Digital low-pass

With the **digital low-pass** on, your **fs** setting keeps its meaning
— it is still the rate the logged data ends up at — but the capture is
made differently: the device samples at its **highest available rate**
and the record is resampled down to fs behind a linear-phase
anti-alias filter (passband to fs/2.56, ≥ 96 dB stopband at fs/2 —
the same guard-band convention a delta-sigma module's hardware
anti-alias filter uses; zero-phase, so transfer functions and modal
fits are unaffected).

Why you might want it on:

- **Anti-aliasing.** Multiplexed-SAR hardware (NI USB-6003/6212, most
  sound cards) has **no analogue anti-alias filter**: logging directly
  at a low fs lets any content above fs/2 fold straight into your
  band. The oversample+decimate chain removes it before the rate
  drops — effectively giving those devices the anti-alias behaviour a
  DSA module (NI 9234) has in silicon.
- **Noise reduction.** Rejecting the out-of-band noise buys roughly
  10·log₁₀(oversample factor) dB of broadband-noise process gain.

On the bridge the server runs the whole chain
(`MySettings(lpf_on=True)` for Python users — the logged settings
record the capture rate as `lpf_capture_fs`); in the browser the page
records at the audio context's native rate and the engine resamples.
If the device has no oversampling headroom (its maximum rate is below
2·fs), the log proceeds unfiltered with a note.

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

!!! info "DSA sample-rate coercion"
    Delta-sigma modules snap off-ladder rates to the nearest legal value.
    When that happens, Setup and Acquire show a note reading the real
    rate the device adopted, and every axis uses that true rate. See
    [NI hardware](ni-hardware.md#dsa-modules-sample-rate-coercion).

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
volts; calibration is applied at display and fit time, so you can set or
correct it after recording without losing anything.

## What runs where — quick reference

| Feature | Browser (Web Audio) | Local bridge |
| ------- | ------------------- | ------------ |
| Soundcard capture | ✅ | ✅ |
| NI-DAQ capture | — | ✅ (`[ni]`) |
| Echo/noise/auto-gain off by default | ✅ | ✅ |
| Output stimulus | ✅ (normalised amplitude) | ✅ (volts, rail-clamped) |
| Pretrigger | ✅ (fixed threshold) | ✅ |
| IEPE / terminal config / voltage rails | — | ✅ (NI) |

Next: [Live monitoring](live-monitoring.md) to check levels before you
commit to a recording.
