# pydvma — TODO / Backlog

The big pre-web-UI backlog is **done**. Across 2026-06 → 2026-07 the
package gained a real test suite, a vectorised analysis core, the
`nidaqmx` NI migration (USB-6003 / USB-6212 / cDAQ-9174, hardware-
verified), and — the headline — a complete **browser web logger**
(`webui/` + `pydvma-serve`) that reached full parity with the old Qt
GUI, which has now been **removed** (last Qt version: the `qt-final`
git tag). The decision trail and per-round detail live in `dev/` (see
`dev/plans/2026-07-07-full-gui-replacement-plan.md` and the
`dev/2026-07-0x-round*-feedback.md` series) and in the git history;
this file now tracks only what is still open.

## Current backlog — web logger follow-ups (round 7)

Flagged during the round-5/6 hands-on rounds; pick up alongside Tore's
next hands-on pass:

- **CSD phase** — the glue must return the complex `Pxy` so the CSD
  pair view can show phase (currently magnitude only).
- **Browser pretrigger threshold control** — expose the trigger
  threshold in the browser Acquire UI (the bridge already has it).
- **Log-y heat rendering for the CWT sonogram.**
- **CSD pair auto-enable on a hidden channel** — selecting a CSD pair
  should re-enable a channel that is currently hidden.
- **Orphan-fit browser e2e** — Playwright cover for the round-6
  orphan-TF fit crash (in progress, task_c158292c).
- **PWA manifest** — installability (manifest first; offline later).
- **Narrow-band CWT damping memory optimisation.**

## Current backlog — hands-on & hardware

- **Tore hands-on round 7** — review the newest surface: shared-pole
  fitting, Best-match / x(iω) scaling group, `/config` prefill,
  sonogram single-targeting, brush v2, dark mode.
- **PC multi-channel + NI recheck** (pending since round 6) — on the
  Windows box, eyeball the 9260 output-rail clamp and the DSA
  coerced-fs notes on Setup/Acquire, and re-verify multi-channel NI
  capture end-to-end.
- **IEPE auto-detect via bias-voltage probe** — enable 2 mA
  excitation and read the DC bias before AC coupling to classify what
  is connected (~24 V open / 8–14 V IEPE sensor / ~0 V low-Z) so
  `iepe_excit_current_A='auto'` can configure each 9234 channel.
  Sensitivity still has to be entered manually.

## Housekeeping (smaller open items)

- **Finish the docs accuracy audit** — the Qt pages were corrected
  when the GUI was removed; the rest of `docs/` still deserves a
  page-by-page cross-check against real behaviour (several pages were
  originally Claude-generated).
- **Test-suite tail** — beyond the bug-pin cases already landed:
  broader `modal.py` multi-mode synthetic fits, `datastructure.py`
  save/load and list ops, and `file.py` `.npy` / CSV / MATLAB import
  round-trips.
- **Import-time / structure cleanup (remainder)** — cache lazy imports
  in `pydvma/__init__.py.__getattr__` (`globals()[name] = ...`);
  silence the `DeprecationWarning: __package__ != __spec__.parent`
  from `_ni_device_specs.py:227`; fix the copy-paste docstrings on
  `DataSet.calculate_tf_set` / `calculate_cross_spectrum_matrix_set` /
  `calculate_tf_averaged` (all three still say "Calls calculate_fft").
- **`streams.py` singletons** — the module-level recorder globals
  (`REC` / `REC_SC` / `REC_NI` / `REC_MOCK`) and `start_stream`
  re-`__init__` are fragile; pass recorder instances explicitly. (The
  mocked harness now guards the behaviour.)
- **Centralise optional hardware imports** — a small `_hardware.py`
  that does the `sounddevice` / `nidaqmx` try-imports once and exposes
  flags + handles, instead of the scattered try/except in `streams.py`
  / `options.py`.
- **Better output-signal control** — offset, ramp, and save/reload of
  signal definitions (the web logger already covers type / amplitude /
  band / sweep).
- **Repo-root cleanup** — the six tracked docs-about-docs files
  (`DOCS_SETUP_SUMMARY.md`, `MKDOCSTRINGS_INTEGRATION.md`,
  `DOCUMENTATION.md`, `README_DOCS.md`, `.mkdocs_quickref.md`,
  `CODE_STRUCTURE.md`) and the personal `logger.yml` conda export —
  fold anything still true into `docs/` or `CLAUDE.md` and delete the
  rest.

## Deferred / low-urgency (no blockers)

- **Mode-shape plotter, MAC helper, ODS plotter** — teaching-useful,
  not urgent. Starter recipes in `dev/mode-shape-sketches.md`.
- **Large-data / streaming acquisition + big-file storage** —
  `scipy.fft` `workers=-1`, optional `pyfftw`, and a chunked/streaming
  cross-spectrum path for recordings that don't fit in RAM; the
  `.dvma` manifest already reserves a `storage` field as the versioned
  hook for an HDF5/Parquet backend. Pick up when a real "too big"
  workload appears.
- **BLAS thread-pinning for small-matrix workloads** — mostly
  user-side; scope `threadpoolctl.threadpool_limits(1)` around the
  modal-fitting loops if batch fitting ever shows jitter. Diagnosis in
  `dev/python_blas_threading_note.md`.
- **Review `multiply_by_power_of_iw` initialisation** (`analysis.py`
  ~63–91) — correct today but fragile if `channel_list` semantics
  change.
- **ML plugin as a separate repo** — keep the core dependency-light;
  the natural open-core seam.
- **Sustainability** — an institutional supporter tier (needs
  Cambridge Enterprise involvement before any payment route) and a
  **JOSS paper + citation** request. Decided direction (2026-07-03):
  the tool stays fully free and ungated.

## Parked (other repo)

- **Teaching notebooks / labsheets for the `.dvma` era** — the 4C6
  labsheets live in a separate repository; update the "you should have
  a `*.npy` file" wording there before October.

---

Everything checked off across the June–July 2026 work — the analysis
speedups, the June bug-fix batch (20 items), the `nidaqmx` migration
and hardware verification, the whole web-logger build (rounds 1–6), the
`.dvma` format, the packaging split, the docs site, and the Qt removal
— is recorded in the git history and in `dev/`. This file deliberately
no longer duplicates it.
