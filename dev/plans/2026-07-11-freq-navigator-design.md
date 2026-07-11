# Frequency navigator — design

**Date:** 2026-07-11 · **Status:** awaiting Tore's review · **Scope:** webui only (no engine changes, no wheel rebuild)

## Motivation

The modal-fitting workflow is currently: box-zoom onto a peak → Fit 1 →
double-click home → box-zoom the next peak → … Tore (round-10 follow-up
discussion) asked for a Nyquist-brush-style "frequency navigator" to skim
along frequency instead, generalised to all frequency displays — with the
observation that one bar is awkward when the captured bandwidth greatly
exceeds the bandwidth of interest (fs chosen high, modes at low frequency):
the working region becomes a tiny, fiddly fraction of the strip.

Agreed direction (this conversation): **Approach B** — a single navigator
bar plus a *progressive* second level (a thin context ribbon that only
appears once a "scope" is set), rather than a permanent two-bar cascade.
The scope is **purely navigational**. Peak-stepping keeps the current
window width. The sono view is parked (its frequency is the y-axis).

## Concepts

Two nested frequency intervals, named consistently throughout code and docs:

- **Window** — the committed shared frequency range (`range.x` of the tf or
  frequency slice; `sharedFreqRange` is `tf.range.x ?? frequency.range.x`).
  This is what the main plot displays and what Calc/Fit read. It is exactly
  what the Nyquist brush's band is today. Window changes are undoable
  (existing history/transient machinery, one entry per gesture).
- **Scope** — the bandwidth of interest: what the navigator strip spans.
  Default `null` = the full data extent, in which case the UI is identical
  to today's single bar. Purely navigational: setting/moving the scope never
  changes the window, the main plot, or any analysis input, and is therefore
  **not** recorded in undo history. It **is** serialized with view state.

## Component: `FreqNavigator`

`NyquistBrush.svelte` is generalised into
`webui/src/components/FreqNavigator.svelte` (NyquistBrush is deleted; the
Nyquist view mounts the new component). Everything the brush does today is
kept unchanged: decimated magnitude strip, drag-body translate / drag-edge
resize / drag-empty create, numeric min–max window fields, log/lin x
following the view's `xScale`, and live preview through the existing
transient-gesture protocol (`beginTransient` / `setRangeLive` /
`commitTransient` / `cancelTransient` — whole drag = one undo step).

New on top of the brush:

### 1. Scope + context ribbon (progressive disclosure)

- The strip's x-domain is the scope (falling back to the full data extent).
- A **⤢ "scope to window"** button in the strip head sets scope := current
  window. (Exact scope entry = type exact window values in the existing
  fields, then ⤢.) No separate scope numeric fields in v1.
- When scope ≠ full extent, a thin (~10 px) **context ribbon** appears above
  the strip: the full extent in miniature with the scope highlighted as a
  draggable band (same gesture code as the strip band: body translates,
  edges resize). **Double-click the ribbon clears the scope** (back to full;
  ribbon disappears). When scope is null the ribbon does not render at all —
  zero extra chrome in the common case.
- Moving the scope does **not** alter the window. If the window falls
  (partly) outside the scope, the strip renders the band clipped, with a
  small arrow glyph at the strip edge pointing toward the off-scope window.
  Dragging on empty strip creates a fresh window inside the scope as today.
- Double-click on the **strip** = window → scope (home-within-scope). This
  replaces today's "reset to full extent" — identical behaviour when scope
  is null.
- Scope is clamped to the data extent on render (data append/load can grow
  or shrink the extent); a scope that becomes degenerate is treated as null.

### 2. Peak stepping (the fit-loop killer)

- **‹ ›** buttons in the strip head jump the window to the previous/next
  detected peak, **keeping the current window width**, centred on the peak,
  clamped so the window stays inside the scope (hugs the edge). Each press
  is one plain `setRange` commit → one undo entry.
- Buttons, not keyboard: the ‹ › keys are already taken by the legend/tray
  line-shift (`selection.shiftLines`, round-8/10b).
- Peaks are detected **client-side** on the strip's own decimated composite
  magnitude (max envelope across the visible strip lines, within the
  scope): local maxima with prominence ≥ a small fraction of the strip's
  y-span (implementation constant, ~5%, tuned against real TFs). No engine
  round-trip; `peakutils` stays untouched.
- Stepping targets the nearest peak strictly beyond the current window
  *centre* in the chosen direction; no wraparound — a button disables when
  no further peak exists.
