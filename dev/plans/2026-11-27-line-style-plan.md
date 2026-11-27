# Line colour and thickness per line — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New sets never reuse a colour still on screen, and each data
line's colour (from the 12-colour palette) and thickness (thin / normal /
bold) can be changed from a ⋯ panel on its tray card, saved with the file.

**Architecture:** The selection store already owns each set's `colors`;
it gains `widths` and `autoColors` beside them, so the tray, legend and
plot read styles from one place. `actions` wraps the edits (fit lines
mirror the colour, the document re-emits for autosave) and persists them
in each item's `ui`. The plot model takes a per-line `width`.

**Tech Stack:** Svelte 5 runes, TypeScript, vitest (`webui/tests`),
Playwright (`webui/e2e`, run from `webui/`).

**Spec:** `dev/plans/2026-11-27-line-style-design.md`

## Global Constraints

- Palette: `LINE_PALETTE` (12 colours) only; no free colour picker.
- Weights: `thin` 1 px, `normal` 1.5 px (default, today's width), `bold` 2.5 px.
- No dashed option. Fit, coherence, σ and band lines keep their widths.
- Fit (`role: 'fit'`) cards get no ⋯; fit lines mirror the source COLOUR only.
- Persist sparse, only changed lines: `ui.line_colors` `{"<ch>": "#rrggbb"}`,
  `ui.line_widths` `{"<ch>": "thin"|"bold"}`. Loaded colour must match
  `/^#[0-9a-f]{6}$/i`, weight must be `thin|normal|bold`; else ignored.
- Gate before commit: `npm run check` (0/0) and `npx vitest run`, from `webui/`.

## Review Focus

1. A set restored by the delete's Undo keeps its picked colours and weights (Task 3 test).
2. A reopened file whose style keys are malformed (`"red"`, `"huge"`, a channel past the end) loads, ignoring them (Task 3 test).
3. Recolouring a line that has a SUBSET fit recolours only the fit line of that channel (Task 3 test).
4. A colour the user picked is not handed to the next new set while a free one exists (Task 2 test).
5. The ⋯ panel in the narrow layout's tray drawer works the same (Task 5: wire NarrowRail too; e2e at desktop only).

---

### Task 1: Automatic colours skip colours in use

**Files:** Modify `webui/src/lib/stores/selection.ts` (`addSet`); Test `webui/tests/stores/selection.test.ts`

**Interfaces:** Produces the colour rule Task 2 relies on (it counts `set.colors` of every `role === 'data'` set).

- [ ] **Step 1: Failing tests** in a fresh `createSelection()`:
  - `a set logged after a delete takes the freed colours, not a survivor's`:
    add A(2ch), B(2ch); `removeSet(A)`; add C(2ch) → C's colours are
    `[LINE_PALETTE[0], LINE_PALETTE[1]]`, and differ from B's.
  - `past 12 lines the least-used colours go next`: add six 2-ch sets, remove
    the third (palette 4, 5), add a 3-ch set → `[P[4], P[5], P[0]]`.
  - Existing palette tests (lines ~400–481) must still pass unchanged.
- [ ] **Step 2:** `npx vitest run tests/stores/selection.test.ts` → the two new tests FAIL.
- [ ] **Step 3:** In `addSet`, replace the `start + c` offset with: count uses of
  each palette entry over current data sets' `colors`; for each channel pick
  the lowest-count index (ties: lowest index), then increment its count.
  Update the `addSet` and `LINE_PALETTE` docstrings.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5:** Commit `fix(webui): a new set's lines take colours no line on screen is using`.

### Task 2: Per-line styles in the selection store

**Files:** Modify `webui/src/lib/stores/selection.ts`; Test `webui/tests/stores/selection.test.ts`

**Interfaces — produces:**
- `export type LineWeight = 'thin' | 'normal' | 'bold'`
- `export const LINE_WEIGHT_PX: Record<LineWeight, number>` = `{ thin: 1, normal: 1.5, bold: 2.5 }`
- `SetEntry` gains `widths?: LineWeight[]`, `autoColors?: string[]`;
  `SetRecord` gains `widths: LineWeight[]`, `autoColors: string[]`
  (`autoColors` = the colours `addSet` gave, or the supplied `autoColors`;
  `widths` default all `'normal'`).
- `LegendEntry` gains `weight: LineWeight` (both `legendEntries` and `legendRows`).
- `setLineColor(id: number, ch: number, color: string): void` (no-op for unknown id/ch)
- `setLineWeight(id: number, ch: number, weight: LineWeight): void`
- `resetLineStyles(id: number): void` → `colors = autoColors`, widths normal
- `getLineStylesForSet(id: number): { line_colors?: Record<string, string>; line_widths?: Record<string, LineWeight> } | undefined`
  — only lines whose colour ≠ autoColor or weight ≠ normal; `undefined` when none.

- [ ] **Step 1: Failing tests:** `setLineColor recolours tray, legend and lineColor`;
  `setLineWeight shows in legendEntries.weight`; `resetLineStyles restores the
  colours the set was given`; `getLineStylesForSet is sparse and undefined when
  untouched`; `a picked colour counts as used by the next set` (A 2ch, set A ch1
  to P[2], add B 2ch → B gets `[P[1], P[3]]`).
- [ ] **Step 2:** run → FAIL.  **Step 3:** implement (copy-on-write `sets.update`).
- [ ] **Step 4:** run → PASS.  **Step 5:** commit `feat(webui): per-line colour and weight in the selection store`.

### Task 3: Actions — edit, mirror to the fit, persist, undo

**Files:** Modify `webui/src/lib/analysis/actions.ts`, `webui/src/lib/model/dataset.ts` (`DvmaItemUi` + its doc); Test create `webui/tests/analysis/lineStyle.test.ts` (harness as `tests/analysis/renameSet.test.ts`: `createActions(stubEngine, createSelection())`, `addRecordedSet`, `reopen` via `writeDvma`/`readDvma`).

**Interfaces — produces (exported from `createActions`):**
- `setLineStyle(setId: number, ch: number, style: { color?: string; weight?: LineWeight }): void`
- `resetLineStyles(setId: number): void`

Both call the selection methods, then recolour the set's fit pseudo-set
(`fitSets.get(setId)`: line `c` mirrors source channel `chans[c]` for a
subset key, else `c`), then `dataset.update(d => d)` when the set is in
`working`. `stampUiState` writes `getLineStylesForSet` into `ui`;
`loadDataset` restores it for TimeData sets AND orphan sets (one helper
`restoreLineUi(setId, ui, nCh)` that also applies `channel_labels`, used
in both passes). The delete Undo path (`addSet` near line 2903) passes
`widths` and `autoColors` from the record.

- [ ] **Step 1: Failing tests:** `a picked colour and weight survive Save and reopen`;
  `a style change re-emits the document once`; `malformed style keys in a file are
  ignored` (`line_colors: {"0":"red","5":"#123456"}`, `line_widths: {"1":"huge"}` →
  automatic colours, normal widths, no throw); `recolouring a fitted line recolours
  its fit line` (use the fit harness from `tests/analysis/modalPseudoSet.test.ts`);
  `undo of a delete brings the styles back` (`removeSet` then the undo the toast
  offers, as `tests/analysis/removeSet.test.ts` does).
- [ ] **Step 2:** run → FAIL.  **Step 3:** implement.  **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat(webui): line styles are saved with the set and follow to its fit`.

### Task 4: Plot draws each line's weight

**Files:** Modify `webui/src/lib/plot/model.ts` (`VisibleLine.width?: number`; `baseLine` and the TF line use `v.width ?? 1.5`), `webui/src/App.svelte` (`visible`: `width: LINE_WEIGHT_PX[e.weight]`); Test `webui/tests/plot/model.test.ts`.

- [ ] **Step 1: Failing test** `a visible line's width reaches the time, frequency and TF lines; coherence keeps 1`.
- [ ] **Step 2:** run → FAIL.  **Step 3:** implement.  **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat(webui): plot lines take their line's weight`.

### Task 5: The ⋯ panel on a data card

**Files:** Create `webui/src/components/LineStylePanel.svelte`; Modify `TrayCard.svelte`, `Tray.svelte`, `NarrowRail.svelte`, `App.svelte` (pass `onSetLineStyle={actions.setLineStyle}`, `onResetLineStyles={actions.resetLineStyles}` to both Tray and NarrowRail); Test create `webui/e2e/line-style.spec.ts` (non-@engine, `/?fixture=1`).

Panel: one block per line — chip + label (`tfLineLabel` rules as the row),
12 swatch buttons (`data-testid="line-swatch-{ch}-{i}"`, `aria-pressed` on the
current, title = colour name), `Segmented` thin/normal/bold
(`testid` `line-weight-{ch}-{w}`); footer **Reset to automatic**
(`line-style-reset`) and **Done** (`line-style-done`). The ⋯ button
(`line-style-open`, title "Line colour and thickness…") sits before `cal`,
only when `onSetLineStyle` is given (so never on fit cards); it toggles a
POP-UP (`line-style-panel`, Tore's ruling) mounted on `document.body` at the
button's rect, clamped inside the window, closing on Escape, on a press
outside it and the button, and on Done. Clicks inside it must not cycle
the set.

- [ ] **Step 1: Failing e2e:** open ⋯ on `tray-card-0`, click `line-swatch-0-6`
  and `line-weight-0-bold` → the first `plot-line` has `stroke=LINE_PALETTE[6]`
  and `stroke-width="2.5"`; the legend swatch shows the colour; Reset → back to
  `#2563eb`, `1.5`; Escape closes the panel; clicking a swatch leaves the set's
  lines `on`.
- [ ] **Step 2:** `npx playwright test e2e/line-style.spec.ts` (from `webui/`) → FAIL.
- [ ] **Step 3:** implement.  **Step 4:** run → PASS; `npm run check` 0/0.
- [ ] **Step 5:** commit `feat(webui): ⋯ on a tray card picks each line's colour and thickness`.

### Task 6: Docs, verify, wrap

- [ ] `docs/web-logger/` tray page: a short paragraph on ⋯ (where, what, saved with the file); CHANGELOG `## Unreleased` Added (⋯) + Fixed (colour reuse after a delete); `python -m mkdocs build --strict` clean.
- [ ] Browser check on the built app (light, dark, narrow drawer): screenshot of the open panel and a bold recoloured line; Save Figure PNG shows the weight.
- [ ] Full gate: `npm run check`, `npx vitest run`, Playwright non-@engine suite; commit `docs: line colour and thickness`.
