# Best Match: pick the reference by card, and say what will change

Short design, approved by Tore in chat on 2026-11-13.

## Why

Tore calibrated the hammer set's TF (free-mass factor), then ran Best Match
with a noise set loaded. The prompt said the hammer set's factor "will be
replaced" whichever **ref ch** he chose. Pressing Rescale did the right thing
(the noise set landed on the hammer set, the hammer factor stayed), but the
communication was poor:

- The reference SET was never shown. It was the TF card's dataset target, or
  the first card under "All sets". **ref ch** then picked a line inside it, and
  `ch_0` (the input) silently fell back to the only TF column, so `ch_0` and
  `ch_1` chose the same reference line.
- The prompt counted the reference line as "calibrated, will be replaced".
  Its new factor is `refFactor × 1`, i.e. unchanged.

Tore wants the reference to be a TF named by its data card in the tray, and the
prompt to say what actually changes.

## Goals

- The reference is chosen explicitly as a TF line, labelled by its card name.
- The prompt names the reference, says it stays as it is, and lists only what is
  rescaled. "Will be replaced" counts only rescaled lines with a non-identity
  displayed factor.
- No prompt when nothing would be lost (Claude's call, offered to Tore with
  "Always ask first" as the alternative; he chose to build as designed).
- The result toast does not report the reference's own ×1.

## Non-goals

- The matching maths (`analysis.best_match`, the engine op) is unchanged.
- Best Match still uses every TF line of every data set, shown or hidden, and
  still rescales the reference card's OTHER lines onto the reference line.
- The dataset dropdown keeps driving the estimator and x(iω); it no longer
  feeds Best Match.

## Approaches considered

1. **A "ref TF" picker of TF lines labelled by card** (chosen). One option per
   TF line: the card name when the card has one TF line, `card · out/in` when
   it has several (the tray's channel labels). Independent of the dataset
   dropdown; defaults to the first card's first line and falls back to it when
   the chosen card goes.
2. A card picker plus a separate line picker. Two controls for what is almost
   always a one-line choice; rejected.
3. Keep "ref ch" and show the reference set's name beside it. Still ties the
   reference to the dataset dropdown, which is the confusing coupling; rejected.

## The how

- `actions.bestMatchRefs()` lists `{ setId, ch, label }` per TF line (data sets
  only, tray order), so the card reads one list and the label rule lives in one
  place.
- `actions.calcBestMatch(refSetId, refChannel, ...)` keeps its signature;
  `refChannel` is now always a TF line's own source channel from that list. An
  input channel still falls back to column 0 for headless callers.
- `BestMatchInfo` gains `reference` (the reference line's label); `names` lists
  only cards with a rescaled line (the reference card appears only when it has
  other lines, as `card (other lines)`); `calibrated` judges rescaled lines
  only. `calcBestMatch` calls `confirm` only when `calibrated` is non-empty.
- `BestMatchConfirmDialog` takes `reference` and states it stays unchanged.
- Toast: `Best match onto <ref>: <set> ×f, ...`, reference line omitted; a card
  with several rescaled lines lists `line ×f` each.
- Tests: vitest for the info (reference excluded, confirm skipped when nothing
  is at risk, the reference's factor kept), and a Playwright `@engine` spec
  driving the picker and the prompt (closes TODO W3).
- Docs: web-logger `analysis.md` and `calibration.md`; the stale
  `engine.calc_best_match` docstring (it still says channel factors).
