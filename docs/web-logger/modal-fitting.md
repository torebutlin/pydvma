# Modal fitting

The **Fit** stage extracts modal parameters — natural frequency `fn`,
damping ratio `ζ`, and quality factor `Q` — from a transfer function by
fitting single-degree-of-freedom (SDOF) resonances. It runs pydvma's own
modal fitter, so the results match the Python
[`modal_fit_*` API](../user-guide/modal-analysis.md#sdof-modal-fitting).

## Getting to the Fit stage

Fit works on a computed transfer function, so it stays disabled until at
least one TF exists. Compute a TF first on the [TF stage](analysis.md#tf-transfer-functions)
(**Calc TF**); the Fit stage then unlocks.

The Fit stage **reuses the TF plot**, so whatever view type you chose on
the TF stage — Mag, Phase, Bode, Nyquist, Real or Imag — carries over
while you fit. The Fit card adds a **TF type** selector
(**Acceleration / Velocity / Displacement**) that sets the `(iω)` power
used by the model, matching the `measurement_type` argument of the
Python fitter.

## Choosing what to fit: all sets jointly, or one set

With more than one TF-bearing set loaded, the Fit card shows a **sets**
dropdown:

- **All sets (shared poles)** — the default with several sets: one
  JOINT fit across every set's transfer functions. Each mode gets a
  single shared natural frequency and damping ratio, with independent
  amplitudes per set and channel — the classic hammer-test workflow,
  where many measurements of one structure share the same poles and the
  joint fit uses all the data at once.
- **a named set** — fit that one set alone.

With a single TF-bearing set the dropdown is hidden and that set is
fitted automatically. Two things to know:

- The choice applies to **Fit 1/2/3** (building the model). **Reject**,
  **Refine** and the per-mode chip actions always operate on the
  *existing* model and keep its exact set composition, so a shared-pole
  model stays coherent through follow-ups.
- Switching the dropdown to a different composition (say shared → one
  set) starts a **fresh model** on the next Fit rather than mixing
  incompatible fits.

(This dropdown is deliberately separate from the analysis cards'
dataset selector, where *All sets* means "each set independently"; here
it means "all sets jointly".)

### Choosing which lines

Within the chosen set(s), a Fit uses **the lines you have left
visible**: hide a line in the legend or tray (click it to *off*) and it
is excluded from the fit; solo one line to fit it alone. The Fit card
shows what the next fit will use — *"all N lines"* when nothing is
hidden, *"2 of 3 lines (visible only)"* for a subset (hover the hint
for the rule) — and if every line is hidden, pressing Fit refuses with
a message rather than silently doing nothing. This matters for
multi-line files that are really several separate measurements — e.g. a
composited JW file holding three instruments' admittances — where a
joint fit across all lines would be physically wrong. Follow-up actions
(Reject, Refine, per-mode edits) keep the *fitted* line composition
regardless of later visibility changes, and changing the visible lines
starts a fresh model on the next Fit rather than mixing incompatible
fits. The fit's dashed reconstruction lines then cover exactly the
fitted lines, with matching colours and labels.

The two selectors compose: in a multi-set fit the poles are shared
across the chosen sets, fitted over the **visible lines of each set**.

## Fitting modes

Fitting works on the **visible frequency window**, so zoom to the region
you care about first, then:

- **Fit 1 / Fit 2 / Fit 3** — fit that many modes in the current window.
  Fit 2 and Fit 3 split the window at detected peaks and fit each.
- **Reject** — delete any fitted modes whose `fn` falls inside the
  visible window (zoom to a bad mode, then Reject it).
- **Refine** — re-fit **all** modes simultaneously for a better joint
  solution. The search runs over the **poles only** (each mode's fn and
  ζ); at every step the amplitudes, phases and global residual terms
  are re-solved linearly against the measured data (variable
  projection). This keeps the search well-conditioned on overlapping
  modes — redundant local residuals used to create flat directions the
  poles could drift along. It **auto-reverts** if the refined fit does
  not actually improve (or fails to converge) — so Refine can never
  make your fit worse numerically. As an extra guard, if a refine
  *does* improve the residual but drags a mode more than 10% from its
  fitted frequency, a warning names the moved mode(s) and offers
  **Undo** — inspect the fit lines before trusting such a result.
- **↶ Undo** — one level of undo, available after any fit, Reject, or
  Refine.

Each mode is fitted with a frequency, damping ratio, amplitude **and a
modal phase** (per channel). For a correctly-typed measurement the
phase should sit near 0° or 180° (a *real* mode); when a fitted mode's
phase strays more than 30° from real, the mode chip marks it **⚠** and
a warning suggests checking the **TF type** — fitting, say, a velocity
admittance as Acceleration is the classic cause. (The original JW
logger printed each fitted phase for the same reason.)

## Fit lines: local or global reconstruction

The fitted model draws as a **"Modal fit" tray card** whose dashed lines
overlay the measured TF — one card per fitted set, with a line per
**fitted** channel (every channel for a full-set fit; just the visible
subset otherwise), controlled from the legend and tray like any other
set. The
**fit lines** toggle on the Fit card picks *which* reconstruction those
lines show:

- **global** (default) — the whole accumulated model, reconstructed over
  each set's full frequency axis. This is not just the sum of the local
  fits: with the poles held fixed, the modal constants (amplitude *and*
  phase, per channel) plus one pair of **global residual terms** per
  channel (a stiffness-like constant for above-band modes and a
  mass-like `1/ω²` term for below-band modes) are **re-solved linearly
  against the measured data**. That removes the double-counting of
  neighbour interactions that each local fit's phase absorbs — locally
  fitted phase partly encodes the Nyquist rotation caused by nearby
  modes, which the joint model explains explicitly.
- **local** — only the mode(s) you just fitted, over the fit window,
  with their own local residual terms. This is transient feedback: any
  other recompute (Refine, mute, a reloaded fit) clears it until your
  next Fit.

The legend names follow the choice — *Modal fit local (set)* vs
*Modal fit global (set)* — so the plot always says which reconstruction
you are looking at. To hide fit lines, use their legend rows or tray
card, just as for measured data.

## The mode chip

A floating **mode chip** over the plot lists every fitted mode:

```text
mode 1   fn = 187.4 Hz · ζ = 0.0032 · Q = 156
```

(`Q = 1/(2ζ)`, shown as ∞ when the fit returns non-positive damping.)
Each row has:

- a **mute** toggle (🔊/🔇) — keep the mode in the model but drop it from
  the global reconstruction, to see its contribution; and
- a **×** delete button.

An **↶ Undo** appears in the chip after a destructive edit, so an
accidental delete or mute is one click to reverse.

If the chip sits over data you want to see, **drag it by its header
strip** to park it anywhere over the plot, or **minimise it** with the
header's ▾ button (double-clicking the header does the same) — the
collapsed chip keeps a one-line *fit · N modes* summary. Its position
and collapsed state stick for the rest of the session.

## Damping from free decay

Modal *damping* can also be estimated directly from a decaying time
signal, without an FRF, via the **Fit damping** button on the
[Sonogram stage](analysis.md#sonogram) — it fits the log-decrement of the
sonogram bands and reports `fn` and `Qn` per mode. Use whichever route
suits your data: an FRF fit (Fit stage) when you have a good transfer
function, or the sonogram decay fit for a ring-down.

## Saving a fit

The fitted model is a `ModalData` object and round-trips through the
[`.dvma` format](dvma-format.md), so **Save Dataset** preserves your
modal fit alongside the underlying data. See
[Saving and exporting](export.md).

!!! note "Beyond SDOF"
    Mode-shape extraction, MAC and ODS plotting are not built into the
    fitter yet (in either interface) — see the
    [Python modal-analysis guide](../user-guide/modal-analysis.md#beyond-sdof-not-yet-built-in).
