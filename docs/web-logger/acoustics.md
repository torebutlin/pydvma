# Acoustic measurements

pydvma records microphones as it records any other sensor: the audio
interface turns the mic's voltage into samples, pydvma turns the samples
back into volts, and a sensitivity in V/Pa turns volts into pascals. For
sound it adds the standard pieces on top: sound pressure level in dB re
20 µPa, A- and C-weighting, octave and third-octave band levels, and
calibration from an acoustic calibrator.

This page uses the **Audient iD44 (MkII)** with **Earthworks M23**
measurement microphones, the setup pydvma was built and checked with.
Any interface works the same way; what differs is how pydvma learns the
interface's full scale (see
[Soundcard input gain and full scale](calibration.md#soundcard-input-gain-and-full-scale)).

## Connecting the iD44

Run the app [served locally](running-locally.md) (`pydvma-serve` or
`dvma.launch`), which is what reads the iD44 in volts. The browser-only
app records fractions of full scale and cannot set the rate.

- **Microphones** go into the XLR combo inputs 1 to 4. Switch on **48 V**
  phantom power for each condenser mic (the M23 needs it).
- Leave the **100 Hz high-pass** switch off unless you want it: pydvma
  can't see it, and it removes real low-frequency content (cars have a
  lot).
- If speakers are on the iD44's outputs, **mute the inputs in the iD
  mixer**, or the mics are fed back to the speakers.
- **Inputs 5 to 20** are the optical (ADAT) inputs, from an external
  preamp. pydvma can't know that preamp's full scale, so these channels
  record in fractions of full scale. Calibrate each one with a
  [calibrator](#from-a-calibrator), which works in any units.
- **Inputs 21 and 22** are the iD44's digital loop-back of its own
  playback, not inputs. Setup says so.

The iD44 runs at 44.1, 48, 88.2 or 96 kHz. When you choose it, Setup
sets **48 kHz**. pydvma sets the interface's rate itself for each
recording and puts it back after. There is no rate menu in the iD app
on a Mac. Changing the rate restarts the iD mixer, which clicks the
outputs, so settle on one rate rather than switching back and forth.

For a lower rate (to keep long recordings small), type it in Setup's
rate box, for example `8000` or `8k`. The iD44 can't run below 44.1 kHz,
so pydvma records at 48 kHz and filters and resamples down, keeping the
iD44 at 48 kHz throughout.

## State the gain of each channel

The gain knobs on the iD44 are analogue, and no software can read them.
pydvma needs each channel's gain to turn samples into volts, so you state
it. In **Setup**, press **Full ▾**, then find **input gain per channel
(for calibrated volts)**. Each channel has a row:

- the **input mode**: `mic` for an XLR mic, `line` for a jack, `inst`
  for the front DI inputs (channels 1 and 2 only);
- the gain in dB, with **bottom** and **top** buttons that fill in the
  knob's end stops (mic 0 and +60 dB, line −10 and +50 dB, from
  Audient's manual);
- **pad**, if the −10 dB pad switch is in;
- the full scale that follows, for example `±0.01 V full scale`. A row
  with no gain reads `full-scale units (gain not stated)`.

The end stops are the only knob positions you can set repeatably. The
iD44 used to build this measured **+50.46 dB** at the top stop of channel
2's line input, against the manual's +50 dB, so its mic input is about
+60.5 dB at the top stop. Expect about ±0.5 dB from unit to unit.
Between the stops, type the gain in, but use a calibrator to get an
accurate sensitivity.

**Choosing a stop.** With the M23 (33.5 mV/Pa) on a mic input, the
loudest sine that fits is:

| gain knob | pad | full scale | suits |
|---|---|---|---|
| top (+60 dB) | out | 79 dB SPL | quiet rooms |
| top (+60 dB) | in | 89 dB SPL | moderate noise |
| bottom (0 dB) | out | 139 dB SPL | cars, machinery, anything loud |

Louder sound clips. Cars at speed can exceed 79 dB SPL, especially at
low frequencies. At the bottom stop nothing realistic clips, and the
interface's own noise, roughly 20 to 25 dB SPL (estimated from Audient's
published converter figures), is far below a car's. In a very quiet
room the top stop keeps the floor at the microphone's own noise. Setup's
level bars and the clip warning judge each channel against its own full
scale.

**From Python**, give `MySettings` a value per channel. A single value
means every channel.

