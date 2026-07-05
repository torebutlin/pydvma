# Stage 2 · Plan 1.5 — analysis-card redesign (build plan)

> **STATUS: all five tasks landed 2026-07-05** (R1–R5), each two-stage
> reviewed, combined suite green (pytest 205 · vitest 226 · check 0/0 ·
> e2e 26 non-@engine + 7 @engine · build OK), and the whole redesign
> smoke-verified in-browser together. Not pushed. Deferred/for-Tore notes:
> the dropdown-solos-the-set coupling (R1), a channel label's single-click
> is reserved for rename so only the rest of the row toggles (R5),
> per-set settings + channel labels are in-session (not yet in `.dvma`).

Source: `dev/2026-07-05-hands-on-feedback.md` §C10 + §D (Tore's hands-on
review). Builds on the layout polish (block B, landed). Five tasks; R1 is the
load-bearing architecture change, the rest layer on top. Same execution model
as Plan 1: per-task TDD, in-browser verification, two-stage review, small
commits, **no push**.

---

## Design decisions

Resolved (my calls, rationale below); the one genuinely open fork is flagged
**[CONFIRM]** and is asked before R1 starts.

- **Per-set analysis settings.** Each set carries its own analysis settings.
  New store `analysisSettings` keyed by setId:
  `{ freq: {window, mode, nFrames}, tf: {chIn, window, averaging, nFrames},
     sono: {nFft, dynRangeDb} }`, seeded from sensible defaults on `addSet`.
  (`calcSono`/`cleanImpulse` are already per-set; `calcFft/calcPsd/calcTf`
  become per-set — they currently loop all sets with one global setting.)
- **Focused set + dataset dropdown.** A shared `analysisTarget: 'all' | setId`
  drives every analysis card's **"Dataset ▾"** dropdown (first control in the
  card): *All sets* + one entry per set (by name).
  - Target = a **set** → the card's controls show/edit THAT set's settings;
    **Calc** runs that set only.
  - Target = **All** → controls show the shared value, or **"–mixed–"** when
    sets differ; editing a control writes it to **every** set; **Calc** runs
    all. ("–mixed–" is display-only; the first edit makes them agree.)
- **Tray ↔ dropdown sync — CONFIRMED "dropdown follows the tray".** The
  dropdown mirrors the tray: focusing/soloing one set → dropdown shows that set
  + its settings; multiple sets shown → dropdown reads **All** with "–mixed–"
  where they differ. Editing in a set-target edits that set; editing in **All**
  applies to **every** set. Picking a set in the dropdown focuses it in the
  tray (reuse `selection.highlight` + `solo`). So `analysisTarget` is derived
  from / two-way-bound with the tray focus, not an independent control.
- **log / lin is per-VIEW, not per-set.** `xScale`/`yScale` live in `ViewSlice`
  (viewstate), toggled from the toolbar/card. Independent of per-set settings.
  **CONFIRMED semantics:** x toggle = frequency axis linear/log (the Bode win);
  **y toggle = dB (log magnitude) ↔ linear magnitude** — a real model change
  (compute `|H|` vs `20·log10|H|`, and `10·log10` vs linear for PSD), with the
  y-axis label following. Applies to magnitude views (FFT mag / TF mag / PSD);
  N/A on phase / real / imag / Nyquist (leave linear).
- **Settings persistence.** In-session only for v1 (the `analysisSettings`
  store is not written to `.dvma`). Persisting per-set settings into the
  manifest is a small, additive follow-up — deferred, noted in TODO.
