# Analysis views

Once you have data, recorded or loaded from a file, the web logger has
four analysis stages: **Time**, **Frequency**, **TF** and **Sonogram**.
Each has a small control card above a shared, interactive plot. The
plot's tray, legend, zoom toolbar and frequency navigator are described in
[Working with plots](working-with-plots.md).

The calculations are pydvma's own analysis code, so the results match the
Python `calculate_*` functions. They run in the browser, or in Python on
your machine when the app is
[served locally](running-locally.md#where-the-analysis-runs).

Most cards start with a **dataset** selector: **All sets** or a single
set. When **All sets** is chosen and the sets disagree on a setting, the
control shows `–mixed–`; the first change you make applies to every set.

While a calculation runs, a **computing…** chip appears in the header.
The first calculation of a session may show **starting engine…** while
the analysis engine loads, which happens once.

!!! tip "A typical impact test"
    1. On **Time**, check the record. If **Clean Impulse** is offered,
       press it.
    2. On **TF**, set **in** to the force channel, keep **avg** on
       *within set*, and press **Calc TF**. Check the coherence.
    3. On **Fit**, place the frequency window on a peak and press
       **Fit 1**. See [Modal fitting](modal-fitting.md).

## Time

The **Time** stage shows the recorded time series.

- **input channel**: the channel that **Clean Impulse** checks and
  cleans.
- **x-range**: **Full** fits all the data; **First 0.2 s** shows the
  start of the record.
- **Clean Impulse** keeps the input (force) channel up to just after
  the hammer pulse and fades it to zero from there, so noise or a second
  hit on that channel doesn't reach the transfer function. The response
  channels are not changed. The button appears only when the input
  channel looks like an impulse, meaning at most 25 % of its energy is in
  the second half of the record.
  Otherwise a note says why it is hidden. It is a toggle (**Clean
  Impulse: on** when applied): the raw recording is kept, so pressing it
  again restores it. Any FFT, TF or sonogram you have already computed
  recomputes to match the copy that is showing. **Save Dataset** writes
  the copy that is showing.
- **Resample** changes the highlighted set's sample rate. Choose another
  set to **match** (the list shows each set's rate) or type a custom rate
  in Hz, then press **Resample**. Going down uses the same anti-alias
  filter as the logger's
  [capture-rate conversion](acquisition.md#capture-rate-and-delivered-rate):
  96 dB stopband at the new Nyquist frequency, zero phase. Going up uses
  band-limited interpolation, which adds no content above the original
  band. Results you have computed recompute at the new rate, and the
  message that follows offers **Undo**.

## Frequency

The **Frequency** stage computes spectra.

- **quantity**: **FFT**, **Power**, **PSD** or **CSD**.
- **window**: **hann** (the default), **hamming**, **flattop** or
  **none**.
- **averaging**: shown for **Power**, **PSD** and **CSD** (one FFT is not
  averaged). This is the [resolution control](#resolution-and-averaging).
- **CSD pair**: for **CSD**, choose channels **X** and **Y**. A set needs
  at least two channels. Changing the pair redraws without recomputing.
- **Calc FFT**, **Calc power**, **Calc PSD** or **Calc CSD** computes the
  result. Once a result exists it recomputes as you change settings.

!!! info "Power or PSD: which to read"
    **Power** and **PSD** come from one calculation, shown two ways.

    **Power** is the power **spectrum**. Each bin holds the mean-square
    amplitude in that bin, in `unit²`, so the axis reads for example
    `Power spectrum ((m/s²)²)`. Read a discrete tone here: a sine of
    amplitude $A$ peaks at

    $$
    \frac{A^{2}}{2}
    $$

    whatever the resolution. Broadband noise does not read correctly
    here, because its level grows with Δf: each bin collects a slice of
    the band.

    **PSD** is the power spectral **density**, in `unit²/Hz`. It is the
    power spectrum divided by the analysis window's effective noise
    bandwidth

    $$
    \mathrm{ENBW} = f_s\,\frac{\sum_k w_k^{2}}{\left(\sum_k w_k\right)^{2}}
    \quad\text{[Hz]},
    \qquad
    S_{xx}(f) = \frac{P_{xx}(f)}{\mathrm{ENBW}}.
    $$

    Read a noise floor here: it does not move when you change the
    resolution. A discrete tone has no meaningful density, because its
    apparent level depends on the window.

    The Live stage's PSD is a separate density, computed from the live
    input in its own units and not calibrated (see
    [Live monitoring](live-monitoring.md)).

    **CSD** plots the cross-spectrum magnitude `|S_xy|` of the chosen
    pair, using the convention `S_xy = E[X*·Y]`. It carries
    `unit_i · unit_j`, so calibration is applied to it. If no auto-power
    is available the plot falls back to the coherence, which is
    dimensionless and never calibrated.

## TF: transfer functions

The **TF** stage estimates frequency response functions.

- **in**: the input (reference) channel. Each other channel becomes an
  `out/in` line: output divided by input. The estimator is fixed; there
  is no H1/H2 choice.
- **window**: **none**, **hann** (the default) or **hamming**.
- **avg**: **none**, **within set** (the default: average frames of one
  recording) or **across sets** (average several recordings).
- **averaging — live**: the [resolution control](#resolution-and-averaging),
  active when **avg** is *within set*.
- **coherence**: overlays the coherence function (on by default).
- **plot type**: **Mag (dB)**, **Phase**, **Bode** (magnitude over
  phase), **Real**, **Imag** or **Nyquist**.
- **Calc TF** computes the result. Once a TF exists it re-estimates as
  you change settings.

**across sets** averages every set that has time data. The input
channel, window and sample rate come from the set that has this option
chosen, and the result appears on the first set that qualifies. Sets with
one channel, or a different sample rate, are left out, and a note names
them.

Coherence near 1 means a clean, linear, low-noise response. Dips point to
noise, nonlinearity or a poor reference, as in the
[Python guide](../user-guide/analysis.md#coherence-function). Coherence
needs averaging: with **avg** set to **none** it is exactly 1 and tells
you nothing. It also cannot tell noise from nonlinearity. To separate the
two, and to get both as numbers, run a
[best-linear-approximation measurement](nonlin.md) on the **Nonlin**
stage.

### Scaling: x(iω) and Best Match

The **scaling** group on the TF card holds two tools.

- **x(iω)^**, with a power from −2 to +2, multiplies the displayed
  spectrum by `(iω)^p`. `+1` turns displacement into velocity and
  velocity into acceleration; `−1` integrates. The axis unit follows
  (`m`, `m/s`, `m/s²`).

    This changes only what is plotted. It is applied per set, never
    alters the stored arrays, and is saved with the set in the `.dvma`
    file. It applies to the **FFT** view and to every TF plot type, not
    to **Power**, **PSD** or **CSD**. It does not feed the
    [modal fit](modal-fitting.md), which uses its own **TF type**.

- **Best match** rescales every TF so that the sets best overlay one
  reference channel over the frequency window you are showing. Choose
  the channel in **ref ch** (a channel of the highlighted set), then
  press **Best match**. It uses every channel of every set, whether or
  not the lines are showing. A message reports the factors it applied.

    The factors are stored as each channel's calibration, so **Best
    match** replaces any calibration those channels had, and leaves their
    units as they were. It therefore asks before it runs, naming the
    measurements that would lose a calibration, and the message that
    follows offers **Undo**. See
    [Best match replaces the calibration](calibration.md#best-match-replaces-the-calibration).

!!! note "Nyquist and Bode plots"
    On a **Nyquist** plot the card shows **fmin** and **fmax** boxes for
    the shared frequency window, and the
    [frequency navigator](working-with-plots.md#frequency-navigator)
    opens automatically. The two panes of a **Bode** plot share a
    frequency axis and each has its own y control.

## Sonogram

The **Sonogram** stage shows how frequency content changes over time.
The **method** switch chooses **STFT** (the default) or **CWT**.

- **dataset** and **channel**: unlike the other cards there is no **All
  sets** option. A sonogram is one channel of one set, and the list holds
  only sets with time data. If there are none, **Calc Sonogram** is
  disabled with a note.
- **dynamic range**: the dB span of the colour map, 30 to 120 dB. It is
  unused, and disabled, when the plot's colour is set to linear.
- **Calc Sonogram** computes the heat map. Once a sonogram exists it
  recomputes as you change the channel, method or window settings.

With **STFT**, **resolution** is a slider (64 to 4096 points) plus an
exact **nFFT** box. A longer window gives finer frequency resolution
and coarser time resolution.

With **CWT**, a complex Morlet wavelet transform, the time and frequency
resolution adapt across frequency. It separates close low-frequency modes
better than any single STFT window.

- **wavelet Q (w0)**: a slider from 4 to 64, with a box that accepts up
  to 128. A higher value gives finer frequency resolution and coarser time
  resolution. This is the main resolution control.
- **voices / octave**: how densely the log-spaced frequency grid is
  sampled. The default, **auto**, follows the wavelet Q (at least 0.6 ×
  w0, and never below 16). Choose a number to fix it.
- **freq range — Hz**: optional minimum and maximum. Either box works on
  its own; a blank one stays automatic. The range applies to the damping
  fit as well as the picture.

The CWT is drawn on its own log-spaced grid, so the frequency axis
switches to **log** when you choose it. Change the axis with **y lin /
log** on the plot toolbar; **colour dB / lin** chooses how the heat is
coloured (see [Working with plots](working-with-plots.md#the-zoom-toolbar)).

!!! note "Long records and memory"
    A CWT damping fit holds one complex number per frequency per time
    sample, so a long, full-rate record over the whole band can need more
    memory than the analysis engine allows. The fit then stops with a
    message naming the remedies, such as narrowing **freq range**. The limit is 0.75 GiB
    in the browser and 8 GiB when the app is
    [served locally](running-locally.md#where-the-analysis-runs).

A sonogram or damping calculation that runs longer than about three
seconds shows a progress bar with a **Stop** button. **Stop** ends the
calculation and restarts the analysis engine, which takes a few seconds;
press **Calc Sonogram** again afterwards.

### Fit damping

**Fit damping** opens the damping panel beside the sonogram (below it on
a narrow screen). Choose the method with **peaks | bands**.

- **peaks** finds spectral peaks at the fit's start time, fits each
  peak's free decay, and estimates a damping value **Qn** for each. The
  left chart shows the spectrum at the start time with a **threshold**
  line you can drag (or type; blank is automatic): only peaks above it
  are fitted. The other chart shows the measured decay of each mode with
  its fitted line and an `f Hz, Qn=…` legend. It works with either
  sonogram method, and the CWT can separate modes that the STFT merges.
- **bands** filters the decay into bands (**all (broadband)**,
  **octave**, **1/3 octave** or **1/10 decade**), forms each band's
  Schroeder energy-decay curve, and reports **EDT**, **T20**, **T30**
  and **T60** and the band's **Qn**. A `—` in the table means that band's
  decay range was too small to fit.

Both methods share **start (s)**, a number box (blank lets pydvma infer
it from the pretrigger) and a draggable **start line** on the sonogram.
Together they set where the free decay begins. The fit updates as you
change any control.

On a wide screen the panel's charts stack in a column beside the
sonogram. Click a chart, or its **⤢** button, to expand it over the plot
area, and click again to restore it. Each chart has a **save** button that
writes a PNG styled like the main figures, delivered the same way as
**Save Figure**, and the bands table saves as CSV.

## Resolution and averaging

The **Power**, **PSD** and **CSD** cards, and the **TF** card with
*within set* averaging, share one resolution control. Its four numbers
are linked: change one and the others follow. There is also a slider.

- **N frames**: the number of averaging frames, overlapped by 50 %.
- **frame s**: the length of one frame in seconds.
- **nFFT**: the samples per FFT.
- **Δf (Hz)**: the frequency resolution.

They are related by

```text
frame_length = duration / (N_frames * 0.5 + 0.5)
nFFT         = round(frame_length * fs)
df           = fs / nFFT
```

More frames means shorter frames, coarser Δf and a smoother estimate.
Fewer frames means finer Δf and a noisier estimate. This is the usual
Welch trade-off. The slider covers the sensible range for the set's
sample rate and duration, and the boxes accept values beyond it.

## Axis labels and units

Axis labels show the units of what you are plotting. On a calibrated
channel they show the engineering unit, for example `Amplitude (m/s²)`,
`Power spectrum ((m/s²)²)` or `|H| ((m/s²)/N)`. Power quantities carry
the square of the unit, a CSD carries the product of the two channels'
units, and a transfer function carries output over input.

An uncalibrated channel shows the units of the stored samples. If the
capture is genuinely in volts (an NI capture, or a soundcard whose full
scale is known) the labels read `Amplitude (V)`, `V²`, `V²/Hz` and
`V/V`. If it is in fractions of full scale, the label has no unit. See
[What calibration changes](calibration.md#what-calibration-changes).

## From Python

Each stage has a Python equivalent, so you can repeat or script any
calculation. See the [Python analysis guide](../user-guide/analysis.md).

| In the app | In Python |
| ---------- | --------- |
| **Clean Impulse** | [`clean_impulse`](../user-guide/analysis.md#impulse-response-cleaning) |
| **Resample** | `resample_to_fs` in `pydvma.analysis` |
| **FFT** | `calculate_fft` |
| **Power**, **PSD**, **CSD** | [`calculate_cross_spectrum_matrix`](../user-guide/analysis.md#cross-spectrum-analysis), or `calculate_cross_spectra_averaged` for the averaged result. The auto-power is `Pxy[i, i]`, and dividing it by `enbw_hz` gives the PSD |
| **TF** | `calculate_tf`, or `calculate_tf_averaged` for **across sets** |
| **x(iω)^** | `multiply_by_power_of_iw`, which changes the data in place |
| **Best match** | `best_match` |
| **Sonogram** | `calculate_sonogram` (STFT), `calculate_cwt` (CWT) |
| **Fit damping**, **peaks** and **bands** | [`calculate_damping_from_sono`](../user-guide/modal-analysis.md#damping-from-free-decay-sonogram-method) and `calculate_damping_from_cwt`; `calculate_damping_by_band` |

Next: [Noise and nonlinearity separation](nonlin.md),
[Modal fitting](modal-fitting.md), or [saving and exporting](export.md).