```python
import pydvma as dvma

settings = dvma.MySettings(
    device='iD44',               # matched by name
    channels=4,
    fs=48000,
    stored_time=300,             # five minutes
    input_mode='mic',            # the default is 'line', so say 'mic'
    input_gain_db=[60, 60, 60, 60],
    input_pad=[False, False, False, False],
)
data = dvma.log_data(settings)
```

A channel whose gain is `None` records in fractions of full scale.
`settings.input_vmax_channels()` lists each channel's full scale in
volts, and `settings.channels_in_volts()` says which are in volts.

### Using your own unit's measured gains

The **top** and **bottom** buttons fill in Audient's figures. A real
unit's stops sit a little off them, and differently on each channel. The
iD44 this was built with measured (line input, 1 kHz, 2026-11-09):

| channel | top stop | bottom stop |
|---|---:|---:|
| 1 | +50.51 dB | −9.92 dB |
| 2 | +50.46 dB | −9.69 dB |
| 3 | +50.59 dB | −9.43 dB |
| 4 | +50.46 dB | −9.21 dB |
| Audient's figure | +50 dB | −10 dB |

and its pad measured 9.98 dB. The mic input is the line input plus
10 dB, so channel 1's mic top stop is +60.51 dB. Pressing **top** on that
unit reads about 0.5 dB high. For your own unit, measure the stops once
(see [Checking the interface](#checking-the-interface)), then **type the
measured gain** instead of pressing the button, e.g. `60.51` for channel
1 at its top stop.

pydvma doesn't store per-unit figures, and Setup forgets the gains you
type when the page reloads. So keep them in the code that starts the
session, which pre-fills Setup every time:

```python
import pydvma as dvma

# this iD44, mic inputs at the top stop, pad out
settings = dvma.MySettings(
    device='iD44', channels=4, fs=48000,
    input_mode='mic',
    input_gain_db=[60.51, 60.46, 60.59, 60.46],
)
session = dvma.launch(settings)
```

At the bottom stops the same unit is `[0.08, 0.31, 0.57, 0.79]`.

Between the stops the printed dial marks are only a rough guide. On that
unit's channel 1 (mic input, set by eye):

| mark | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gain, dB | 0.1 | 0.5 | 2.6 | 6.7 | 13.8 | 20.3 | 25.4 | 32.1 | 39.4 | 47.9 | 60.5 |

The steps are uneven, and the last mark alone spans 12.7 dB, so a
setting between 9 and 10 is uncertain by a few dB. Use a stop, or
calibrate with a calibrator at the gain you set. Then
calibrate each microphone once with **use for new recordings too**
ticked (below). The browser remembers that, so the next session needs
only the launch.

For a script that records with `dvma.log_data` and no app, also give
each mic's sensitivity and set the unit:

```python
settings = dvma.MySettings(
    device='iD44', channels=4, fs=48000, stored_time=300,
    input_mode='mic',
    input_gain_db=[60.51, 60.46, 60.59, 60.46],
    channel_sensitivities=[0.0335, 0.0335, 0.0335, 0.0335],  # V/Pa, each mic's own
)
data = dvma.log_data(settings)
data.time_data_list[-1].units = ['Pa'] * 4
```

## Calibrating to pascals

### From the spec sheet

Record something, then open the calibration dialog (**cal** on the
dataset's card in the tray). Enter the mic's sensitivity in **volts per
pascal**, and set the unit to **Pa**. The M23 used here is 33.5 mV/Pa, so
enter `0.0335`. This works only on a channel whose gain is stated, since
the sensitivity is per volt.

### From a calibrator

An acoustic calibrator plays a known level, usually 94 dB SPL (1 Pa rms)
at 1 kHz. Record its tone, then press **ref tone** on that channel's row
of the calibration dialog. The steps are under
[From a reference tone](calibration.md#from-a-reference-tone).

Mind the full scale: a 94 dB calibrator clips the M23 at the top stop
(full scale 79 dB SPL). Turn the gain down until the tone fits. On a
channel whose gain is stated the sensitivity comes out in V/Pa, which
belongs to the microphone, so it still holds when you turn the gain
back up and state the new gain. It is then as accurate as the two stated
gains. Calibrating at the gain you will measure at avoids that
dependence.

### For the recordings that follow

Tick **use for new recordings too** in the calibration dialog, and every
later recording from the iD44 arrives in pascals. If a later recording
states a different gain or pad on that channel, the app warns you. See
[Use it for new recordings too](calibration.md#use-it-for-new-recordings-too).

Each calibrated channel's file records how its calibration was made:
spec sheet or reference tone, the date, the calibrator's level and
frequency, and the gain and pad you stated.

## Sound pressure level, weighting and bands

Once every line on the plot is in **Pa**, the frequency view's dB axes
read in dB SPL: `Magnitude (dB re 20 µPa)` for **FFT**, and
`PSD (dB re (20 µPa)²/Hz)` for **PSD**. Lines in any other unit keep the
usual labels.

**weighting** (FFT, Power and PSD) applies **A** or **C** frequency
weighting, or **Z** for none. It changes only what is drawn, like the
x(iω) display. The data and every calculation stay unweighted, and the
axis label says `dB(A)` or `dB(C)`. The curves are the analytic ones of
IEC 61672-1, 0 dB at 1 kHz. A-weighting follows the ear's sensitivity at
moderate levels. C-weighting is nearly flat and keeps the low frequencies
that A-weighting removes, which matters for car and machinery noise.

**bands** (Power and PSD) draws **octave** or **one-third-octave** band
levels as steps over the spectrum, with the IEC 61260 base-10 centres
(31.5, 63, 125 Hz, …). Each band's power is summed from the density
within it, so it is right for broadband sound and for tones alike, and it
follows the weighting. In **Power** mode a step is the band's power, so
in Pa it reads directly as the band's dB SPL. In **PSD** mode a step is
that power divided by the bandwidth, which puts it at the level of the
density around it. Bands with fewer than three frequency bins are left
out, so for the lowest third-octaves use a finer frequency resolution
(fewer averaging frames, or a longer recording).

For **frequency content over time**, use the sonogram (STFT). A CWT of
minutes of audio is far too large, and the app says so instead of
running it.

**From Python**, the same calculations are in `pydvma.acoustics`:
`weighting_db(f, 'A')`, `band_levels(f, psd, 'third-octave', 'A')` and
`P_REF` (20 µPa). See [Analysis](../api/analysis.md#acoustics).

## Long recordings

Recordings of several minutes work through `pydvma-serve` and
`dvma.launch`, with the analysis on the native engine: capture, PSD,
sonogram, save, reload and restoring after the tab closes. Measured with
4 channels for 5 minutes at 48 kHz (576 MB): a PSD takes about 6 s, a
sonogram of one channel about 6 s, and saving or reloading under a second.
A `.dvma` file of a long recording is stored uncompressed, so it is about
the size of the data (576 MB for that recording), and saving it is fast.

The server keeps a copy of the session on disk, about the size of the
data, and rewrites it after each change: see
[Your session is kept safe](running-locally.md#your-session-is-kept-safe).

A recording takes 384 kB per channel per second at 48 kHz, plus 384 kB
per second for its time axis: 8 MB per second for 20 channels. The limits
that follow:

- **Analysis and saving** take up to 4 GB in one go: about **9 minutes of
  20 channels** at 48 kHz, 4.5 minutes at 96 kHz, or 37 minutes of 4
  channels. Analysis results saved with the data count towards the same
  4 GB. (Measured on a Mac. On Windows a request over about 2 GB may not
  get through to the analysis: about 4.5 minutes of 20 channels.)
- **The PSD's frequency resolution** matters more at many channels. Over
  minutes of data, the default 10 averaging frames give a very fine Δf,
  and the coherence the PSD also returns grows with the square of the
  channel count: about 4.8 GB for 20 channels over 5 minutes. With many
  channels, set a coarser Δf first (1 s frames: under 100 MB).
- **The browser** holds each recording several times over. 20 channels
  for 5 minutes is 2.4 GB per copy, which is the most likely thing to
  fail. Not yet measured in a real browser.

The sample rate sets the size directly. If the sound you care about is
below 4 kHz, recording at 8 or 16 kHz cuts everything by 3 to 6 times,
with the iD44 still running at 48 kHz.

## Checking the interface

`dev/id44_hw_check.py` in the repository is a headless check of an iD44
on a Mac. It confirms the rate ladder, that the rate is 48 kHz and stays
there, 24-bit capture, and that the loop-back inputs return DAW 1+2
exactly. With a cable from line output 3 (outputs 3+4 set to **DAW
THRU** in the iD app) into an input, `--daw-thru-channel N` measures that
input's gain against the line output's rated +18 dBu, and
`--line-gain-db G` checks that pydvma reads the input in volts.

## Not yet

Planned but not built: noise statistics (Leq, L10, L90 and the like),
correcting a mic's frequency response from its calibration chart,
fast/slow time-weighted SPL, and a dB SPL readout on the live scope.
The iD44 has not yet been tried on Windows. Audient's manual is on
[audient.com](https://audient.com).
