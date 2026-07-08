# Round-6 hands-on feedback (2026-07-08)

Dark mode: fine. Repro data as round 5 (scratchpad copies):
ruler_grid_acc_3.mat (JW, orphan TF) + grid_data.npy (4C6, 12 sets).

## Bugs

1. **Fit on the JW/orphan-TF file crashes**: `TypeError: calc_fit()
   missing 1 required positional argument: 'ch_in'` for Fit 1 AND
   Fit 2. (The 4C6 data fits fine — this is the orphan chIn=null
   path: round-5 R5-B "omits ch_in so the engine default applies",
   but glue's calc_fit has NO default for ch_in.)
2. **Sonogram computes/renders nothing** — silent, plot stays white
   (light AND dark), for STFT and CWT both. Investigate compute vs
   render (incl. the dark-theme heat canvas) and the target
   semantics (an orphan TF set has no time data — sono must require
   a time-bearing set and say so).

## Design / UX

3. **Sono target semantics**: force an explicit SINGLE set + channel
   choice — no "All sets" option for the sonogram.
4. **Zoom box sometimes reads as text-selection** — the whole area
   flashes selection-blue mid-drag (light + dark). Suppress
   user-select/native drag during plot gestures.
5. **Many-channel tray card too compressed** (JW file): the card
   should list channels as normal rows (legend is fine). >4-channel
   sets currently start collapsed — make the rows accessible/obvious
   (better default or clearer expansion).
6. **Nyquist brush v2**: whole-band drag (not just edges — check the
   body-drag hit target), two min/max text boxes INSIDE the strip,
   and LIVE update of the Nyquist plot while dragging (not on
   release).
7. **Multi-set fitting with SHARED POLES** (4C6 data): fitting now
   only fits the target set; Qt's modal_fit_all_channels fits ALL
   sets' TFs simultaneously (one fn/zn, per-channel amplitudes) —
   that's the hammer-test workflow. Add a fit-target choice: **All
   sets (shared poles)** vs a single set. ("Earlier it was fitting
   them all" = the Qt behaviour.)

## Completeness audit vs the old Qt logger (Tore asked)

Remaining functional gaps (everything else has parity or better):
- **Multi-set shared-pole fitting** (item 7 above).
- **Best Match scaling** (`analysis.best_match` — Qt's relative
  set/channel scaling tool). Not built.
- **x(iω) scaling tool** (Qt's acc↔vel↔dsp multiply-by-(iω)^p on
  FFT/TF data). The Fit card has measurement_type for the FIT model
  only; the data-transform tool is not built.
- **Launch-config prefill**: `pydvma-serve --settings` serves the
  JSON at /config but the UI only uses it for bridge DETECTION — it
  does not pre-fill Setup (the Qt logger consumed a MySettings).
Everything else from gui.py maps: logging ± pretrig ± output, osc,
FFT/PSD/CSD/TF/coherence/sono (+CWT new), clean impulse, modal
fit/reject/recon (+Refine/editing/persistence new), calibration,
save/load legacy+dvma, MATLAB/CSV export, message feedback (toasts).
Parked separately: 4C6 labsheets (other repo), Qt teardown (Tore's
word), PWA manifest (plan B3 'if cheap'), mode-shape/MAC helpers
(Phase D, never in the Qt logger).
