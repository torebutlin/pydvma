# Live monitoring

Before committing to a recording it helps to *see* the incoming signal —
check levels, watch for clipping, confirm a mode is where you expect.
The web logger gives you two live views of the input: a **persistent
mini-monitor** that follows you across every stage, and a full-screen
**Live** oscilloscope.

Both run against whichever source is active — a browser soundcard or a
bridged soundcard/NI device — and both compute their spectra **in the
browser** in real time.

## The mini-monitor

In the wide layout a **Monitor** panel is docked at the foot of the
dataset tray, so it stays visible no matter which stage you are on.

- When off it shows a **▶ Start** button.
- When running it shows a compact time trace, per-channel level bars with
  a latching **CLIP** indicator, an **⤢** button to expand into the full
  Live stage, a **▾** to collapse the body, and a **Stop** button.

The monitor is **persistent** — it is not stopped automatically when you
change stages. Start it once and it keeps running until you stop it (or
close the tab).

!!! note "Narrow layout"
    On a narrow window the tray collapses to a compact rail and the
    docked mini-monitor is not shown; use the **Live** stage instead.

## The Live stage

Open **Live** (or press **⤢** on the mini-monitor) for the full
oscilloscope. Its controls live in the Live card:

- **Start Monitor** → **⏸ Pause / ▶ Resume** and **Stop** while running.
- **display** — **Stacked** (one lane per channel) and **Auto Y**
  (autoscale the amplitude axis, on by default).
- **view time** — the time window shown: 50 / 100 / 200 / 500 ms or 1 s,
  or **custom…** for any window from 20 ms to 5 s.

Inside the plot region a bar of chips toggles the panes:

- **T time** — the oscilloscope trace.
- **F freq** — the live spectrum (see below).
- **L levels** — the per-channel level bars with the CLIP latch.
- **P pause** — freeze the display.

### Live spectrum: FFT or Welch PSD

The **F freq** pane has its own controls:

- **spectrum** — **FFT** (a per-frame amplitude spectrum) or **PSD** (an
  averaged Welch power spectral density).
- **fft axes** — magnitude **dB / lin**, and frequency **lin f / log f**.
- **fft freq** — **Full** (DC to Nyquist) or **Range** (enter a min/max
  band).

In **PSD** mode two more controls appear: **averages** (1× to 16×, how
many overlapping Welch segments to average — steadier but slower to
respond) and **smoothing** (off / low / high — exponential smoothing
across frames). PSD is displayed in dB/Hz (or linear u²/Hz).

The FFT/PSD is a windowed (Hann) transform computed in the browser
every frame, so it works identically whether the source is Web Audio or
the bridge.

### Levels and clipping

The level bars fill green → amber → red with the signal peak. The
**CLIP** pill **latches** as soon as any channel's peak reaches 0.95 of
full scale, and stays lit until you click it (or restart the monitor) —
so you never miss a brief clip that happened while you were looking
elsewhere. If CLIP trips, reduce the input level or (on NI) widen the
voltage range before recording.

## Tips

- Use Live to set levels first, then switch to **Acquire** to record —
  the mini-monitor keeps running so you can watch levels during setup.
- Watch coherence in the [TF stage](analysis.md) *after* recording, but
  catch gross problems (clipping, dead channels, wrong device) live —
  it is much cheaper than re-recording.

Next: [Analysis views](analysis.md).
