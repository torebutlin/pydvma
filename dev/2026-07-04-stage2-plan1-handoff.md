# Stage 2 · Plan 1 — handoff (the no-install browser analysis app)

**Date:** 2026-07-04 · **Status:** Plan 1 complete — all 16 tasks landed,
two-stage reviewed, milestone-gate passed. **Nothing is pushed** (your call);
the CI/Pages workflows activate on your next `git push`.

The next working session should be **hands-on with your real lab `.dvma`
files** (see "Try it" below), then decide the Plan-2 open questions in
"Decisions for you". A fresh Claude session should read this file first.

---

## TL;DR

`webui/` is a Svelte 5 + TypeScript + Vite app that loads/creates `.dvma`
datasets and runs the **analysis half** of the old Qt GUI entirely in the
browser — FFT/PSD/CSD, transfer functions (+ averaging + coherence),
sonograms, all the plot views (mag/phase/Bode/real/imag/Nyquist), a
draggable legend with tri-state on/fade/off lines, box-zoom/pan navigation,
autosave, and PNG/PDF figure export. All the maths runs in **real pydvma**
inside a pyodide web worker — no formulas were reimplemented in JS.

Acquisition, the oscilloscope/monitor, modal fitting, calibration, and the
`pydvma serve` NI bridge are **Plan 2+** (see backlog).

## Try it

```bash
cd webui
npm install            # first time only
npm run dev            # vite dev server on http://localhost:5173
```

- **See it working immediately with sample data:**
  `http://localhost:5173/?fixture=1` auto-loads a checked-in 2-channel
  impulse set (`src/assets/impulse.dvma`). Click **TF → Calc TF**, then flip
  the **Plot type** dropdown through Mag / Phase / Bode / Real / Imag /
  Nyquist. Try **Freq** (FFT/PSD/CSD + averaging), **Sonogram**, and
  **Export**.
- **Your own data:** the **Load Data** button (top bar) opens a `.dvma`,
  legacy pickle `.npy`, or `.mat`. Or set a **working directory** (Downloads
  chip → it anchors Load/Save/Export/autosave to one folder when your
  browser supports the File System Access API; Chrome/Edge do, Safari/Firefox
  fall back to download/upload).
- First compute boots pyodide (a few seconds — numpy/scipy stream from the
  jsdelivr CDN; pydvma + peakutils are vendored). The shell never blocks:
  compute calls queue until the engine is ready.

## What's live (mapped to the design spec §-numbers)

| Area | Spec | State |
|---|---|---|
| Bench shell: header, gated ribbon, context card, data tray | §2 §3 | ✅ |
| Data model + tray: sets as cards, rename, delete, tri-state on/fade/off, matrix batch ops | §3 | ✅ |
| Views: Time, Frequency (FFT/PSD/CSD + within/across averaging), TF (mag/phase/Bode/real/imag/Nyquist), Sonogram | §5 | ✅ |
| Coherence overlay (dashed right-axis, mag/phase only) | §5 | ✅ |
| Nyquist (square, fits data, fmin/fmax window) | §5 | ✅ |
| Plot navigation: box-zoom, pan, back/forward history, Auto X/Y, manual limits | §6 | ✅ |
| Legend: draggable + corner/edge presets, tri-state mirror | §3 §6 | ✅ |
| Figures: PNG + PDF export, white/transparent/dark backgrounds | §7 | ✅ |
| Save/Load `.dvma`; legacy `.npy` + `.mat` import; working directory; autosave + restore banner | §7 | ✅ |
| Adaptive/narrow layout: rail + flyover tray | §9 | ✅ |
| Debuggability: per-kind stale-guard, boot-error rejection (no silent hangs), `window.__viewState` hook under `?fixture=1` | §11 | ✅ |
| Deployment: CI test/build + Pages deploy to `/app/`; relative asset paths | §11 | ✅ (inactive until you push) |
| Figure-export dark mode (app-wide dark theme is Plan 2) | §7 §10 | ✅ (partial) |

## Milestone-gate results (2026-07-04)

All suites green on this Mac:

- **Python:** `pytest tests/ -q` → **205 passed, 4 skipped** (hardware
  auto-skips; `pydvma/` and repo-root `tests/` were never touched).
- **webui unit:** `npx vitest run` → **152 passed, 1 skipped**.
- **type/lint gate:** `npm run check` → **0 errors, 0 warnings** (131 files).
- **e2e:** non-`@engine` **17 passed, 1 skipped** (parallel); `@engine`
  (real pyodide boot) **4 passed** (serial, `--workers=1`).
- **build:** `npm run build` → `dist/` with vendored `pyodide/`+`pypi/` and
  relative `./assets` paths (works under `/pydvma/app/`).

**Two bugs were found by the branch-wide review and fixed at the gate:**

