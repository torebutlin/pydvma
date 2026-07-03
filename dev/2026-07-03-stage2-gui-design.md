# pydvma Stage 2 — web GUI detailed design ("bench" layout)

**Date:** 2026-07-03
**Status:** Draft for review (design session output)
**Parent:** `dev/2026-07-01-web-ui-design.md` (architecture decision record — Stage 2 section)
**Visual reference:** `dev/mockups/round2-bench.html` (normative for layout/feel;
where this spec and the mockup disagree, the spec wins — the refinements from
the final mockup review are recorded here, not re-mocked)
**Process:** mockup rounds + review captured in the session of 2026-07-03;
round-1 options A/B/C remain in `dev/mockups/` as the decision trail.

## 1. Goals and non-goals

Goals (from the decision record's problem statement plus the design session):

- One web app, three data sources (Web Audio, `pydvma serve` bridge, files),
  same UI everywhere. App shell never gates on pyodide boot.
- Feels modern and slick; teaching workflow stays recognisable (Log Data →
  view → Calc FFT → Calc TF → Best Match → save), but the labsheet will be
  rewritten to match the new UI, so geography is free.
- Data navigation is first-class: the sets × channels grid is the central
  object, comparison across sets is the core interaction.
- Zoom/axis navigation is the single most important UX surface — students
  must not get lost.
- The plotting logic must be **debuggable**: explicit view state, no
  stringly-typed mode flags (the Qt GUI's `auto_xy` strings are the
  cautionary tale).
- Settings philosophy: sensible defaults, progressive disclosure,
  capability-driven visibility. "Not LabVIEW."

Non-goals for Stage 2:

- No feature growth beyond the Qt GUI except where this spec says so
  (calibration flow, damping-fit interactivity, figure-export modes are the
  deliberate exceptions). Fitting >3 simultaneous modes, HDF5 storage
  backend, drag-gesture modal parameter editing are out (noted as stretch /
  later).
- The Python CLI is untouched. The Qt GUI stays frozen until parity is
  demonstrated in the lab.

## 2. Layout (wide state)

Four fixed bands, top to bottom (see mockup):

1. **Header** (always visible): product mark; acquisition summary chip
   (device · fs · channels · duration); live per-channel level meters with a
   latching CLIP flag (the "is my stream alive / is anything clipping"
   glance, replacing the Qt title-bar level text); prominent labelled
   **Load Data** and **Save Dataset** buttons; autosave indicator
   ("autosaved 14:32 ✓").
2. **Stage ribbon**: `Setup · Acquire · Time · Frequency · TF · Sonogram ·
   Fit · Export`. Quiet text buttons, active pill, **no numbering and no
   digit-key shortcuts** (typing in inputs must never switch views).
   Selecting a stage swaps the main view *and* the context card — the stage
   is the only tool-switching mechanism.
3. **Context card**: one fixed-height card (module styling) per stage;
   consistent internal grid (title, labelled control groups, primary action
   right-aligned). Never changes height between stages in wide mode.
4. **Main area**: data tray (left, ~300 px) + hero plot (rest). The plot is
   the largest element on screen at all times. The **monitor**
   (oscilloscope) docks at the tray's foot; expandable (§8).

Status/messages: inline status text in the Acquire card during capture
("Logging data for 2.0 seconds…", "Waiting for trigger on channel 0…
[Cancel]", "Trigger detected."); toasts bottom-right elsewhere; every
destructive action (delete set/last/all, replace, scaling) gets an **Undo**
in its toast. OK/Cancel/Undo idiom carries over from Qt.

## 3. Data model and tray

- Objects: **sets** (one per capture or load), each with **channels**. Line
  identity = (set, channel), colour from a fixed palette, label editable
  (double-click; default `set_N · ch_M`, custom names propagate to legend
  and exports — this resolves the old "legend relabelling" TODO item).
- **Tri-state per line: on / fade / off** (fade ≈ 25 % opacity for context).
- **Matrix batch semantics:**
  - set-card *header* click cycles every channel in that set;
  - *channel chip* (header row above the cards, one per channel index)
    cycles that channel index across **all** sets;
  - individual line chip cycles just that line;
  - All / None / Solo, and `‹ ›` steppers that walk the highlight
    set-by-set (pairwise comparison idiom).
  - Channel chip row must scale: it shows the union of channel indices
    across sets, horizontally scrollable past ~8, and operates on all sets
    including collapsed ones.
- A set whose lines are **all off** renders its card with a strike-through
  treatment ("out of stock") and is **omitted from the legend entirely**
  (no crossed-out legend entries; exported figures show only visible data).
- Set cards: timestamp, duration badge, collapse toggle (many-channel sets
  default collapsed), per-channel rows with sparkline thumbnails, `⋯` menu:
  Rename / Delete / **Calibrate…**
- **Calibrate… dialog** (seed of the GUI calibration flow): per-channel
  sensitivity (value + unit: V, m/s², N, Pa, …) writing through to
  `channel_sensitivities` / `channel_cal_factors`; a guided known-input
  calibration flow (measure reference → compute factor → apply) is part of
  Stage 2 scope, reachable from this dialog; Best-Match remains the quick
  relative-scaling tool (§6 TF).

## 4. Acquisition (Setup and Acquire stages)

- **Setup card** is the single settings home: device select (with a
  "suggest settings" affordance that probes the chosen device's
  capabilities and proposes fs/channels), fs, channels, duration,
  and the progressive-disclosure rows below. **Apply** restarts the stream;
  failures surface as a toast + disabled Log button with a reason.
- **Acquire card**: settings summary chip — clicking opens the *same
  settings editor as a popover* (one source of truth, no stage jump);
  **Output** row and **Pretrigger** row as inline on/off toggles that
  expand a second row of controls when on (collapsed = lab default):
  - Output (only rendered when the active device reports output
    capability): type (sweep / white / gaussian), amplitude (V), f1, f2,
    duration, preview sparkline. When on, the Log button wears a small
    **OUT** badge — there is **one** Log Data button, never a separate
    "log with output".
  - Pretrigger (plain on/off, not "arm" language): samples, threshold,
    **input channel** (the channel watched for the trigger).
  - Capability-driven visibility generalises later to IEPE controls
    (NI 9234) served by the bridge's device metadata.
- **Log Data** (solid green, the app's primary action): status sequence in
  the card; on completion the new set lands in the tray *selected*, plot
  switches/stays on Time view showing it. Cancel works during pretrigger
  wait and during capture.

## 5. Views and analysis

Terminology fix from review: anywhere the Qt GUI said "impulse channel",
the new UI says **input channel** (it designates the excitation/reference
channel for TF and impulse-cleaning regardless of excitation type).

- **Time**: Clean Impulse (input channel picker), quick-range chips (Full /
  first-x-s), y in volts (or calibrated units where sensitivities set).
- **Frequency**: sub-modes **FFT | PSD | CSD**. PSD/CSD get the same
  averaging treatment as TF: window select plus the **coupled resolution
  control** — three linked fields (N_fft, N frames, frame length in s) with
  one slider; editing any one updates the others live against the source
  duration. Calc actions live-update on slider drag exactly like the Qt
  N-frames slider (a teaching feature, non-negotiable).
- **TF**: window, averaging (none / within set / across sets), coupled
  resolution control (as above), coherence toggle. **Coherence is drawn per
  line in the same hue, lighter and dashed, right axis 0–1** — the colour
  pairing is how users match coherence to data, so distinction comes from
  weight/dash/alpha, never a different hue. Plot types: Mag (dB) / Phase /
  Bode (stacked mag + phase) / Real / Imag / Nyquist. Scaling group:
  x(iω), x 1/(iω), ref set/chan, Best Match, Undo scaling.
  - **Nyquist**: square aspect always; axes fit the data (not forced to
    centre on 0,0); zoom/box-zoom works with aspect preserved; fmin/fmax
    fields link to the frequency range zoomed in the other TF views.
- **Sonogram** (its own stage): live resolution slider (coupled control),
  dynamic range (dB), set/channel picker. **Damping fit** is interactive:
  a draggable start-time line on the sonogram excludes the initial
  transient from peak-finding; a peak threshold slider; running the fit
  opens the **decay-fit plot** (log-magnitude decay per detected band with
  fitted lines and per-band fn/Qn results — the current Qt "Damping Fit
  Results" popup, kept and made live against the threshold slider).
- **Fit** (modal fitting): view = TF zoomed to working range with fit
  overlays. Fit 1 / Fit 2 / Fit 3 modes over the visible range; Reject;
  **fitted-modes list**: a compact table (fn, ζ, Q per mode) with per-mode
  include/exclude toggle, delete, and numeric editing; **Global optimise**
  (seeded by the individual fits) after peak-by-peak fitting; Summary and
  Reconstruction views. Drag-gesture parameter editing is a stretch goal,
  not Stage 2 scope.

## 6. Plot navigation (the #1 UX surface)

- Toolbar attached to the plot (top-right): box-zoom (rubber band), pan,
  back / forward (history), Auto X, Auto Y, `⋯` popover with manual
  min/max fields. Two-way sync: dragging updates fields, editing fields
  updates the plot.
- Guardrails: zooming cannot leave the data (clamped with elastic
  overshoot); double-click = auto-fit both axes; Auto Y fits *selected*
  lines only (Qt behaviour, kept).
- Axis state is per-view and restored when returning to a view; frequency
  range is shared between TF plot types (incl. Nyquist's fmin/fmax).
- **Legend**: draggable to reposition freely, plus a position control
  (corner presets NE / NW / SE / SW and outside-right) in the plot
  toolbar's `⋯` popover — presets are explicit choices, dragging does not
  snap; toggleable on/off; entries mirror tray tri-state (click to cycle);
  off-sets omitted (§3); custom labels.

## 7. Figures, saving, export

- **Save Dataset** (header + Export card) writes `.dvma`. **Autosave**: on
  by default, after every capture/compute, with a "restore last session"
  offer on next launch — the students-losing-data mitigation. Explicit
  save remains the way to get a file. Where autosave lands depends on the
  working-directory capability below (real file if possible, browser
  storage otherwise).
- **Working directory**: a user-set folder that anchors all file
  operations — load dialogs open there, saves/exports/autosaves default
  there. Shown as a chip in the header (click to set/change).
  Capability-layered:
  - Chromium browsers: File System Access API directory handle, persisted
    across sessions (re-grant prompt on revisit); autosave writes a rolling
    `autosave.dvma` there as a real file.
  - `pydvma serve` mode: the bridge owns the working directory on the lab
    PC's real filesystem — same UI concept, works in any browser.
  - Fallback (Safari/Firefox on the hosted app): browser-storage autosave
    plus standard download/upload; the chip indicates "Downloads" and
    saved files carry a session-name prefix.
- **Load Data** handles all imports: `.dvma` (native JS reader), legacy
  `.npy` pickle (via pyodide), `.mat` JW-logger.
- **Save Figure**: format checkboxes (PNG / PDF — explicit, no silent
  two-for-one) and a **background mode: white (default) / transparent /
  dark** — white for reports, transparent PNG for slides, dark to match
  dark-mode decks. Export renders from the same plot model at export DPI,
  honouring visibility, labels, legend position.
- Export card also: Matlab, CSV.

## 8. Monitor (oscilloscope)

- Docked mini-panel at the tray foot: live trace + per-channel level bars +
  latching clip flag; its own hide/expand controls live **on the panel**.
- Expanded overlay: time trace, live FFT, level bars, keyboard toggles
  <kbd>T</kbd>/<kbd>F</kbd>/<kbd>L</kbd>/<kbd>P</kbd> (panels + pause),
  autoscale-y toggle, and a **stacked-traces toggle** (vertical separation
  per channel, the Qt many-channel idiom) so 10 channels remain readable;
  FFTs overlay; levels become a bar row.
- Displays normalised amplitude (±1 of device full scale) — it is a
  qualitative instrument; quantitative work happens in captured data.
- **Pop-out** to a separate browser window (own "bit of instrumentation",
  usable on a second monitor); the docked mini stays as the affordance to
  bring it back. Monitor runs in parallel with logging off the same stream
  (single stream owner in the source layer — no Qt-style stream contention).

## 9. Adaptive layout

- **Wide** (≥ ~1000 px): as §2.
- **Narrow** (below, or user-toggled): the tray collapses to a ~72 px
  **set rail** — one chip per set (colour stack + aggregate state) that
  still cycles the whole set on click, channel chips compress to dots, and
  a `⋯`/`›` affordance opens the **full tray as a flyover drawer**
  (rail + drawer hybrid — chosen in review). Monitor shrinks to a levels
  strip on the rail. Ribbon keeps **word labels** (Frequency may abbreviate
  to "Freq"; never icon-only). Context card may wrap to two rows.
- Narrow is a first-class mode: it is how students run the app beside the
  labsheet on one screen.

## 10. Theme

- Light (default) and **dark** app themes; design tokens from the mockups.
- Figure export background is independent of app theme (§7) — reports stay
  white-paper by default regardless of how the app is skinned.

## 11. Architecture requirements (binding for the implementation plan)

- **Stack:** Svelte + TypeScript + Vite in `webui/` (per the decision
  record). Static deploy to Pages at `…/pydvma/app/`; also served by
  `pydvma serve` in the lab.
- **Maths:** pydvma core in a pyodide **web worker**; FFT/TF/windowing/
  sonogram/modal fitting are never reimplemented in JS. The UI is fully
  interactive before pyodide finishes booting (analysis actions queue with
  visible "engine loading" state).
- **Data sources** behind one TS interface: `WebAudioSource`,
  `BridgeSource` (websocket to `pydvma serve`), `FileSource`. Capability
  metadata (AO support, IEPE, sample-rate ladder) flows from the source and
  drives conditional UI (§4).
- **Files:** `.dvma` read/write natively in JS (jszip + npy codec);
  legacy pickle via pyodide only.
- **Plot state:** a single explicit view-state store per plot (view, axis
  ranges, per-line visibility tri-state, plot type, legend state), with
  serialisable state and time-travel-friendly updates — this is the
  debuggability requirement made concrete. No mode strings.
- **Rendering:** scope/monitor = canvas (rAF, decimated ring buffer — the
  gate prototype's approach, which held a stable 30 fps; investigate the
  30-vs-60 cap before locking the render loop, per the gate verdict).
  Static analysis plots = the chosen plot layer must support: SVG/canvas
  export at print DPI, coherence twin axis, square-aspect Nyquist, legend
  drag, rubber-band zoom with history. Plotly.js is the candidate; a thin
  custom SVG layer (as prototyped in the mockups) is the fallback if
  Plotly fights the export/aspect requirements. Decide via a one-day spike
  at implementation start.
- **Testing:** Playwright e2e with synthesised audio (getUserMedia mock)
  covering the golden path (log → FFT → TF → fit → save/load round-trip);
  bridge protocol tests against `MockRecorder`; plot-state store unit
  tests; visual regression on the figure exporter (white/transparent/dark).
- **Compatibility:** CLI untouched; `.dvma` format contract from Stage 0.5;
  Qt GUI frozen until the new app passes a real lab dry-run.
- **Deployment modes and interop** (all ship in parallel, indefinitely):
  Python CLI (unchanged, the customisation path); hosted web app (Pages
  `/app/`: analysis + soundcard, zero install); local web app
  (`pydvma serve`: same UI served by the lab PC, adds NI over websocket,
  no internet dependency); JupyterLite (`/lite/`, Stage 1, stays); Qt GUI
  (frozen, deprecated once the web app passes the lab dry-run). One build
  of the app serves both web modes — it probes for a local bridge and
  offers NI devices only when one responds. `.dvma` is the interchange
  format across every mode; the app's Setup card fields map 1:1 to
  `MySettings`, so a lab-configured session is reproducible from the CLI
  and vice versa.

## 12. Deferred / stretch (recorded so they aren't lost)

- Guided known-input calibration wizard beyond the seeded dialog (§3) if
  implementation time is short — the dialog + sensitivities ship regardless.
- Drag-gesture editing of modal parameters; >3-mode simultaneous fits.
- IEPE auto-detect preflight surfaced in Setup (bridge feature).
- Browser-tab-title level indicator (revisit once the header meters have
  been used in anger).
- PWA/offline packaging for the Pages build.

## 13. Review checklist against the session's pain list

Every irritation from the 2026-07-03 review maps to a section above:
zoom UX → §6; legend/labels/off-sets → §3 §6; PSD/CSD + averaging → §5;
coherence distinction → §5; calibration → §3; settings sprawl → §4;
output controls → §4; sono damping robustness/interactivity → §5;
mode-fit editability → §5; Nyquist axes → §5; import/export → §7;
autosave/data loss → §7; scope stacking/clipping → §8; narrow mode → §9;
robustness/debuggability → §11; dark mode / figure backgrounds → §7 §10.
