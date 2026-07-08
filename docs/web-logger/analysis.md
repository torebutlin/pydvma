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

## Time

The **Time** stage inspects the raw time series.

- **input channel** — the channel used by Clean Impulse.
- **x-range** — **Full** (fit all data) or **First 0.2 s**.
- **Clean Impulse** — zeroes the pre-impulse noise and windows the tail
  of an impact response (the same operation as
  [`clean_impulse`](../user-guide/analysis.md#impulse-response-cleaning)).

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

!!! note "Nyquist and Bode navigation"
    In **Nyquist** view the card exposes **fmin/fmax** fields linked to
    the shared TF frequency range. A draggable frequency-band *brush*
    over a Nyquist plot, and fully split axis controls for the stacked
    Bode panes, are **in flight** — today Nyquist uses number fields and
    Bode shares the frequency axis.

## Sonogram

The **Sonogram** stage shows how frequency content evolves over time
(a short-time Fourier transform).

- **dataset** and **channel** selectors.
- **resolution — {nFFT} pt** — a slider (64 to 4096-point STFT window)
  plus an exact nFFT box. A longer window gives finer frequency
  resolution and coarser time resolution, and vice versa.
- **dynamic range** — the dB span of the colour map (30–120 dB).
- **Fit damping** — estimates modal damping from the log-decrement of the
  sonogram bands, listing `fn (Hz)` and `Qn` per detected mode (or "no
  decaying modes detected"). This is the browser front-end to
  [`calculate_damping_from_sono`](../user-guide/modal-analysis.md#damping-from-free-decay-sonogram-method).
- **Calc Sonogram** computes the heat-map.

!!! note "Method: STFT today"
    The sonogram is currently STFT-only (a power-of-two window). A
    **continuous-wavelet (CWT)** method — usable by the damping fit too —
    is **on the roadmap**, not yet shipped.

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
  set is highlighted.
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
dock it via the toolbar.

### The zoom toolbar

- **Box zoom** / **Pan** modes; **↶ Undo** / **↷ Redo** step through the
  view history.
- **Auto X** fits the full data extent; **Auto Y** fits only the lines
  currently visible.
- Axis-scale toggles appear where they apply: **x lin/log** on frequency
  and TF views, **y dB/lin** on magnitude/PSD views.
- The expander opens a popover with **manual axis limits** (applied live)
  and **legend placement** (a 2×2 corner grid plus an *Outside* option).

Next: [Modal fitting](modal-fitting.md), or
[saving and exporting](export.md).
