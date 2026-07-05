# Stage 2 Plan 1 — hands-on feedback triage (2026-07-05)

Tore's first hands-on session with the browser analysis app. Verdict:
"looking mostly good". Feedback below, triaged into **bugs fixed now**,
**UX polish (decided, queued)**, and **Plan-2 design (needs a steer)**.
Tore's answers to the milestone-gate questions are recorded at the end.

---

## A. Bugs fixed this session (committed, verified)

All reproduced in-browser and root-caused before fixing; the sonogram is
now covered by an `@engine` e2e (it had none).

1. **Sonogram showed nothing.** Two bugs: (a) the heat `<canvas>` is a
   *replaced* element, so `width/height:auto` used its intrinsic 38×257
   buffer size (a sliver) not the inset box — sized it explicitly to the
   data rect; (b) PlotSurface's opaque `plot-bg` hid the canvas — added an
   `overlay` prop (transparent bg, no gridlines) for the sono axis layer.
   Commit `68c4ce7`.
2. **Tray line-preview sparklines were flat.** `channelData` was never
   passed Tray→TrayCard. Wired a reactive `channelSeries` accessor so
   previews draw the real decoded time series (live as data loads/cleans).
   Commit `68c4ce7`.
3. **Tray tri-state only fired on the tiny colour chip.** Whole row is now
   a button — chip + preview + label + badge all cycle on→fade→off. `68c4ce7`.
4. **Legend sat under the zoom/nav toolbar.** Default moved NE→NW. `36886a8`.
5. **Legend "picked itself up" on hover.** A stuck `armed` flag (pointerup
   missed off-card before the drag threshold) promoted a later hover-move to
   a drag. Cleared on a no-button move. `36886a8`.

## B. UX polish — DONE (2026-07-05, verified in-browser)

6. **Save Figure on every view.** ✅ Moved to the **top bar** between Load Data
   and Save Dataset (disabled until data loads); opens the Export stage from
   any view. The Export card's execute button is renamed **Export** so there
   aren't two "Save Figure" buttons at once. Removed the Time card's copy.
7. **Context bar never scrolls.** ✅ Dropped the fixed 118px height (now a
   min-height floor) and removed the `.ctx-body` inner scroll — the zone grows
   to fit (measured 118→133px for PSD, no scroll).
8. **Action button placement.** ✅ Reflowed via one shared-CSS `order` change:
   **Title → Action Button → settings**, button pinned right of the fixed-width
   heading (consistent across cards).
9. **Setup / Acquire (and Fit) navigable.** ✅ No longer dead-disabled — dimmed
   but clickable; selecting one shows an explanatory placeholder ("Recording
   from a live input arrives in a future update…").

## C. Per-line relabel (bug-ish, deferred into the design pass)

10. **Can't relabel lines.** Only the *set* renames (double-click its name).
    Per-channel labels need new storage in the selection store + `.dvma`
    persistence, and interact with the TF out/in labelling (below) — so this
    is done deliberately in the design pass, not as a quick patch.

## D. Plan-2 design — needs a steer on approach/priority

11. **Per-dataset analysis settings + selector.** Each set may be processed
    differently (its own PSD/TF settings). Add a **"select dataset" dropdown**
    (incl. *All* + each set) that keeps in sync with the left-card selection;
    when *All* is shown and settings differ, display **"–mixed–"**. This is
    the biggest change — it moves analysis settings from global to per-set and
    reshapes the Freq/TF/Sono cards.
12. **PSD/ΔF controls as slider + text box.** For PSD etc., expose ΔF (and the
    resolution family) as a **slider paired with a text box**. Text box accepts
    values outside the slider range (slider clamps to its end-stops); sliders
    ship a sensible default range. Open question Tore raised: **precompute the
    full slider range** for a slick feel? → Recommendation: yes for lab-sized
    data (cheap); gate on data size so huge captures don't stall. Advise
    precompute-when-small, compute-on-release-when-large.
13. **Log/lin toggles for BOTH x and y.** (Tore: yes to both.) Plot-core +
    view-state feature.
14. **TF channel labelling = output/input.** (Tore's pick: the "out/in"
    approach — clearest when different sets have different channel
    arrangements.) This also fixes the confirmed multi-channel TF bug (E1:
    `tf_data` drops the input channel, so lines currently mislabel/drop on
    >2-channel sets). Label each TF line `out/in` (e.g. `ch1/ch0`); the input
    channel shows no TF line. Alt to keep in reserve: label by output channel
    with the input named in a legend header (`Input: <ch>`).
    **DONE (Task R4, 2026-07-05).** `chIn`/`nChannels` carried onto the tf
    slice; `lib/plot/tfChannels.ts` remaps each visible source channel to
    its output column (input → no line) and labels `ch_out/ch_in`; the same
    transform drives the legend (via a `Legend` `entriesOverride`) so plot
    and legend agree. Coherence overlay uses the same remap. New 3-channel
    fixture (`webui/tests/fixtures/impulse3ch.dvma`) + model/tfChannels unit
    suites + an `@engine` e2e; the channel-label part is factored so R5's
    custom labels slot in. Verified in-browser (2 out/in lines, input absent).
15. **Oscilloscope as a "Live" tab.** A dedicated **Live** tab across the top
    (between Acquire and Time) in ADDITION to a small window bottom-left — two
    ways to reach the scope. Depends on the acquisition chunk (Web Audio /
    soundcard), which is a Plan-2 milestone in its own right.
16. **Figures tab / export preview (future).** Tore floated a **Figures** tab
    before Export for controlling exported-figure appearance (and a preview).
    Parks the figure-export font-fidelity note (A12) here.

## E. Tore's answers to the milestone-gate questions

- **TF labelling:** go with **out/in** first (§14); output-only+header as alt.
- **Axis scaling:** want **log/lin toggles for x AND y** (§13).
- **Figure fonts:** note it for now; revisit via a **Figures tab / export
  preview** later (§16). Deploy coupling: fine as-is.