- Degenerate start: if the window spans ≥ 90% of the scope (i.e. "home",
  where keep-width is meaningless), the first step sizes the window to 1/10
  of the scope, centred on the target peak. Thereafter keep-width applies.

### 3. Fitted-mode ticks

- When a modal fit exists, a small tick/triangle marker is drawn on the
  strip at each mode's `fn` (from `modal.modes`); muted modes draw dimmed.
  The strip doubles as a mode map: fitted peaks are visibly marked, so the
  remaining unfitted peaks are where you skim next. Markers are
  display-only (no interaction in v1).

## Placement, collapse, auto-open

- A **navigator toggle button** joins the `ZoomToolbar` (the `.plot-nav`
  strip), shown on the views that support the navigator. The navigator
  itself mounts above the plot area, where the Nyquist brush sits today.
- Per-view persisted state in `ViewSlice`: `navigator: boolean | null`,
  default `null` = **auto**. Auto resolves to *open* when the Fit stage is
  active or the tf plotType is `'nyquist'` (where the strip is the primary
  frequency control, as today), *closed* otherwise. The toolbar toggle sets
  an explicit boolean, which then wins and is serialized. Like the legend
  flags this is a display mode — not in undo history.

## Which views, and wiring

- **frequency** view (fft/psd/csd) and **tf** view in every plotType,
  including Bode (one strip above the stack, driving the shared x across
  both panes) and Nyquist (replacing today's brush mount in `App.svelte`).
- **sono** — parked (frequency is the y-axis there; a vertical variant is a
  possible later item, not designed here).
- Strip data: generalise `nyquistMagModel` (App.svelte ~line 790) into a
  `navModel` for the active view — the existing builders with
  `freqRange: null, range: {x: null, y: null}` for full extent:
  tf → `tfPlotType: 'mag'`, `yScale: 'log'` (exactly today's brush feed);
  frequency → the view's own `freqMode` lines, `yScale` pinned `'log'` for
  shape legibility. The scope only affects how the strip *renders* (its
  px-mapping and decimation domain), not the model build.
- Window writes go through the active view's slice exactly as the brush
  does for `'tf'` today (transient protocol for drags; `setRange` for
  peak-steps and double-click).

## State model changes (`viewstate.ts`)

- `ViewSlice` gains `navigator: boolean | null` (default `null`); handled
  by the existing `fresh()`-merge in `restore()`, so old snapshots load.
- The store gains a top-level **`freqScope: [number, number] | null`**
  (default `null`), shared across the frequency-x views — the scope is a
  property of the measurement, not of the projection, mirroring how
  `sharedFreqRange` already spans tf/frequency. `serialize()` /
  `restore()` carry it; older snapshots without it restore to `null`.
  Setter `setFreqScope(range | null)` — no history push.

## Explicitly out of scope (v1)

- Semantic scope (driving default calc bands, exports, auto-Reject outside
  the scope) — deliberate later step if lab use demands it.
- Sono view (vertical navigator).
- Keyboard shortcuts for peak-step (key collision with line-shift).
- Interactive mode ticks (click-to-select a mode, drag-to-retune).
- Navigator in Save Figure exports — it is chrome, like the toolbar; the
  export path is untouched.

## Testing

- **vitest:** scope↔px mapping under lin/log and under a set scope;
  clamping of scope to a changed data extent; peak-detection helper on a
  synthetic multi-peak spectrum (finds the peaks, respects prominence);
  peak-step targeting (keep-width, centre rule, edge clamping, disabled at
  ends, the ≥90%-width first-step rule); `freqScope` + `navigator`
  serialize/restore round-trip incl. legacy snapshots; auto-open
  resolution (fit stage / nyquist / explicit override).
- **Playwright (from `webui/`):** toggle shows/hides the navigator on
  frequency and tf views; dragging the band live-rewindows the main plot
  and lands exactly one undo entry; ⤢ scopes the strip and the ribbon
  appears; ribbon double-click clears it; ‹ › moves the window preserving
  width (assert via the toolbar's limit fields); mode ticks appear after a
  fit (reuse the existing fit e2e flow); the Nyquist view's existing brush
  coverage is ported to the new component (testids renamed
  `nyquist-brush*` → `freq-nav*`).
- New calc-free UI throughout — no `engine.boot()` concern (no new calc
  actions).

## Docs

Web Logger docs: a "Frequency navigator" subsection (window vs scope, the
ribbon, peak stepping, mode ticks, the auto-open rule) + update the modal
fit page's workflow description (skim-and-fit replaces zoom-fit-home).
Gate with `python -m mkdocs build --strict`.
