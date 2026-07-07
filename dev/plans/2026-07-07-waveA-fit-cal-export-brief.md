# Wave A implementation brief — Fit · Calibration · Figures/Export

Scout output (read-only Opus agent, 2026-07-07) for Wave A of
`dev/plans/2026-07-07-full-gui-replacement-plan.md`. Verified refs at
scout time; spot-check line numbers before relying on them.
Normative visual reference: `dev/mockups/round2-bench.html`; spec
`dev/2026-07-03-stage2-gui-design.md` §3/§5/§7.

## Plumbing facts

- `webui/scripts/build-wheels.sh:31` wheels the LOCAL repo
  (`pydvma-1.5.0-py3-none-any.whl`, name hard-coded in
  `engine.ts:18 ENGINE_WHEELS`). Python changes reach the engine on a
  build-wheels rerun ONLY if the version string stays `1.5.0` (a bump
  silently breaks boot until ENGINE_WHEELS is updated — no guard).
- `glue.py` is bundled via `?raw` import (`engine.worker.ts:26`) —
  glue-only changes need just a vite rebuild. Worker dispatch is
  generic (`glue[op].callKwargs(payload)`) so a new `calc_fit` op is
  automatically callable; no client/worker edits.

## A. Modal fitting (pydvma side — nothing new needed for A1)

- `modal_fit_all_channels(tf_data_list, freq_range, measurement_type
  ='acc'|'vel'|'dsp') -> ModalData` (`modal.py:181`) — fits ONE mode
  over freq_range across all non-reconstruction TFs (skips
  `flag_modal_TF`); seeds fn0/zn0 via `f_3dB`; least_squares over
  packed `[fn, zn, an*N, pn*N, rk*N, rm*N]`; multiplies by
  `channel_cal_factors` (`modal.py:227`); sets `modal.MESSAGE`.
- `reconstruct_transfer_function(modal_data, f, mt)` (`:340`, local
  residuals) and `..._global` (`:359`, zeroed residuals); both set
  `flag_modal_TF=True`, non-mutating.
- `ModalData` (`datastructure.py:756`): `.M (n_modes, 2+4*nch)`,
  summaries `.fn .zn .an .pn`, `add_mode` (sorted), `delete_mode`.
  Round-trips `.dvma` (`container.py:81/360`).
- `TfDataList.add_modal_reconstruction(tf, mode='replace'|'append')`
  (`datastructure.py:518`).
- Qt driver: `gui.py:912` card (TF-type combo, fmin/fmax, Fit /
  Reject / Summary / Reconstruction); `fit_mode()` `:2616` fits one
  mode over the zoomed range then local recon overlay (replace);
  `reject_mode()` `:2698` deletes modes with fn in range;
  Best-Match/x(iω) live in the SCALING tool (`:2583`,
  `analysis.best_match:105`), not Fit.
- Sonogram damping: `analysis.calculate_damping_from_sono(time_data,
  n_chan, nperseg, start_time) -> (fn, Qn, fit_data)` (`:651`); Qt
  popup `DampingFitWindow` (`gui.py:241`).
- **Quirk:** ONE mode per call. Mockup's "Fit 1/2/3" = fit that many
  modes in the visible window. Decision (orchestrator): ship Fit-1 =
  Qt-equivalent single-mode-in-window + accumulate via add_mode;
  Fit 2/3 via peak-detection sub-ranges (peakutils is in the engine)
  as best-effort; OMIT "Global optimise" (no engine entry point —
  multi-mode simultaneous fit deferred, flag to Tore).

## B. Webui plumbing

- Add `calc_fit` (and `calc_damping`, `export_mat`) to glue.py
  mirroring `calc_tf` (`glue.py:82`): rebuild TfData objects
  (`TfData.__init__` `datastructure.py:733`), TfDataList, fit,
  reconstruct over dense f; return `{M, fn, zn, an, pn, message,
  recon_freq_axis, recon_tf_data}` via `_arr`. Stateless — JS store
  holds the modal M and re-sends for add/replace/delete.
- `actions.ts`: `calcFit(target, freqRange, mt)` following calcTf —
  extend `Kind` (`:37`), per-kind stale guard, new modal/recon slice.
- **Recon overlay = extra PlotLines on the TF plot**, precedent =
  coherence overlay (`plot/model.ts:338-357`). Mockup: recon pink
  `#be185d`, global recon dashed grey `#66708a`
  (round2-bench.html:1583-1590). Must respect the TF out/in remap +
  off-line visibility machinery (App.svelte:380-412, tfChannels.ts).
