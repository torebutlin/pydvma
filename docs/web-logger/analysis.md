# Analysis views

Once you have data — recorded, or loaded from a file — the web logger
gives you four analysis stages: **Time**, **Frequency**, **TF** and
**Sonogram**. Each has a small control card and a shared, fully
interactive plot. The maths is pydvma's own analysis core (running in a
pyodide worker in the browser, or in the `pydvma serve` process), so
results match the Python `calculate_*` functions exactly.

Most analysis cards start with a **dataset** selector — **All sets** or a
single set. When *All sets* is selected and the sets disagree on a
setting, the control shows a `–mixed–` state.

While a computation is in flight a small pulsing **computing…** chip
appears in the header (calc buttons also grey out). The very first
calculation of a browser session shows **starting engine…** instead
while the in-browser Python engine boots — that one-off wait is normal.

## Time

The **Time** stage inspects the raw time series.

- **input channel** — the channel used by Clean Impulse.
- **x-range** — **Full** (fit all data) or **First 0.2 s**.
- **Clean Impulse** — zeroes the pre-impulse noise and windows the tail
  of an impact response (the same operation as
  [`clean_impulse`](../user-guide/analysis.md#impulse-response-cleaning)).
  It is a **toggle**: the raw recording is kept, so clicking again
  restores it (and back — the clean is cached, never re-run on its own
  output). Every result you have already computed (FFT / PSD / TF /
  sonogram) recomputes to match whichever copy is applied. Saving writes
  the applied copy; the other copy lives only in the session.
- **Resample** — change the highlighted set's sample rate after the
  fact. Pick another set to **match** (the dropdown lists each set with
  its rate — handy when measurements logged at different rates need a
  common fs) or enter a **custom** rate. Downsampling uses the same
  noise-reducing anti-alias filter as the logging
  [digital low-pass](acquisition.md#digital-low-pass) (96 dB stopband
  at the new Nyquist, zero-phase); upsampling is band-limited (sinc)
  interpolation, which — unlike linear interpolation — invents no
  frequency content above the original band and passes the recorded
  band untouched. Existing results recompute at the new rate; the
  success message offers a one-step **Undo**, and saving writes the
  resampled data.

## Frequency

The **Frequency** stage computes spectra.

- **quantity** — **FFT**, **PSD**, or **CSD**.
- **window** — **hann** (default), **hamming**, **flattop**, or **none**.
- **averaging** — shown for **PSD** and **CSD** only (a single FFT is not
  averaged); this is the resolution control described
  [below](#resolution-and-averaging).
- **Calc FFT / Calc PSD / Calc CSD** computes the result. Once a result
  exists it recomputes live as you change settings.

!!! info "What CSD currently shows"
    The **CSD** quantity currently plots the **coherence** (`|Cxy|` on the
    diagonal) for the set. A full cross-spectrum **pair selector** (pick
    two channels) and an explicit `E[X*Y]` vs `E[XY*]` **convention**
    label are **on the roadmap and not yet shipped** — the card notes
    "cross-power pairs deferred". For arbitrary cross-spectra today, use
    the Python
    [`calculate_cross_spectrum_matrix`](../user-guide/analysis.md#cross-spectrum-analysis).

## TF — transfer functions

The **TF** stage estimates frequency response functions.

- **in** — the input (reference) channel. The transfer function is
  formed as **output / input**: the input channel is dropped and each
  remaining channel becomes an `out/in` line. (This is an automatic
  convention, not a selectable H1/H2 estimator.)
- **window** — hann (default) / hamming / none.
- **avg** — **none**, **within set** (frame-average one recording), or
  **across sets** (ensemble-average several recordings). The
  [resolution control](#resolution-and-averaging) appears when
  *within set* is selected.
- **coherence** — overlay the coherence function (on by default). Its
  right-hand axis gets its own control in the plot toolbar.
- **plot type** — **Mag (dB)**, **Phase**, **Bode** (magnitude over
  phase, stacked), **Real**, **Imag**, or **Nyquist**.
- **Calc TF** computes; it re-estimates live once a TF exists.

Good coherence (near 1) means low noise and a linear, causal response;
dips flag noise, non-linearity, or a poor reference — the same
interpretation as in the [Python guide](../user-guide/analysis.md#coherence-function).

### Scaling: x(iω) and Best Match

The TF card carries a small **scaling** group — the web-logger equivalent
of the old Qt logger's Scaling tool.

- **x(iω)^ p** (`p` in −2 … +2) — differentiate or integrate the
  displayed spectrum by multiplying it by `(iω)^p`: `+1` converts
  displacement → velocity → acceleration, `−1` integrates back. The axis
  unit label follows the derivative ladder (`m` → `m/s` → `m/s²`).

    This is a **non-destructive, per-set display transform** — it changes
    only what is plotted, never the stored arrays, so a set that
    recomputes (or is re-fitted) is unaffected. It differs from Python
    `multiply_by_power_of_iw`, which mutates the `FreqData`/`TfData` in
    place. The power applies to the **FFT** view and every **TF** plot
    type (not PSD or coherence), is saved per set in the `.dvma` file, and
    does **not** feed the modal fit — [modal fitting](modal-fitting.md)
    always reads the raw transfer function with its own measurement type.

- **Best match** — pick a **ref ch** (a channel of the focused set) and
  press **Best match** to rescale every TF so the family best overlays
  that reference channel over the currently visible frequency window (the
  Qt `best_match` maths: an RMS-magnitude ratio with a least-squares
  sign). The factors are written through the ordinary
  [calibration](calibration.md) path — a per-channel `channel_cal_factors`
  multiplier — so they persist in the `.dvma` file, show up (and are
  editable) in the Calibrate dialog afterwards, and are undone by reopening
  Calibrate and resetting the sensitivities. A toast reports the applied
  per-set factors.

    Unlike the [modal fit](modal-fitting.md#choosing-which-lines), Best
    match always uses **all** channels of each set — it is a calibration
    operation, not a fit, so hiding a line in the legend or tray does
    not exclude it.

!!! note "Nyquist and Bode navigation"
    In **Nyquist** view the card exposes **fmin/fmax** fields linked to
    the shared TF frequency range, and the plot carries a draggable
    frequency-band **brush** — drag either end (or slide the whole band)
    to scrub the same shared range live, with one undo step per gesture.
    The stacked **Bode** panes share the frequency axis; each pane has
    its own y-axis control (the phase pane offers ±180° or auto).

## Sonogram

The **Sonogram** stage shows how frequency content evolves over time.
Two methods are available via the **STFT | CWT** switch:

- **STFT** (default) — the classic short-time Fourier transform.
  **resolution — {nFFT} pt** is a slider (64 to 4096-point window)
  plus an exact nFFT box: a longer window gives finer frequency
  resolution and coarser time resolution, and vice versa.
- **CWT** — a continuous wavelet transform (complex Morlet). Instead
  of one fixed window it uses log-spaced frequencies whose time/
  frequency trade-off adapts per band — better at separating close
  low-frequency modes than any single STFT window. Controls:
  **wavelet Q (w0)** — a slider (4–64, the exact box accepts up to
  128) for the wavelet's own bandwidth: higher w0 = more cycles under
  the envelope = finer *frequency* resolution at the cost of coarser
  *time* resolution — this is the true resolution knob;
  **voices/octave** (how densely the log-frequency ladder is sampled) —
  defaults to **auto**, which keeps the density matched to the wavelet
  Q (a high-Q wavelet's narrow bands need a comparably dense grid, so
  auto tracks ≥ 0.6·w0 up the ladder, never below 16); pick an explicit
  number to pin it, or *auto* to resume following; and an optional
  frequency range. The magnitude
  scale matches the STFT image, so the two methods read comparably.
  The heat map is drawn on the wavelet's **native log-spaced grid**, so
  switching the frequency axis to **log** (see below) shows its full
  low-frequency detail.

Common controls:

- **dataset** and **channel** selectors. Unlike the other cards, the
  sonogram has **no *All sets* option** — it is a single-set,
  single-channel view, so you pick exactly one set and one channel. The
  dropdown lists only **time-bearing** sets: a loaded spectrum or
  transfer function on its own has no time signal to transform, so those
  sets are excluded. If nothing time-bearing is loaded, **Calc
  Sonogram** is disabled with a note explaining why.
- **dynamic range** — the dB span of the colour map (30–120 dB). It
  applies to the **dB** colour mode; in **linear** colour mode (below)
  the heat is normalised 0 → peak instead, so this control is disabled.
- **frequency axis** and **colour** live on the plot toolbar, not the
  card. The **y — lin | log** switch draws the frequency axis linearly
  (default) or on decades; **log** stretches the low-frequency detail
  and is the natural pairing with the CWT's log grid. (The x axis stays
  time — a log time axis is not meaningful.) The **colour — dB | lin**
  switch maps the heat by magnitude in dB (default, over the dynamic
  range span) or by linear magnitude (0 → peak). Both choices persist
  per view with the rest of the axis state.
- **Fit damping** — opens the **interactive damping panel** below the
  sonogram, with two methods on a **peaks | bands** toggle:

    - **peaks** — finds spectral peaks at the fit's *start time*, fits
      each band's free decay (damping from the log-magnitude slope,
      frequency from the phase slope), and draws the decay-fit chart:
      measured `Re log(S)` as × markers with the fitted line per mode
      and an `f Hz, Qn=…` legend. The left chart shows the start-slice
      spectrum with a **draggable threshold line** (also a number field;
      blank = automatic) — only peaks above it become candidate modes.
      It works with whichever sonogram method is selected — the CWT
      variant can resolve close modes the STFT merges. Browser front-end
      to
      [`calculate_damping_from_sono`](../user-guide/modal-analysis.md#damping-from-free-decay-sonogram-method)
      and its CWT counterpart `calculate_damping_from_cwt`.
    - **bands** — band-passes the decay into standard bands (**all**
      broadband, **octave**, **1/3 octave** or **1/10 decade**), forms
      each band's Schroeder energy-decay curve, and fits the acoustic
      decay metrics: **EDT**, **T20**, **T30**, **T60** (T30-preferred)
      and the equivalent band-centred **Qn**. The chart overlays each
      band's EDC with its dashed T60 fit line; a `—` in the table means
      that band's decay range was too small to fit (not an error).
      Front-end to `calculate_damping_by_band`.

    Both methods share the **start (s)** control — a number field
    (blank = inferred from the pretrigger) *and* a draggable **start
    line** on the sonogram itself, so you choose where in time the free
    decay begins. Every control re-fits live.

    On wide screens the panel sits in a column to the **right** of the
    sonogram with the charts stacked; click a chart (or its ⤢ button)
    to **expand it to fill the plot area** and click again to pop it
    back. On narrow screens the panel docks below the sonogram. Every
    chart has a **save** button — it exports a PNG styled exactly like
    the main figures, to the same place (working folder or Downloads) —
    and the band-metrics table saves as **CSV**.

- **Calc Sonogram** computes the heat-map.

## Resolution and averaging

The **PSD**, **CSD** and averaged-**TF** cards share one resolution
control. It exposes four *coupled* numbers — change any one and the rest
update — plus a slider:

| Field | Meaning |
| ----- | ------- |
| **N frames** | number of (50 %-overlapped) averaging frames |
| **frame s** | length of one frame, in seconds |
| **nFFT** | samples per FFT |
| **Δf (Hz)** | frequency resolution |

They are tied together by the same relations pydvma uses internally
(50 % overlap):

```text
frame_length = duration / (N_frames * 0.5 + 0.5)
nFFT         = round(frame_length * fs)
df           = fs / nFFT
```

So **more frames -> shorter frames -> coarser Δf but a smoother
(lower-variance) estimate**, and fewer frames -> finer Δf but a noisier
estimate. This is the classic Welch trade-off; pick the balance that
suits your measurement. The slider covers the sensible range for the
set's sample rate and duration; the boxes accept values beyond it.

## Working with the plot

The controls below are shared across every analysis view.

### The dataset tray

The **tray** (left, wide layout) lists every dataset with a colour-coded
channel stack, name, duration and per-channel sparklines.

- **All / None / Solo** show, hide, or isolate lines; **‹ ›** step which
  set is highlighted (or which channel, when only one set is loaded).
- With a **subset of lines** selected (some on, some off), **‹ ›**
  instead shift the *whole selection* one step, wrapping at the ends.
  Two hand-picked lines stay a pair as they walk the channels, and a
  measured channel plus its fit line cycle together — a quick way to
  compare each channel against its fit in turn. Measured sets and fit
  overlays shift independently: a selected line that is a whole
  (single-channel) set steps to the next *set*, and a visible fit line
  rides along rather than being dropped.
- Each set name is a **tri-state** toggle — click cycles the whole set
  **on -> faded -> off**; double-click (or **F2**) renames it.
- Expand a set to toggle individual channels (each channel line is also
  tri-state: on / faded / off).
- The channel-index chips across the top toggle a given channel column
  across *all* sets at once.
- **cal** (on hover) opens the [calibration dialog](calibration.md); **×**
  deletes the set.

### The legend

A draggable **legend** floats over the plot. Clicking a legend row cycles
that line on -> faded -> off (mirroring the tray); switched-off lines stay
listed, struck-through, so you can bring them back. Drag it anywhere, or
dock it via the toolbar. With many lines (more than ten) the legend lays
itself out in two or three balanced columns, and a small corner button
(appears on hover) switches to a **compact mode**: a grid of colour-coded
dots — one row per set, one column per channel — where each dot clicks
exactly like its full row and the full label shows as a tooltip.

### The zoom toolbar

The toolbar sits in a slim strip **above the plot frame** (it never
covers the data area).

- **Box zoom** / **Pan** modes; **↶ Undo** / **↷ Redo** step through the
  view history.
- **Auto X** fits the full data extent; **Auto Y** fits only the lines
  currently visible.
- Axis-scale toggles appear where they apply: **x lin/log** on frequency
  and TF views, **y dB/lin** on magnitude/PSD views, and on the
  **Sonogram** a frequency-axis **y lin/log** plus a heat **colour
  dB/lin** switch (see the Sonogram section).
- The expander opens a popover with **manual axis limits** (applied live)
  and **legend placement** (a 2×2 corner grid plus an *Outside* option).

Next: [Modal fitting](modal-fitting.md), or
[saving and exporting](export.md).
