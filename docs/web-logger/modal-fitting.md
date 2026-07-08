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

## Fitting modes

Fitting works on the **visible frequency window**, so zoom to the region
you care about first, then:

- **Fit 1 / Fit 2 / Fit 3** — fit that many modes in the current window.
  Fit 2 and Fit 3 split the window at detected peaks and fit each.
- **Reject** — delete any fitted modes whose `fn` falls inside the
  visible window (zoom to a bad mode, then Reject it).
- **Refine** — re-fit **all** modes simultaneously for a better joint
  solution. It needs at least two modes, and it **auto-reverts** if the
  refined fit does not actually improve (or fails to converge) — so
  Refine can never make your fit worse.
- **↶ Undo** — one level of undo, available after any fit, Reject, or
  Refine.

## Reconstruction overlays

Two independent overlays let you check the fit against the data:

- **Local** — the reconstruction of the mode(s) you just fitted
  (on by default).
- **Global** — the reconstruction of the whole accumulated model
  (off by default).

Toggle each with the **Local** / **Global** buttons. Turning both on lets
you compare a single mode against the full multi-mode reconstruction.

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
