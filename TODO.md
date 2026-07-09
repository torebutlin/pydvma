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

## Current backlog — web logger follow-ups

Flagged during the round-5/6 hands-on rounds (round-7, 2026-07-09,
worked through Tore's first lab-testing feedback batch — see
`dev/2026-07-09-round7-feedback.md` for the nine items + dispositions);
pick up alongside further feedback:

- **Round-7 leftovers (small):**
    - ~~Legend default corner~~ — DONE in round 7b: defaults `se` now
      (Tore's call).
    - Sono `y lin|log` + `colour dB|lin` toggles stayed in the toolbar
      bar for one-click access — fold into the popover if Tore still
      finds the bar busy.
    - LOCAL fit lines only exist right after a full Fit (the engine
      returns empty local slices on recon/refine/mute recomputes — the
      same lifetime the old pink overlay had). Return local slices from
      those ops if the toggle should survive a mute.
    - ~~Damping panel export~~ — DONE in round 7c: every chart saves as
      its own PNG (same delivery + restyle contract as Save Figure);
      the band table saves CSV.
- ~~Exported figures never include the legend~~ — DONE in round 7d:
  when the legend is toggled visible the export gains an equivalent SVG
  legend at its on-screen position (off lines excluded; columns wrap
  like the card; restyled by the same white/transparent/dark contract).
  Coherence was verified to already follow its toggle; both are
  e2e-guarded. Remaining by design: Nyquist's brush strip stays out of
  the export (a navigation control, not part of the figure).

- **CSD phase** — the glue must return the complex `Pxy` so the CSD
  pair view can show phase (currently magnitude only).
- **Browser pretrigger threshold control** — expose the trigger
  threshold in the browser Acquire UI (the bridge already has it;
  browser uses a fixed 0.05).
- ~~**Log-y heat rendering for the CWT sonogram**~~ — DONE
  (2026-07-09). The sono plot now has a toolbar **y — lin | log**
  frequency-axis switch; the heat painter maps each pixel row through
  the chosen scale to the nearest source bin (value→pixel, not
  bin-index→pixel), so it renders both the STFT's uniform grid and the
  CWT's non-uniform grid, and the CWT display now passes its **native
  log grid** (`uniform_freq=False` in `calc_sono`) — no more display
  resample, full low-frequency detail on log-y. Ships alongside a heat
  **colour — dB | lin** toolbar switch (dB uses the dynamic-range span;
  lin normalises 0→peak, disabling the dynamic-range box). Both persist
  per-view in the `.dvma` UI state.
- **CSD pair auto-enable on a hidden channel** — selecting a CSD pair
  should re-enable a channel that is currently hidden.
- **Orphan-fit browser e2e** — Playwright cover for the round-6
  orphan-TF fit crash (task_c158292c; was running in its own session
  in the `claude/determined-haslett-6448df` worktree — check whether
  it finished and merge or redo).
- **PWA manifest** — installability (manifest first; offline caching
  later, and only wired to deploy hashes — a stale service worker
  serving an old build is the failure mode to design against).
- **Narrow-band CWT damping memory optimisation** — a prototype was
  reverted because the `10·median/max` peak-detection heuristic
  misbehaves on narrow bands. Round-7 made the threshold a real
  user-controllable parameter (interactive panel), which removes the
  heuristic-dependence blocker — the narrow-band memory optimisation
  can be revisited on its own now.
- **Dark-mode contrast verdicts (Tore)** — deliberately shipped as-is
  and awaiting his call: the green Save Dataset button is white-on-
  green ≈2.7:1 and solid-indigo buttons ≈3.6:1 in dark. Bump if they
  bother him in use.

## Old-logger (V2.9a) feature review list (round-7f survey)

The recovered MATLAB source of the original JW/Tore logger was surveyed
on 2026-07-09 (Tore's OneDrive, "…Pen Drive History IV/Data logger
V2.9a"; full inventory in `dev/2026-07-09-round7-feedback.md`). Worth
considering, in rough priority:

1. **Grid / roving-hammer TF logging** (`gridlog*.m`) — measurement
   grids with next-point prompting and per-point re-log; the
   acquisition side that feeds **mode shapes** (ties into the parked
   mode-shape plotter thread).
2. **Legacy modal-parameter file import** — the old logger saved
   `md_param` (n×4: f, Q, |A|, arg A) `.mat` files; a ~30-line importer
   maps them onto `ModalData`. Valuable if archived `_param.mat` files
   still matter.
3. **"Add/edit a mode by hand" reconstruction authoring** (`reconpar`
   family) — type f, Q, amplitude-in-dB to add or tweak a mode without
   refitting; a nice manual authoring loop on top of the fits.
4. **Compensate time delay** — multiply a channel by `exp(-i·2πf·τ)`
   (vibrometer / instrumentation phase cleanup). Tiny and useful.
5. **Digital filtering from fitted modes** — per-mode filter
   coefficients to isolate one mode's time-domain contribution.
6. **RFP (rational-fraction-polynomial) fitting** — an alternative
   fitter family; useful cross-check for overlapping modes.
7. **Auto-identify TF measurement type** (round-7f wish, not in the old
   logger either — it used a hand-set `ipower` flag, as pydvma uses
   the Fit card's TF type): infer disp/vel/acc from the fitted-phase
   deviation (the new ⚠ flag's data) and suggest the type that
   minimises it. Natural extension of the phase-significance flag.

Covered already: measurement-type exponent (Fit card's TF type =
`ipower`), (iω)^p display transform, sweep logging, impulse cleaning
(`hammerclean`), decay fits. Low value (research-specific): cepstrum
sonogram, Signal Wizard export, bowed-string/musical-acoustics extras.

## Current backlog — hands-on & hardware

- **Lab-testing period (Tore, days/weeks)** — real structures, real
  measurements; expect feedback-driven fix rounds, not feature waves.
  Newest surface to exercise: shared-pole fitting, Best-match / x(iω)
  scaling group, `/config` prefill, sonogram single-targeting, brush
  v2, dark mode. `data/examples/` has the two real regression files
  (see its README); `dev/bridge_hw_check.py` is the reusable headless
  NI harness to run after any acquisition-path change.
- **IEPE auto-detect via bias-voltage probe** — enable 2 mA
  excitation and read the DC bias before AC coupling to classify what
  is connected (~24 V open / 8–14 V IEPE sensor / ~0 V low-Z) so
  `iepe_excit_current_A='auto'` can configure each 9234 channel.
  Sensitivity still has to be entered manually.

## Release & sustainability admin (Tore's threads)

v2.0.0 is SHIPPED (PyPI + `v2.0.0` tag + GitHub release with
artifacts, 2026-07-08). Remaining admin, no deadlines:

- **Zenodo DOI** — enable the GitHub–Zenodo integration (archives
  future releases automatically) or manually upload the v2.0.0 sdist
  to mint a DOI for this release; then fill the commented `doi:` slot
  in `CITATION.cff` and update the "DOI on the way" note on
  `docs/about/support.md`.
- **Cambridge Enterprise conversation** — required before any payment
  route for the institutional-supporter tier; until then the support
  page's contact-email route stands. When a route exists, add it to
  the support page (and optionally `.github/FUNDING.yml`, which today
  only links the Sponsor button to that page — no payment links).
- **JOSS paper** — Tore is authoring it personally; the draft +
  submission checklist moved OUT of the repo to
  `~/Library/CloudStorage/OneDrive-UniversityofCambridge/Work
  Research - onedrive/Work Research/Projects/2026_pydvma_paper/paper`
  (ORCID already applied). Outstanding: Zenodo DOI, word-count check,
  submit at joss.theoj.org.
- **Release artifacts note** — `dist/` (gitignored) holds the two
  2.0.0 artifacts; pre-2.0 local builds were moved to a temporary
  scratchpad and are recoverable from PyPI if ever needed.

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
- **Sustainability** — decided 2026-07-03 (tool stays fully free and
  ungated) and EXECUTED 2026-07-08: CITATION.cff, the support page,
  FUNDING.yml link, JOSS draft. What remains is admin — see "Release
  & sustainability admin" above.

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
