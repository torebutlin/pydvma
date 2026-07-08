# Round-5 hands-on feedback (2026-07-07, late)

Tore's hands-on on the round-4 surface (Mac, single-channel so far;
PC/multi-channel not yet re-checked). Real repro data attached to the
session (DO NOT commit — teaching/research data; build synthetic
fixtures instead):

- `~/Library/CloudStorage/OneDrive-UniversityofCambridge/Work Teaching - onedrive/4C6/LAB RESULTS/grid_data.npy`
- `~/Library/CloudStorage/OneDrive-UniversityofCambridge/Shared - current/Shared 2024 - MEng - TB VM - data/Jim Woodhouse/ruler_grid_acc_3.mat`

## Bugs

1. **Sono still broken**: Calc Sonogram silently fails (no banner);
   dragging the nFFT slider then surfaces `array is too big` from
   INSIDE scipy: `calculate_sonogram → scipy.signal.spectrogram →
   _fft_helper → sliding_window_view` — the same 32-bit WASM
   nominal-size limit we fixed in pydvma's own cross-spectrum code,
   but this instance lives in SCIPY's helper, so the pydvma-side fix
   must re-segment in calculate_sonogram itself (byte-identical
   against scipy, like the CSD fix) + glue guard for stale wheels.
   ALSO fix the silent first-press (error must surface on Calc, not
   only on slider drag).
2. **Legacy `.npy` load fails** (grid_data.npy): `legacy_to_dvma →
   container.save → AttributeError: 'DataSet' object has no attribute
   'modal_data_list'` — old pickles predate newer list attributes;
   the legacy path must normalise missing lists (compat contract:
   ≤1.4.0 files load forever). Audit for ALL potentially-missing
   attrs, not just this one.
3. **Multi-channel .mat (ruler_grid_acc_3.mat, 11-point TF)**: loads
   as an orphan TfData set but the 11 lines "seem counted as one";
   Solo doesn't behave; the ‹ › single-line increment arrows don't
   either. (Tray shows CH 0..10 + 11 colour chips + '0 s' badge.)

## Axis navigation — special plot contexts (design question answered)

4. **Nyquist**: x/y controls must mean REAL/IMAG there (currently x
   acts like freq); Auto X/Y misbehaves. Design (Tore's idea, adopt):
   a narrow magnitude-vs-frequency strip above the Nyquist plot with
   a draggable highlighted band selecting the frequency range shown
   beneath (drives the same shared/committed freq range, so Fit
   windows work from the Nyquist view too).
5. **Bode**: phase pane's y-axis + Auto Y broken — the single-axis
   toolbar doesn't map to two stacked panes. Direction: x controls
   stay shared (frequency); y controls target the MAGNITUDE pane;
   the phase pane gets its own compact y control (auto | ±180 lock).
6. **Coherence overlay** gets no axis control — give the right axis a
   minimal control (auto | 0–1) in the expanded panel.

## Features / adjustments

7. **CSD**: needs a pair selector (two channel dropdowns) + state the
   convention (E[X*Y] vs E[XY*]) in the UI.
8. **Osc custom view time**: max too low — allow longer windows.
9. **Fit stage**: expose the same view-type options as TF
   (mag/phase/Bode/Nyquist/real/imag) while fitting.
10. **Browser parity** (decision): make the browser (Web Audio) mode
    as full-functioning as sensible — output stimulus + pretrigger in
    the browser, so Pages doesn't feel like a 'lite' version.
11. **Dark mode**: green light — start (sequenced after the axis-nav
    work to avoid style-file collisions).

## Notes

- Solo/‹›/multi-line issues only tested on Mac; PC multi-channel
  recheck pending.
- Liked: Local/Global fit views, Refine, the new axis nav overall,
  the mode chip with × deletes.
- Queued design idea remains: fit-as-tray-card (recon lines with
  normal per-line controls); modal-data restore from .dvma could ride
  that.
