# Line colour and thickness per line — design (2026-11-27)

Small change. Tore's ask, from the 4C6 lab: students ended up with two
lines from two sets in the tray drawn in the same colour; offer a simple
way to change a line's colour, and its thickness, without endless menus.

## Why the colours matched (a bug, fixed here too)

`selection.addSet` gave a new set `LINE_PALETTE[(start + ch) % 12]`,
with `start` the number of DATA-set channels in the tray at that moment.
Deleting a set lowers the count but frees no colour, so log A, log B,
delete A, log C gives C exactly B's colours (confirmed in vitest: both
`#059669`, `#d97706`). Log, delete, log again is the lab's normal rhythm.

**Fix:** a new data set's lines take the palette colours used by the
fewest lines on screen, ties in palette order, one line at a time. With
nothing deleted this is the old rule exactly (12 channels → 0..11, the
13th wraps to 0), so files open in the same colours as before; after a
delete the freed colours are reused first, and no two lines share a
colour until there are more than 12. A colour the user picked counts as
used. Fit pseudo-sets still mirror their source and take no slot.

## The menu (Tore's design, his choices in bold)

- A **⋯ on each data set's tray card** (not on a modal-fit card: fit
  lines mirror their measured line).
- It opens a small panel inside the card, one block per line: the line's
  label, the **finite 12-colour palette** as swatches (current one
  ringed), and **thin / normal / bold, per line** (Tore: per line, so
  one line can stand out). **No dashed option** — dashes mean coherence
  and fit lines. A "Reset to automatic" puts the set back.
- Keep it simple: nothing else (no opacity, markers, custom hex).

## Behaviour (my calls, stated to Tore)

- Widths on screen: thin 1 px, normal 1.5 px (today's width), bold
  2.5 px. Applied to the measured lines in the time, frequency and TF
  views (Bode, Nyquist included); coherence, σ, band and fit-overlay
  lines keep their own widths.
- Saved figures follow automatically (they redraw the same lines;
  `printFigure` scales `line.width`).
- A modal fit's lines follow their measured line's COLOUR (recolour the
  line, the fit follows); they stay at their own width.
- Persisted per item in the `.dvma` `ui`, like renamed channels:
  `ui.line_colors` `{"1": "#dc2626"}` and `ui.line_widths`
  `{"0": "bold"}`, sparse, only where changed. So reload, session
  restore, journal and autosave keep them; Python ignores `ui`. Loaded
  colours must be `#rrggbb`; anything else is ignored.
- A style change re-emits the document so autosave / the journal see it
  (as a channel rename does). Undo of a set delete restores its styles.
- "Reset to automatic" restores the colours the set was given when it
  appeared, and normal width.

## Approaches considered

- **Per-set thickness** (one control per card): simpler, but cannot
  pick out one line. Tore chose per line.
- **A floating popover** vs **a panel inside the card**: the tray
  scrolls, so a popover anchored in it clips near the bottom; a panel in
  the card cannot clip and works the same in the narrow layout. Panel
  chosen (my call).
- **Colour picker with any colour**: rejected by Tore (finite palette).
