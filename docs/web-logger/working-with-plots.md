# Working with plots

Every stage that draws a plot shares the same tools: the **tray** of
datasets on the left, a **legend** over the plot, and a **zoom toolbar**
above it. The frequency views add a **frequency navigator** strip. This
page describes all four, so the stage pages ([Analysis](analysis.md),
[Nonlin](nonlin.md), [Modal fitting](modal-fitting.md)) don't repeat them.

## The dataset tray

The tray lists every dataset with its name, duration and a stack of its
channels. It is on the left in the wide layout.

- **All** and **None** show or hide every line. **Solo** shows only the
  highlighted set, or only the highlighted channel when one set is
  loaded.
- **‹ ›** move the highlight to the previous or next set, or to the
  previous or next channel when one set is loaded.
- With a subset of lines showing (some on, some off), **‹ ›** shift the
  whole selection one channel along instead, wrapping at the ends. Two
  lines you picked stay a pair as they move, and a measured channel
  moves together with its fit line, which is a quick way to compare each
  channel with its fit in turn.
- Click a set's name to cycle the whole set: **on**, **faded** (drawn
  dimmed), **off**. Double-click the name, or press **F2**, to rename it.
- Expand a set to switch individual channels on, faded or off. Double-click
  a channel name to rename it.
- The channel numbers across the top cycle that channel through on,
  faded and off in **all** sets at once.
- **cal** (shown on hover) opens the [calibration dialog](calibration.md).
  **×** deletes the set. On the **Modal fit** card the **×** clears the
  fit, and a message offers **Undo**.
- **⚠ source changed** appears on a set whose saved FFT or transfer
  function was computed from earlier time data. Click it to recompute.

## The legend

A **legend** floats over the plot with one row per line. Click a row to
cycle that line **on**, **faded**, **off**, as in the tray. Lines that
are off stay listed, struck through, so you can bring them back.

Drag the legend anywhere, or choose a corner in
[the toolbar's panel](#the-zoom-toolbar). With more than
ten lines it flows into two or three columns. A small button in its
corner (visible on hover) switches to a **compact** view: a grid of
coloured dots with one row per set and one column per channel. Each dot
works like its full row, and hovering shows the full label.

## The zoom toolbar

The toolbar sits above the plot, so it never covers your data.

- **Box zoom** and **Pan** set what dragging on the plot does.
  **↶** and **↷** step back and forward through your view changes.
- **Auto X** and **Auto Y** return an axis to automatic fitting (on a
  Nyquist plot they read **Auto Re** and **Auto Im**). An automatic axis
  keeps re-fitting as data arrives or lines are switched on and off,
  until you next zoom. Automatic y fits only the visible lines, and only
  the samples inside the current x window, so a zoomed stretch fills the
  plot.
- **x lin / log** sets the frequency axis on the Frequency and TF views
  (not Nyquist). **y dB / lin** sets magnitude between dB and linear on
  the FFT, Power and PSD views and on the TF **Mag (dB)** and **Bode**
  plots. On the Sonogram, **y lin / log** sets the frequency axis and
  **colour dB / lin** sets how the heat map is coloured.
- The **frequency navigator** button (the strip icon) shows or hides the
  [navigator](#frequency-navigator).
- The chevron at the right end of the toolbar opens a panel when you
  hover over it; click it to keep the panel open. It holds:
    - **manual axis limits**, applied as you type;
    - **Legend**: show or hide, and place it in a corner (**NW**, **NE**,
      **SW**, **SE**) or **Outside**;
    - on a **Bode** plot, **phase y**, set to **±180°** or **auto**; and
    - on a plot with a coherence overlay, **coherence**, set to **0–1**
      or **auto** for the right-hand axis.

Axes refit themselves when the plot's meaning changes. New data arriving
in a view (a capture, a loaded file, a first calculation) refits y.
Changing the quantity, the plot type, dB or linear, or the calibration
resets y to automatic, because the units change. A window you zoomed to
on purpose is kept when you recompute an existing result.

## Frequency navigator

On the **Frequency** and **TF** views the navigator shows the magnitude
of the visible lines across the whole measured bandwidth, in a slim strip
above the plot. A highlighted band marks the current frequency window,
the same window that **Calc** and **Fit** use.

- Drag the band to move along frequency. The plot follows as you drag.
- Drag either edge of the band to resize it.
- Drag on empty strip to draw a new window.
- Type exact limits in the **min** and **max** boxes, in hertz.
- Double-click the strip to reset the window to the scope, or to the full
  range when the strip is not scoped.

Each drag is one undo step.

The **‹ ›** buttons jump the window to the previous or next spectral
peak, keeping its width. Peaks are found on the curves you see in the
strip. From a window that spans nearly the whole strip, the first press
narrows it to a tenth of the strip so the jump is meaningful. Once you
have [fitted modes](modal-fitting.md), each one is marked with a small
triangle on the strip, so the unmarked peaks are the ones still to fit.

**⤢** narrows the strip itself to the current window, which helps when
the measurement covers much more bandwidth than you care about. A thin
ribbon then appears above the strip showing where the scope sits in the
full range; drag the ribbon's band to move or resize the scope. The
button becomes **⤡**: click it, or double-click the ribbon, to clear the
scope. The scope changes only what the strip shows. It never moves the
window or affects a calculation, and it is not saved with your data.

The navigator opens by itself in the **Fit** stage and on the **Nyquist**
plot. Elsewhere, use the toolbar button to show or hide it. The choice is
remembered for each view until you reload the page.
