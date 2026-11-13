# Best Match reference picker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Best Match takes its reference as a TF line named by its data card, and its prompt and toast say exactly what changes.

**Architecture:** A pure helper lists the TF lines with their card labels (one rule for the card's picker and the action's messages). `actions.calcBestMatch` keeps its signature but leaves the reference line untouched, asks only when a rescaled line has a calibrated level to lose, and names the reference in its prompt and toast. `TFCard` swaps "ref ch" for a "ref TF" select fed by the helper.

**Tech Stack:** Svelte 5 + TypeScript (webui), vitest, Playwright `@engine`.

**Spec:** `dev/plans/2026-11-13-best-match-reference-design.md`

## Global Constraints

- Option label: the card name when the card has ONE TF line; `card · out/in` when it has several (tray channel labels; an orphan TF uses the plain channel label).
- Toast copy: `Best match onto <ref label>: <name> ×f, ...` (3 significant figures), reference line never listed.
- Prompt names the reference and says it stays as it is; the reference card is listed as rescaled only when it has other TF lines, as `<name> (other lines)`.
- `data-testid` `best-match-ref` and `best-match` stay; dialog test ids stay.

## Review Focus

- The chosen reference card is deleted → the picker falls back to the first TF line; Best Match still runs.
- Only one TF line in the session → info toast "nothing to rescale", engine not called, nothing written.
- Reference card with several TF lines → its other lines are rescaled, the reference line keeps its exact state (no override created from a channel ratio).
- A data set with no TF yet → absent from the picker and from the rescale.
- Orphan TF (TF-only file) → listed by channel label; rescale still writes its stored factors (existing path).

---

### Task 1: TF-line reference list

**Files:**
- Create: `webui/src/lib/analysis/bestMatchRefs.ts`
- Test: `webui/tests/analysis/bestMatchRefs.test.ts`

**Interfaces:**
- Produces: `interface BestMatchRef { key: string; setId: number; ch: number; label: string }`;
  `tfLineChannels(chIn: number | null, nCols: number): number[]` (source channel per TF column);
  `tfLineName(name, ch, chIn, nLines, label): string`;
  `bestMatchRefs(sets: readonly { id: number; name: string }[], tfOf: (setId) => { chIn: number | null | undefined; nCols: number } | undefined, label: (setId, ch) => string): BestMatchRef[]` — key `${setId}:${ch}`, tray order, sets without a TF skipped.

- [ ] Test: single-line card → `[{label: 'hammer', ch: 1}]`; two-line card → `card · ch_1/ch_0`, `card · ch_2/ch_0`; orphan → `card · ch_0`, `card · ch_1`; set with no TF / zero columns skipped; custom channel labels used.
- [ ] Implement; vitest green; commit.

### Task 2: calcBestMatch semantics

**Files:**
- Modify: `webui/src/lib/analysis/actions.ts` (`BestMatchInfo`, `calcBestMatch`)
- Test: `webui/tests/analysis/bestMatch.test.ts`, `tfCalibration.test.ts`, `calStaleFit.test.ts`

**Interfaces:**
- Consumes: `tfLineName`, `tfLineChannels` from Task 1.
- Produces: `BestMatchInfo { reference: string; names: string[]; calibrated: string[] }`.

- [ ] Tests (two sets A ref, B): the reference line's tfCal is untouched (a channel-calibrated A gets NO override); confirm not called when nothing rescaled is calibrated, and the run happens; confirm called with `{reference:'A', names:['B'], calibrated:['B']}` when B carries a TF factor; A with two TF lines → names include `A (other lines)`; one set one line → engine not called, info toast; toast text `Best match onto A: B ×3.00`. Port the single-set tests in `bestMatch.test.ts` and `calStaleFit.test.ts` to two sets.
- [ ] Implement; vitest green; commit.

### Task 3: TF card picker and prompt wording

**Files:**
- Modify: `webui/src/components/cards/TFCard.svelte`, `webui/src/components/BestMatchConfirmDialog.svelte`

- [ ] "ref TF" select of `bestMatchRefs(...)` (`$setsView`, `$derivedStore[id]?.tf`, `$channelLabel`), state = key, fallback to first; disabled with "no TF" when empty; Best match calls `calcBestMatch(ref.setId, ref.ch, ...)`.
- [ ] Dialog takes `reference`, says it stays as it is, lists `names`.
- [ ] `npm run check` 0/0; commit.

### Task 4: e2e (closes TODO W3)

**Files:**
- Create: `webui/e2e/best-match.spec.ts` (`@engine`)

- [ ] Load two TF sets, calibrate the second's TF via Calibrate or `__dataset` hook, pick the first as ref TF, press Best match: prompt names the reference + "stays as it is", lists only the second; Cancel changes nothing; with nothing calibrated no prompt and a success toast naming the reference.
- [ ] Spec green; commit.

### Task 5: Docs

**Files:**
- Modify: `docs/web-logger/analysis.md`, `docs/web-logger/calibration.md`, `pydvma/engine.py` (`calc_best_match` docstring), `TODO.md` (W3), `CHANGELOG.md` (Unreleased)

- [ ] `mkdocs build --strict` clean; commit.
