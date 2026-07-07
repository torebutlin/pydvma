# Round-3 hands-on feedback (2026-07-07)

Tore's hands-on with the round-2 implementation (mini-oscilloscope +
Live scope + analysis fixes, commits `888f710..dc47c85`). Two bugs,
three enhancements, three design sign-offs.

## Bugs

1. **PSD compute crashed** (Frequency stage, PSD, "All sets"): after
   recording a NEW single-channel set (44.1 kHz, 2 s) alongside the
   3-channel fixture (fs 2000), Calc PSD raised through the engine:
   `glue.py:76 calc_psd → pydvma analysis.calculate_cross_spectrum_matrix
   → np sliding_window_view → as_strided → ValueError: array is too big;
   arr_size * arr.dtype.itemsize is larger than the maximum possible
   size.` Card showed resolution N=23, frame 0.17 s, nFFT 333,
   Δf 6.01 Hz — note Δf/nFFT/frame are consistent with fs 2000 (the
   FIXTURE's fs), while the recorded set is 44.1 kHz, and the recorded
   set's PSD did render. Suspect the resolution/per-set settings path
   pushes one set's nFFT/N-frames onto a set with a different fs.
   Repro: `?fixture=3ch`, record (or synthesize) a 1-ch 44.1 kHz set,
   target All sets, Calc PSD.

2. **A failed TF poisoned the Sonogram**: after the (expected,
   graceful) TF no-output-channel message on the 1-ch set, the
   Sonogram card displayed the TF error in its own banner and sono
   appeared not to work (empty axes). Errors must be scoped per
   compute kind: each card shows only its own kind's error, a new calc
   clears only its own kind, and one kind's failure never blocks
   another kind from computing.

## Enhancements

3. **Tray: whole-card tri-state by clicking the card title** — click
   cycles the whole set's lines on → fade → off (group selection);
   double-click still renames.
4. **Sliders should live-update during drag**, not only on release
   (resolution slider, sono nFFT — anywhere a slider drives a live
   recompute).
5. **More sophisticated expanded oscilloscope**: view-time as a
   dropdown of common values PLUS typable custom entry; frequency-axis
   controls; the FFT pane should offer a PSD mode with some averaging
   choices.
6. **Setup full mode should carry the FULL range of options** — grows
   in relevance when NI-DAQ acquisition is implemented (structure it
   so nidaq settings can slot in).

## Design sign-offs (keep as-is)

- Calc-button-first gating for live recompute: "fine actually".
- Mini oscilloscope without FFT: fine.
- Audio processing filters (echo/noise/AGC) defaulting OFF: agreed.
