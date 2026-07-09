# Round 8 — lab-testing feedback (2026-07-09, late evening)

Tore's second feedback batch of the lab-testing day. Four items; all
landed.

## 1. Fit summary "gets in the way" → draggable + minimisable

`FitChip.svelte` grew a slim header strip: `⠿ fit · N modes` plus a
`▾/▸` chevron (MiniMonitor idiom). The header is the drag handle
(pointer-captured, DampingStartLine pattern); double-click also
minimises. Position + collapsed state live in **module-scope** `$state`
so they survive the chip's re-mounts (stage switches, Nyquist/default
layout swaps) for the whole session — deliberately NOT persisted to
`.dvma` or localStorage.

Details that came out of eyeballing it in the real browser:

- **Re-clamp on size change** (`clampToParent`): the drag clamp is
  computed from `offsetWidth/Height` + the known CSS anchor
  (left 64 / bottom 52 — keep in lockstep), not from
  transform-tainted rects, and an `$effect` re-clamps on
  collapse/expand/mode-count changes. Without it, expanding a chip
  parked at the plot's right edge clipped its mute/× buttons past the
  plot edge (seen live; now e2e-relevant behaviour).
- **z-index 6 (above the legend's 5)**: both overlays are draggable,
  but with the chip *below*, parking it under the legend made it
  invisible and ungrabbable (the legend ate the pointerdown — also
  seen live). The smaller thing sits on top: it stays visible and
  recoverable wherever it's parked.

e2e: fit.spec.ts drags by explicit delta from the header centre and
asserts the moved bbox, then minimise → `fit · 2 modes` summary →
expand. (First attempt asserted against `before.x + 140` — that's the
chip's *left edge* plus 140, not the grab point plus 140; the drag was
a ~0 px no-op. Fixed.)

## 2. ‹ › with a multi-line selection → shift the whole selection

New `selection.shiftLines(dir)`: rotates every set's tri-state pattern
one channel, **wrapping within each set** (not the global flat line
list). Chosen semantics and why:

- A hand-picked pair of channels stays a pair as it walks the set.
- A measured channel + its fit-recon line cycle **together**
  (ch1+fit1 → ch2+fit2 → …) — the "ch-fit pair comparison" ask.
- A one-line fit set (subset fit) wraps to itself, so the fit line
  stays put while the data channel steps — a global-flat-list rotation
  would have marched the fit line into the data set (rejected for
  that reason).
- Uniform sets (all-on / all-off / all-fade) are unchanged by
  rotation, so a fully-visible fit overlay or a hidden set stays put.
- Each line KEEPS its own tri-state ('fade' shifts as 'fade').

Tray dispatch (`shiftMode`): ‹ › shift when a **proper subset** of
lines is showing (some off, some visible) that is NOT a clean
whole-set solo; all-on keeps the existing "enter solo stepping"
behaviour, and a clean multi-set solo keeps the tested per-set
stepping. Button titles/aria flip accordingly. Six new store unit
tests + a tray.spec.ts e2e.

## 3. Long-calc progress indication → header computing chip

New `BusyChip.svelte` docked at the right edge of the header's flex
slot: a small pulsing-dot pill, `computing…` (or `starting engine…`
while pyodide boots — the wait that historically read as a hang).
Driven from App by one derived signal: `actions.busy` (ref-counted,
covers every engine calc) OR `damping.busy` OR
`engine.status === 'loading'`.

Deliberate behaviours: 300 ms delay-in so sub-perceptual calcs never
flash it (on the M-series Mac literally everything but the boot is
under the threshold — verified live); fade in/out; indeterminate by
design (the worker protocol is strict request/response — no mid-calc
progress frames exist to show a bar); `prefers-reduced-motion`
respected; `role="status"`. e2e: fit.spec.ts asserts the chip is
visible during the first Calc TF (engine boot) and gone after.

Not covered (accepted): ExportCard's local figure-export busy and the
synchronous .dvma encode/decode (a sync block can't paint a chip
anyway); file *conversions* already show the Converting… toast.

## 4. Docs vs current behaviour → audited, five gaps fixed

A docs audit against the round-7h behaviour found the pages largely
current (the fit-uses-visible-lines section already matched). Fixed:

- **analysis.md** "Nyquist and Bode navigation" note claimed the
  Nyquist brush was *in flight* — it shipped in round 5. Now
  describes the brush + fmin/fmax + per-pane Bode y (±180°|auto).
- **modal-fitting.md**: added the all-lines-hidden refusal ("Nothing
  to fit…"), the "all N lines" wording, and the explicit multi-set
  compose rule (shared poles across sets, over the visible lines of
  each); "a line for every channel" → "a line per fitted channel".
- **analysis.md** Best match: now states it always uses ALL channels
  (calibration op — visibility deliberately doesn't affect it).
- New round-8 behaviours documented: chip drag/minimise
  (modal-fitting.md), ‹ › subset shift (analysis.md tray section),
  computing chip (analysis.md intro).

`python -m mkdocs build --strict` green.

## Suites at close

pytest untouched (no Python changes). webui: `npm run check` 0/0,
vitest 648 passed / 1 skipped (+6 new), Playwright full suite — see
final session summary (fit.spec + tray.spec green after the fixes
above).
