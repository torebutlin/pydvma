# Live monitoring

Before you record, it helps to see the incoming signal: check the levels,
watch for clipping, and confirm a mode is where you expect. The web logger
gives you two live views of the input: a **monitor** panel that stays with
you on every stage, and a full-screen **Live** oscilloscope.

Both show whichever input is active: a browser soundcard, or a soundcard
or NI device when the app is [served locally](running-locally.md). The
Live stage computes its spectrum in the browser as the signal arrives.

## The monitor panel

In the wide layout a **Monitor** panel sits at the foot of the dataset
tray, so it stays visible on whichever stage you are on.

- When it is off it shows **▶ Start**.
- When it is running it shows a small time trace, a level bar for each
  channel with a **CLIP** indicator, **⤢** to open the full Live stage
  (clicking the trace does the same), **▾** to collapse the panel body,
  and **Stop**.

It keeps running when you change stage. Start it once and it runs until
you press **Stop** or close the tab.

On a narrow window the tray shrinks to a rail. The rail keeps a small
strip with the level bars and a **C** clip indicator; click it to open the
Live stage.

## The Live stage

Open **Live**, or press **⤢** on the monitor, for the full oscilloscope.
The Live card has these controls:

- **Start Monitor**, which becomes **⏸ Pause** or **▶ Resume**, and
  **Stop**, while it runs.
- **display**: **Stacked** puts each channel in its own lane. **Auto Y**
  fits the amplitude axis automatically, and is on by default.
- **view time**: how much time the trace shows. Choose 50, 100, 200 or
  500 ms, or 1, 2, 5 or 10 s, or choose **custom…** and type a value from
  0.02 s up to a limit set by memory (at most 30 s, less at high sample
  rates with many channels).

Four chips in the plot area show or hide the panes:

- **T time**: the oscilloscope trace.
- **F freq**: the live spectrum.
- **L levels**: the level bars and the **CLIP** indicator.
- **P pause**: freezes the display.

### Live spectrum: FFT or PSD

- **spectrum**: **FFT** shows a per-frame amplitude spectrum. **PSD**
  shows an averaged Welch power spectral density, in dB/Hz or, on a linear
  axis, u²/Hz. Both use a Hann window.
- **fft axes**: magnitude in **dB** or **lin**, and frequency on a **lin
  f** or **log f** axis.
- **fft freq**: **Full** shows DC to the Nyquist frequency. **Range** lets
  you type a minimum and maximum in hertz; a blank box means 0 or Nyquist.

In **PSD** mode two more controls appear:

- **averages**: 1× to 16× (1, 2, 4, 8 or 16) overlapping segments
  averaged. More averages give a steadier trace that responds more
  slowly.
- **smoothing**: **off**, **low** or **high** exponential smoothing
  across frames.

The Live spectrum is in the input's own units and is not calibrated. It
is not the same quantity as the **PSD** on the
[Frequency stage](analysis.md#frequency).

### Levels and clipping

Each level bar fills from green through amber to red as the peak rises.
The **CLIP** indicator lights as soon as any channel's peak reaches 95 %
of full scale, and stays lit until you click it or restart the monitor,
so you don't miss a brief clip. If it lights, lower the input level, or on
NI widen the voltage range, before recording.

Full scale depends on the input:

- an NI card: the input range you set in Setup, for example ±5 V, so a 3 V
  peak reads 60 % and does not light **CLIP**;
- a soundcard whose full scale is known: the full-scale voltage from its
  [calibration](calibration.md#soundcard-input-gain-and-full-scale); and
- the browser, or a soundcard with no known full scale: 1.0, the top of
  the converter's range.

Hover a bar to see its percentage, and its reading in volts where full
scale is a voltage. Setup's **input level** readout
([Acquisition and setup](acquisition.md#full-controls)) reports the same
peaks with advice.

## Tips

- Set your levels on **Live**, then switch to **Acquire** to record. The
  monitor keeps running, so you can watch the levels while you set up.
- Catch gross problems here (clipping, a dead channel, the wrong device).
  It is much cheaper than re-recording. Coherence, on the
  [TF stage](analysis.md#tf-transfer-functions), tells you about the
  measurement after the fact.

Next: [Analysis views](analysis.md).