- **`fitEngine` capability is never flipped today** (`stages.ts:27/
  37/44`). Flip when a TF result first exists
  (`actions.hasComputed('tf')`), mirroring `acquire.ts:115`.
- Card mount: `ContextCard.svelte:80-107` stage chain — add FitCard.
  Fit stage reuses `view:'tf'`; do NOT add a 'fit' ViewId. Fit range
  = `viewState.sharedFreqRange` (`viewstate.ts:166`).

## C. Calibration

- Field is **`channel_cal_factors`** (multiplier array) on data
  objects; `channel_sensitivities` is a MySettings acquisition-time
  field that seeds it. List API: `get_calibration_factors()`,
  `set_calibration_factors_all()`, `set_calibration_factor()`
  (`datastructure.py:433-516`; 2026-06 bugfix). TF cal is a RATIO
  cal[out]/cal[in] per output column (`:706-724`), set at compute
  time by calculate_tf.
- Applied at DISPLAY time in Qt (`plotting.py:267/271/299`); webui
  `model.ts` does NOT apply cal factors today — the gap. Apply in
  buildPlotModel per branch (ratio for TF).
- **Persistence: use the REAL manifest field** —
  `manifest.items[i].meta.channel_cal_factors` already round-trips
  both codecs (`container.py:86-95/275`; `dvma.ts:107-113`, metaRaw
  `:161`). Write via `setItemMeta(item,'channel_cal_factors',…)`
  (`dataset.ts:77`). Do NOT stuff into the `DvmaItemUi.ui` blob.
  Container wire `format_version` is `1` (JS reader caps at 1).
- UI: mockup Calibrate… modal (round2-bench.html:685-701) from tray
  `⋯` menu (`:677`): per-channel sensitivity + unit select
  (V / m/s² / N / Pa), disabled known-input flow, Cancel/Apply.
  Sensitivity unit label has no dedicated pydvma field — piggy-back
  on `units` or defer authoring (flag to Tore).

## D. Figures / Export

- Existing: PNG + PDF ship (`export/figure.ts:84-181`, jsPDF+svg2pdf;
  white/transparent/dark bg). **Matlab/CSV are disabled stubs**
  (`ExportCard.svelte:143-146`).
- `.mat` schema (`file.py:187-315 export_to_matlab`): keys
  `time_axis_all/time_data_all`, `freq_axis_all/freq_data_all`,
  `tf_axis_all/tf_data_all` — per-kind sets interpolated onto a
  common axis, column-concatenated; complex stays complex; no
  coherence. Browser: `scipy.io.savemat` in a glue op (`export_mat`).
- CSV (`file.py:482-548`): first col = set[0] axis, then data columns
  appended; comma, no header. Reproduce in pure TS. Raw values (no
  cal) in both.
- Font fidelity: exported SVG must carry explicit inline
  font-family/size (same self-contained-SVG fix as the `data-role`
  color pass, `figure.ts:8-15`).
- Mockup Export card (round2-bench.html:577-593): figure (png/pdf) ·
  data (Export Matlab / Export CSV) · autosave switch · Save Dataset.

## Task split (Wave-A dispatch)

Shared spine (actions.ts / plot/model.ts / App.svelte / glue.py) has
ONE owner:

- **Agent 1 — FIT + sono damping (owns spine):** glue.py (calc_fit,
  calc_damping, export_mat for Agent 2), actions.ts, plot/model.ts
  (recon overlay + documented cal-factor seam for Agent 3),
  App.svelte, stages.ts (flip fitEngine), ContextCard.svelte, new
  cards/FitCard.svelte, new stores/modal.ts, SonoCard.svelte
  (damping button + popover).
- **Agent 2 — FIGURES/EXPORT (parallel, disjoint):** export/figure.ts
  (font fidelity), new export/data.ts (TS CSV; .mat dict builder),
  ExportCard.svelte (enable buttons), optional FigurePreview.svelte.
  Calls Agent 1's `export_mat` glue op (spec in this brief).
- **Agent 3 — CALIBRATION (after Agent 1's seam lands):** new
  CalibrateDialog.svelte, TrayCard.svelte (⋯ menu), new
  model/calibration.ts, consume the model.ts seam. Persist via
  setItemMeta channel_cal_factors.

## Risks

- Wheel-name staleness if pyproject version bumps (ENGINE_WHEELS).
- Recon overlay must respect TF remap + off-lines (round-2 precedent).
- Fit-N semantics + Global optimise + unit-string authoring:
  flagged for Tore's next hands-on.
