# Round-4 hands-on feedback (2026-07-07, evening)

Tore's hands-on with the Waves A–D surface (Fit, calibration, export,
Live PSD mode, bridge). Decisions from the queued list are folded in.

## Bugs

1. **Calc Sonogram shows nothing after logging from the mic** — PSD
   etc. on the same recorded set work fine. Repro: record via mic
   (or the fake-mic path), Calc Sonogram → empty. Investigate;
   suspects: recorded-set channel/target handling in the sono path.
2. **Fit → Reject raises** `Traceback ... File "/engine/glue.py",
   line 410` (pressing Reject right after a fit).
3. **Loading a legacy `.npy` that already contains a TF** loaded the
   time data but NOT the TF. Derived kinds present in a loaded file
   (TF/FFT/sono) must populate their views.

## UX / behaviour changes

4. **View jump on load**: loading a file with only some data kinds
   (e.g. time only) should switch the active view to one that HAS
   data (and e.g. a TF-only file → TF view).
5. **Live osc, view time**: two boxes (dropdown + always-visible
   typebox) is odd → dropdown of defaults plus a 'custom' entry;
   picking 'custom' reveals the typebox.
6. **Live osc, freq axis**: 'full' and 'range' options with
   **min/max** (not just an fmax).
7. **Plot view controls (ZoomToolbar) redesign** — all a bit too
   subtle:
   - ‹ › arrows unclear: if they are view-history undo/redo, use the
     standard curl undo/redo arrows.
   - Drag (pan) and box-zoom glyphs too tiny.
   - The ⋯ expander works but wants something more obvious — an
     expander down-arrow; better: **hovering the toolbar auto-expands
     it** (no hunting).
   - Expanded range entries should apply **live** (no Apply button),
     and be laid out transposed: xmin/xmax stacked on the left,
     ymin/ymax stacked on the right, with visible grouping.
   - Legend-location buttons arranged as a **2×2 grid** matching the
     corners.
   - x/y lin-log groupings need clearer grouping; use explicit
     **lin | log segmented choices**, NOT a toggle button that renames
     itself (ambiguous which state it shows vs sets). Same for dB|lin.
   - **Consistency**: these controls must behave the same as the Live
     viewer's equivalents (one control language app-wide).
8. **'RESOLUTION' group label on PSD/TF reads oddly directly above
   'N'** (N is the opposite of resolution): rename the group
   'Averaging' (or 'number of frames'); label the N box **'N frames'**.
9. **Fit stage UX**:
   - Recon overlays: dashed global is a bit subtle; need visibility /
     line controls — consider the fit/model becoming a **card in the
     left tray** with the same per-line controls as normal sets.
   - Modal summary chip: per-mode delete (bin or ×, consistent with
     app), with undo — or a mute-without-delete option.
   - Accumulation across Fit 1 then Fit 2 works (initial confusion was
     the subtle dashed global line).
10. **Global fit → 'Refine'**: add a Refine action that takes the
    CURRENT set of fitted modes as the starting point and refines all
    simultaneously (modes were fitted in isolation/pairs so neighbours
    interact); **undo if it gets worse**, and self-detect
    non-convergence and revert automatically.
11. **Pretrigger default**: 1000 samples is too high (often exceeds
    chunk size; wasteful) → default **100**, and make it **editable on
    the arm control** itself.
12. **Output UI: more fulsome controls** (beyond switch/type/amp/
    f1/f2 — e.g. duration, output device/channel selection).

## Decisions (from the queued list)

- **CSV**: export ALL available data, sensibly (confirms current
  all-kinds behaviour).
- **Axis labels**: 'Amplitude' is fine when no units provided; use
  stored units where available.
- **Fit-N**: fit-per-window accumulation is right; Global optimise
  arrives as the 'Refine' above (not a from-scratch global fit).