1. **Nyquist axis corruption (Critical).** The TF view's committed range `.x`
   is a *frequency* band (it doubles as the Nyquist locus window). The model
   was also applying it to the Real/Imag axes, so setting fmin/fmax — or
   box-zooming TF-mag then switching to Nyquist — collapsed the locus to a
   dot. Fixed (Nyquist axes auto-fit the windowed locus and square);
   unit-locked + verified live in the browser. Commit `5b60fbb`.
2. **Clean Impulse data-loss (Important — your #1 pain point).** Clean
   Impulse mutated the dataset in place without re-emitting the store, so
   **autosave never captured the cleaned data** (explicit Save was fine).
   A clean-then-close silently lost the cleanup. Fixed (store re-emits);
   unit-locked. Commit `6791ad3`.

## Decisions for you (hands-on-session agenda)

1. **Multi-channel TF channel mapping (confirmed bug, needs your call on
   labelling).** `calculate_tf(ch_in)` drops the input channel, so `tf_data`
   has `N_channels − 1` output columns. The plot currently indexes those
   columns by the *source* channel number, so for **>2 channels** it
   mislabels TF lines and silently drops one (a 4-channel cDAQ set would show
   this). For the common 2-channel case it renders one TF line, just under
   the input-channel's legend label. The fix is mechanical (remap the visible
   channel through the output-channel set, skipping `ch_in`), but it embeds a
   **labelling choice**: should a TF line be labelled by its **output
   channel**, or as `H (out/in)`? And should the selected *input* channel
   simply show no line in the TF view (physically it has no self-TF)? Pick a
   convention and it's a small follow-up. *(Engine-seam review, `model.ts`
   TF branch + the coherence-overlay loop have the same remap need.)*
2. **X-axis Lin/Log toggle.** Present in the old Qt GUI, absent from the
   Stage-2 spec (frequency axes are linear). Want it back? It's a small
   addition to the plot core + view-state.
3. **Figure-export fonts.** Exported tick/axis-label text falls back to a
   default font (jsPDF Helvetica / SVG default) — colours are inlined but the
   app's mono/body fonts aren't. Roughly at parity with the old Qt export.
   If you want WYSIWYG fonts in figures, it's a small follow-up (inline
   font-family/size the way the colours were).
4. **Deploy coupling (FYI, not a bug).** The Pages deploy builds the docs +
   JupyterLite + the Stage-2 app as one atomic artifact, so a webui build
   failure would also block a docs deploy. That's the intended
   single-artifact model (and `webui.yml` gates webui changes independently),
   but be aware of it.

## Known deliberate deviations (recorded, not oversights)

- `.dvma` uses **fflate** (smaller, sync) rather than jszip (the spec's jszip
  was parenthetical). Round-trip is byte-checked against the Python writer.
- **CSD** shows the coherence diagonal only; `Pxy` off-diagonal pair selection
  is deferred (needs a pair-picker UX).
- **Matlab/CSV export** from the browser is deferred (import works).
- **App-wide dark theme** is deferred (tokens exist; figure-export dark ships).
- `noUnusedLocals`/`noUnusedParameters` in `tsconfig.app.json`: evaluated at
  the gate (amendment A5) and **deferred** — `tsc` is clean and the flags
  wouldn't catch the (used-within-file) exports we have; revisit if litter
  appears.

## Repo / CI state

- **Not pushed.** Local `master` is ahead of `origin/master`. The
  `.github/workflows/webui.yml` (test+build) and the extended
  `.github/workflows/docs.yml` (Pages deploy → `/pydvma/app/`) go live on
  your next push. CI runs `@engine` Playwright serially (pyodide can't boot 3
  concurrent workers reliably) and gates `PYODIDE_VERSION` against the
  vendored runtime (`scripts/check-pyodide-version.mjs`).
- **Vendored, gitignored:** `webui/public/pyodide` (runtime, staged from the
  npm devDep by `scripts/fetch-pyodide.sh`) and `webui/public/pypi`
  (pydvma+peakutils wheels, built by `scripts/build-wheels.sh`). Both are
  regenerated in CI; you need them locally for `@engine` e2e and `build`.
- Per-task commits from `6588d8b` (scaffold) to HEAD; each task was
  implemented then two-stage reviewed (spec + quality) before closing.

## Plan-2 backlog (out of scope for Plan 1, tracked)

Acquisition (Setup/Acquire cards, one **Log** button + **OUT** badge,
pretrigger); monitor/oscilloscope (stacked-traces toggle, pop-out); levels in
the header/tab title; the **Fit** stage (modal fitting, editable/deletable
fits, reconstruction); **sonogram damping-fit** interactivity (draggable
start line + threshold slider); **calibration** dialog +
`channel_sensitivities` write-through; **Best Match / x(iω)** scaling group;
Matlab/CSV **export** from the browser; **CSD off-diagonals**; app-wide
**dark theme**; the **TF multi-channel labelling** decision (#1 above);
the **X-log toggle** (#2); **figure-export fonts** (#3); `pydvma serve`
bridge + capability metadata + NI (Plan 3); PWA packaging. `ExportCard`'s
download path duplicates `workdir.fallbackDir()` — consolidate when touched.