- **TF labelling = out/in** (Tore's pick). Fixes the confirmed multi-channel
  bug (E1): `tf_data` drops the input channel, so N−1 output columns must be
  remapped and labelled `out/in` (e.g. `ch1/ch0`); the input channel shows no
  TF line. Uses the custom channel labels from R5 when present.

---

## Tasks

### R1 — Per-set settings store + dataset dropdown (foundation)
**Files:** new `src/lib/stores/analysisSettings.ts`; `src/lib/analysis/actions.ts`
(calc* read per-set settings + accept a target); `src/components/cards/{Frequency,TF,Sono}Card.svelte`
(add the Dataset dropdown, bind controls to the focused set's settings, "–mixed–");
`src/App.svelte` (wire the store); `src/lib/stores/selection.ts` (focus↔highlight).
- Store: `analysisSettings` (Record<setId, PerSetSettings>) with defaults on
  addSet + cleanup on removeSet; `analysisTarget` writable; helpers
  `get(setId,view)`, `set(target,view,patch)` (patch-all when target='all'),
  `isMixed(view,key)`.
- `calc*` take a `target: 'all'|setId`, read each set's settings, run the
  matching sets. Preserve the per-kind stale-guard + ref-counted busy.
- Cards: Dataset dropdown (All + sets); controls two-way bind to the focused
  settings; show "–mixed–" placeholder when `isMixed`.
- **Tests:** store unit tests (defaults, patch-all, isMixed, add/remove
  lifecycle); actions tests (per-set targeting; All applies to all); e2e —
  two sets, different windows, dropdown switches settings, "–mixed–" shows.

### R2 — ΔF resolution control: slider + text box
**Files:** new `src/components/ResolutionControl.svelte` (shared); wired into
Frequency (PSD/CSD) + TF (averaging) + Sono (nFft). Uses `analysis/resolution.ts`.
- Each resolution quantity (N frames / frame-length / ΔF / nFFT) is a
  **slider paired with a text box**. The **text box accepts values outside the
  slider range** (slider clamps to its end-stops, doesn't fight the number).
  Sliders ship a **sensible default range** derived from the set (fs, duration).
- **Precompute (Tore's Q):** precompute the slider's value↔ΔF mapping when the
  set is small (fast, slick); for large sets compute on release. Threshold on
  sample count. `log()`-equivalent comment noting the cap.
- **Tests:** ResolutionControl unit (out-of-range text clamps slider, mapping
  correct against `resolution.ts` ground truth); e2e drag + type-out-of-range.

### R3 — Log/lin toggles for x and y  *(independent — can start immediately)*
**Files:** `src/lib/stores/viewstate.ts` (`xScale: 'lin'|'log'`,
`yScale: 'lin'|'log'` in ViewSlice + restore-guard); `src/lib/plot/{scales,build}.ts`
(log10 transform, decade ticks, guard ≤0); `src/components/{ZoomToolbar,PlotSurface}.svelte`
(x/y lin·log toggle UI); `src/lib/plot/model.ts` (y magnitude representation).
- **x toggle** = frequency axis linear/log10 (decade gridlines/ticks, skip/clamp
  ≤0). Applies to frequency/tf/psd/csd x-axes; time x stays linear.
- **y toggle = dB ↔ linear magnitude** (CONFIRMED): `yScale='log'` → dB
  (`20·log10|H|` for FFT/TF mag, `10·log10` for PSD, current behaviour);
  `yScale='lin'` → linear magnitude (`|H|`, linear PSD). The y-axis LABEL
  follows ("|H| (dB)" ↔ "|H|"). model.ts branches on the view's yScale. N/A on
  phase/real/imag/Nyquist (ignore the toggle there).
- **Tests:** scales unit (log mapping + decade ticks + ≤0 guard); model unit
  (yScale='lin' returns |H|, not dB); e2e toggle changes ticks/label.

### R4 — TF out/in channel labelling + multi-channel fix
**Files:** `src/lib/analysis/actions.ts` (store `chIn` on the tf slice);
`src/lib/plot/model.ts` (remap visible ch → output column, skip input, label
`out/in`); `src/lib/stores/selection.ts`/legend (out/in label). Depends on R1
(chIn is per-set) + R5 (custom labels) but degrades gracefully with `ch_n`.
- Remap: output columns = sorted(channels ∖ {chIn}); `v.ch===chIn` → no line;
  else column = index within the output set. Label `${outLabel}/${inLabel}`.
  Same remap in the coherence-overlay loop.
- **Tests:** model unit (3-channel TF: correct columns, input dropped, labels);
  e2e multi-channel fixture (needs a 3-ch fixture — add one).

### R5 — Per-line (channel) relabel
**Files:** `src/lib/stores/selection.ts` (per-channel `label` storage +
`renameChannel(setId,ch,label)`); `src/components/TrayCard.svelte` (double-click
channel label → inline rename, mirrors the set rename); legend + model use the
label. Optional: persist channel labels to `.dvma` (defer with R1's persistence).
- **Tests:** selection unit (renameChannel, defaults, per-set independence);
  e2e rename a channel → reflected in legend + tray.

---

## Ordering & execution

1. **R3** can start now (independent plot-core work).
2. **R1** is the foundation — build it once the [CONFIRM] fork is settled.
3. **R2** and **R4** layer on R1 (they edit the restructured cards / per-set chIn).
4. **R5** pairs with R4 (labels feed the out/in display).

Execution: subagent-driven (Opus implementer → spec review → quality review),
per-task commits, in-browser verification each task, full suite (pytest +
vitest + e2e + build) green before closing each. Update
`dev/2026-07-05-hands-on-feedback.md` as each lands. No push.

## Testing baseline to keep green
`pytest tests/ -q` · `npx vitest run` · `npm run check` · `npx playwright test`
(`@engine` serial). Add: analysisSettings + ResolutionControl unit suites, a
3-channel TF fixture, and e2e for the dropdown / "–mixed–" / log-lin / rename.
