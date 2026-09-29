# Modal fitting

The **Fit** stage extracts modal parameters from a transfer function: the
natural frequency `fn`, damping ratio `ζ` and quality factor `Q`. It fits
single-degree-of-freedom (SDOF) resonances with pydvma's own modal
fitter, so the results match the Python
[`modal_fit_*` functions](../user-guide/modal-analysis.md#sdof-modal-fitting).

## Getting to the Fit stage

Fit works on a transfer function, so it stays disabled until one exists.
Compute a TF on the [TF stage](analysis.md#tf-transfer-functions) with
**Calc TF**, and Fit unlocks.

Fit reuses the TF plot. Whatever plot type you chose on the TF stage
carries over, and the Fit card has its own **view** selector to change it:
**Mag (dB)**, **Phase**, **Bode**, **Real**, **Imag** or **Nyquist**. The
card's **TF type** selector, **Acceleration**, **Velocity** or
**Displacement**, tells the fit what your transfer function measures. It
sets the `(iω)` power in the model, like the `measurement_type` argument
of the Python fitter.

## Choosing what to fit

### All sets or one set

When more than one set has a transfer function, the Fit card shows a
**sets** selector.

- **All sets (shared poles)** is the default. It makes one joint fit
  across every set's transfer functions. Each mode gets a single natural
  frequency and damping ratio, with separate amplitudes for each set and
  channel. This is the usual hammer-test workflow: many measurements of
  one structure share the same poles, and the joint fit uses all the data.
- Choosing **a named set** fits that set alone.

With one transfer-function set the selector is hidden. Note that here
**All sets** means "jointly", whereas on the analysis cards it means "each
set on its own".

### Choosing which lines

Within the chosen sets, a fit uses the lines you have left showing. Hide
a line in the [legend or tray](working-with-plots.md) to exclude it, or
solo one line to fit it alone. The Fit card says what the next fit will
use: `all N lines`, or `2 of 3 lines (visible only)`. If every line is
hidden, **Fit** refuses with a message.

This matters for a file that holds several unrelated measurements, for
example the admittances of three different instruments. A joint fit across
all of them would be physically wrong, so show only the lines that share
poles.

The fit's dashed reconstruction lines cover exactly the lines that were
fitted, with matching colours and labels.

Choosing a different set, or a different selection of lines, starts a
fresh model at the next **Fit**. **Reject**, **Refine** and the per-mode
actions always work on the existing model and keep the sets and lines it
was fitted on, whatever you show or hide afterwards.

## Fitting modes

Fitting works on the frequency window you are showing. The
[frequency navigator](working-with-plots.md#frequency-navigator) opens
automatically on this stage, so the quickest loop is:

1. Put the window on a peak: drag the navigator's band, or press **›** to
   jump to the next detected peak.
2. Press **Fit 1**.
3. Press **›** again, and repeat.

Each fitted mode is marked with a small triangle on the navigator strip,
so the unmarked peaks are the ones still to fit. You can also zoom the
plot itself; the plot and the navigator share one window.

- **Fit 1**, **Fit 2** and **Fit 3** fit that many modes in the window.
  **Fit 2** and **Fit 3** split the window at detected peaks and fit each
  part.
- **Reject** deletes the fitted modes whose `fn` lies inside the window.
  Zoom to a bad mode, then press it.
- **Refine** re-fits all the modes together for a better joint solution.
  It needs at least two fitted modes. It adjusts only each mode's
  frequency and damping; at every step it re-solves the amplitudes, phases
  and residual terms by least squares, which keeps overlapping modes
  well-behaved. If the result is no better it reverts automatically, so
  Refine never makes a fit worse. If it improves the fit but moves a mode
  by more than 10 % (and more than 2 Hz), a warning names the mode and
  offers **Undo**, so inspect the fit lines before trusting it.
- **↶ Undo** reverses the last fit, reject or refine (one level).

Each mode is fitted with a frequency, a damping ratio, and an amplitude
and modal phase for each channel. For a correctly chosen **TF type** the
phase sits near 0° or 180°. If a mode's phase is more than 30° from
either, its chip shows **⚠** and a warning suggests checking **TF
type**. Fitting a velocity admittance as **Acceleration** is the usual
cause.

### Fit lines: local or global

The fit appears as a **Modal fit** card in the tray, with dashed lines
over the measured transfer function: one card per fitted set, and a line
for each fitted channel. Show, fade or hide them from the legend or tray
like any other set. The **fit lines** switch chooses what they show.

- **global** (the default) is the whole model, drawn over each set's full
  frequency axis. With the poles fixed, pydvma re-solves every mode's
  amplitude and phase for each channel against the measured data, and adds
  a pair of residual terms per channel for modes above and below the
  band. This removes the double counting of neighbouring modes that a
  single local fit absorbs into its phase.
- **local** shows only the modes you have just fitted, over the fit
  window. It is transient feedback: any other recompute (Refine, mute, a
  reloaded fit) clears it until your next **Fit**.

The legend names say which you are looking at: *Modal fit local (set)* or
*Modal fit global (set)*. To clear the whole fit, delete the **Modal fit**
card in the tray (**×**); a message offers **Undo**.

## The mode chip

A floating chip over the plot lists every fitted mode:

```text
mode 1   fn = 187.4 Hz · ζ = 0.0032 · Q = 156
```

`Q = 1/(2ζ)`, and shows ∞ if the fit returns non-positive damping. Each
row has a **mute** toggle (🔊/🔇), which keeps the mode in the model but
leaves it out of the global reconstruction so you can see what it
contributes, and a **×** to delete the mode. **↶ Undo** appears in the
chip after a mute or delete.

Drag the chip by its header to move it out of the way, or minimise it
with **▾** (double-clicking the header does the same). A minimised chip
still shows a one-line `fit · N modes` summary. Its position and state are
kept until you reload the page.

## Calibration and units

The fit uses the calibrated transfer function, so the modal constants
come back in engineering units, and the fit lines sit at the same level as
the measured curve. Frequencies, damping ratios and Q don't depend on
calibration.

If you change a set's calibration after fitting, a message says that the
fit's constants are still in the previous units. Re-fit to update them.
pydvma does not re-fit for you, because that would discard any modes you
had rejected or refined by hand. See
[what calibration changes](calibration.md#what-calibration-changes).

## Damping from free decay

You can also estimate damping directly from a decaying time signal,
without a transfer function, with **Fit damping** on the
[Sonogram stage](analysis.md#sonogram). Use the Fit stage when you have a
good transfer function, and the sonogram fit for a ring-down.

## Saving a fit and reading it in Python

The fitted model is saved in the [`.dvma` file](dvma-format.md) with the
rest of your data, so **Save Dataset** keeps it (see
[Saving and exporting](export.md)). To read the modes in Python:

```python
import pydvma as dvma

data = dvma.load_data(filename='session.dvma')
modes = data.modal_data_list[0]
modes.fn     # natural frequencies, Hz
modes.zn     # damping ratios
modes.an     # modal-constant amplitudes, one column per channel
modes.pn     # modal-constant phases, radians
```

!!! note "Beyond SDOF"
    Mode-shape extraction, MAC and operating-deflection-shape plots are
    not built into the fitter yet, in either the app or Python. See the
    [Python modal-analysis guide](../user-guide/modal-analysis.md#beyond-sdof-not-yet-built-in).
