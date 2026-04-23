# pydvma — TODO / Backlog

Backlog of items to review, fix, add or investigate. Grouped by topic below; see "Recommended sequencing" for the agreed order of work.

## Recommended sequencing

Ordering is by dependency and hardware availability, not by priority alone. Mac = soundcard only; NI hardware (cDAQ, DAQ) requires a Windows or Linux machine because the NI-DAQmx driver does not run on macOS.

### Phase A — Mac-only, foundation (start here)

1. **Structural pre-review (light, time-boxed, ~1 day)** — quick pass over the package before deeper work. Looking for: dead code (e.g. is `gui_tk.py` still needed?), glaring bugs, obvious structural issues that would affect test design or the speedup, copy-pasted patterns that should be helpers. Not a deep review. Outcome: a handful of high-value fixes/deletions made directly, plus notes fed into this `TODO.md` for the final pass in Phase D. Stop as soon as you catch yourself wanting to redesign something — that belongs in Phase D.
   - **First pass complete (branch `pre-review`).** Removed three dead files (`pydvma/gui_tk.py`, `pydvma/gui_tk_old.py`, `pydvma/develop_sonogram_damping function.py`) and an orphan commented import in `__init__.py`. Normalised `== None` / `!= None` to `is None` / `is not None` across 8 files (33 occurrences). Further findings from the pass have been added to the sections below (bare `except:` clauses, `streams.py` singletons, centralised hardware imports, `multiply_by_power_of_iw` initialisation).
2. **Minimal pytest scaffolding** — just enough to add "golden" regression tests for CSD / TF / PSD outputs on synthetic signals from `testdata.py`. Full test-suite expansion comes later.
3. **TF / PSD / CSD speedup** in `calculate_cross_spectrum_matrix` — protected by the golden tests from step 2.
4. **Rolling code review + rolling docs audit** — during steps 2–3, capture any issues noticed and fix the corresponding `docs/` pages for files you touch. Avoid a big up-front review.
5. **nidaqmx prep (desk work on Mac)** — read the `nidaqmx-python` API, sketch the shape of a migrated `Recorder_NI`, and build a mocked `streams.py` test harness that doesn't require real hardware. The goal is to arrive at the Windows machine with a ready-to-drop-in plan.

### Phase B — Mac-only, GUI & analysis (after Phase A)

Do in this order:

6. **GUI framework evaluation** — qtpy + PyQt5 today vs. PyQt6 / PySide6 / alternative. Pivotal choice, done after the speedup work has settled and before further GUI work. Produce a short decision record; don't migrate yet unless trivial.
7. **Plotting robustness & logic** — may fold into a backend migration if (6) recommends one.
8. **Legend relabelling.**
9. **GUI calibration flow.**
10. **Improved import / export.**

### Phase C — Windows or Linux with NI hardware (intermittent access)

Treat these as one coherent package, done together in each hardware session because they share hardware risk and setup cost:

11. **nidaqmx migration of `Recorder_NI`** — drop in the plan from step 5.
12. **NI cDAQ support** — naturally fits nidaqmx's task-based API.
13. **Trigger & logging audit** across soundcard (`Recorder`) and NI paths.
14. **Turn off ±1 scaling for the NI path** — use `VmaxNI`. (Soundcard side of this can be done on Mac in Phase B if wanted, but is easier to do with NI side together for consistency.)

Because Windows access is intermittent, design each hardware session to be pauseable: small, well-specified tasks with tests runnable on Mac via mocks between sessions.

### Phase D — Deferred / low-urgency (any time, no blockers)

- **Mode-shape plotter** — useful for teaching, not urgent.
- **CWT time-frequency analysis.**
- **Full test-suite expansion** beyond `analysis.py` (i.e. `modal.py`, `file.py`, `datastructure.py`, mocked `streams.py`).
- **Final formal code review pass** — once the big refactors have landed and the dust has settled.
- **ML plugin as a separate repo** — isolated, can happen any time.

---

## Housekeeping & review

- [ ] **General code review** — full pass over the package for clarity, dead code, duplication, error handling, and consistency.
- [ ] **Audit documentation accuracy** — the current `docs/` were Claude-generated and appear to contain invented/added content. Cross-check every page in `docs/` against the real behaviour in `pydvma/`. Don't assume `docs/` is correct when reading unfamiliar parts of the code.
- [ ] **Set up a test suite** — no `tests/` directory exists today. Target `pytest`, covering at least: `analysis.py` (FFT, CSD, TF on known signals from `testdata.py`), `modal.py` (fits on synthetic modes), `datastructure.py` (calibration, list ops), `file.py` (round-trip save/load, CSV, MATLAB). Decide how to mock/skip the hardware-dependent paths (`streams.py`).
- [ ] **Fix bare `except:` clauses** — 21 instances across `streams.py` (5), `gui.py` (10), `options.py` (3), `plotting.py` (2), and `analysis.py` (1). Bare `except:` catches `KeyboardInterrupt`, `SystemExit`, and unexpected driver errors, masking real issues. Each site needs judgement about which exceptions to catch — hardware imports want `(ImportError, NotImplementedError)`; data handling often wants `(TypeError, ValueError, IndexError)`. Deferred to after Phase A step 2 (pytest scaffolding) so changes to error-handling behaviour are covered by tests.
- [ ] **Further import-time and import-structure cleanup** — quick wins already landed (`import pydvma` dropped from ~2.5 s to ~1.2 s on a Mac by deferring `seaborn`, `matplotlib.pyplot`, `streams` in `options.py`, and removing dead `pyqtgraph`/`gui` imports). The remaining ~1 s is the GUI stack: `__init__.py:1` eagerly does `from .gui import Logger, Oscilloscope`, which pulls in qtpy, pyqtgraph, matplotlib backends, and cascades through `plotting`/`datastructure`. CLI and script users never touch the GUI but still pay this cost. Candidates for the next pass:
    - Make `Logger` and `Oscilloscope` lazy via a module-level `__getattr__` in `pydvma/__init__.py` (Python 3.7+). Accessing `pydvma.Logger` still works; GUI is only loaded on first access.
    - Replace `from pkg_resources import resource_filename` in `gui.py` with `importlib.resources` (`pkg_resources` is deprecated and slow).
    - Audit each module's top-of-file imports for unused symbols and for heavy imports that are used in only one function. Other inter-module `from . import ...` lines should be checked — the current graph has several cycles (e.g. `datastructure` ↔ `analysis`, `streams` ↔ `acquisition`, and others) that Python handles but which slow startup and make dependency reasoning harder.
    - Consider splitting the package so `pydvma.core` (data + analysis + file I/O, no GUI) can be imported without any Qt / matplotlib cost. Natural fit alongside the GUI backend evaluation in Phase B.

## Analysis features

- [ ] **Faster TF / PSD / CSD** — `calculate_cross_spectrum_matrix` (`pydvma/analysis.py`) loops `scipy.signal.csd` over every channel pair. Investigate a vectorised version (compute all FFTs once, build the CSD matrix from outer products of segment FFTs, average, apply window correction). Benchmark vs. current implementation.
- [ ] **CWT / wavelet time-frequency analysis** — currently only `calculate_sonogram` (STFT-based spectrogram) exists. Add continuous wavelet transform for non-stationary signals; decide on library (e.g. `pywt`) and whether to add a `WaveletData`/`WaveletDataList` pair.
- [ ] **Simple mode-shape plotter** — combine output of `modal_fit_all_channels` with per-channel position coordinates to draw mode shapes (1D line of accelerometers, 2D grid, etc.). No mode-shape code exists today.
- [ ] **Review `multiply_by_power_of_iw` initialisation** — `analysis.py` lines 63–91. Uses `hasattr(data, 'iw_power_counter')` plus a zero-array initialisation with single-element assignment; correct under current usage but fragile if `channel_list` semantics change. Revisit when writing unit tests for this function in Phase A step 2.

## Acquisition, hardware & signal handling

- [x] **Add NI cDAQ (compactDAQ) support** — nidaqmx-backed path added; chassis is enumerated as a single "device" whose channels span its slotted modules.
- [ ] **Audit trigger & logging logic across hardware paths** — verify trigger, pre-trigger buffer, and stop conditions behave the same for soundcard (`Recorder`) and NI (`Recorder_NI_nidaqmx`). Document actual behaviour.
- [x] **Evaluate driver choice for NI hardware** — nidaqmx chosen; PyDAQmx removed after one clean hardware session across USB-6003, USB-6212, and cDAQ.
- [x] **Remove PyDAQmx path** — done. `Recorder_NI_PyDAQmx`, `setup_output_NI_pydaqmx`, the PyDAQmx import, and the `ni_backend` setting are all gone. `Recorder_NI` is kept as an alias for `Recorder_NI_nidaqmx` for one release to soften external imports.
- [ ] **Turn off -1…+1 input scaling** — soundcard input is normalised to float32 [-1, +1]. Change so that input is returned in volts (or physical units once calibration applied), and make use of `settings.VmaxNI` (and any equivalent soundcard value) to scale correctly.
- [ ] **Easier / GUI-based calibration handling** — calibration factors exist per channel (`set_calibration_factor` etc.) but the GUI workflow for capturing and applying them is awkward. Design a cleaner flow (known-input calibration, sensitivity entry, save/load calibration sets).
- [ ] **Better control of output signals** — review `signal_generator` and the GUI output frame: expose amplitude, offset, timing, ramp, sweep parameters more cleanly; preview; save/reload signal definitions.
- [ ] **Refactor module-level singletons in `streams.py`** — three module-level globals (`REC`, `REC_SC`, `REC_NI`) manage recorder instances; `start_stream` calls `REC_NI.__init__(settings)` directly on an existing object, which is fragile and hard to mock. Redesign: pass recorder instances explicitly, or introduce a small registry. Fits naturally alongside Phase A step 5 (mocked `streams.py` test harness for NI prep).
- [ ] **Centralise optional hardware imports** — `sounddevice` and `nidaqmx` are currently imported at the top of `streams.py` (and `sounddevice` is partially duplicated in `options.py`) wrapped in `try`/`except`. Works, but scattered. A small `_hardware.py` helper that does the try-imports once and exposes boolean flags plus module handles would make mocking for tests and graceful degradation on hardware-less machines cleaner.

## GUI & plotting

- [ ] **Allow legend relabelling** — `update_legend` in `plotting.py` reads labels from the data objects; add GUI-level relabelling so plots can be customised without editing data.
- [ ] **Evaluate migration to a better GUI backend** — current stack is qtpy → PyQt5 + pyqtgraph + matplotlib-Qt5Agg. Review whether PyQt6/PySide6, or an alternative (e.g. web-based) would be a better fit long-term, given lab deployment constraints.
- [ ] **Plotting robustness & logic** — tighten the wiring between data objects → `PlotData.update()` → user interaction in `plotting.py`. Goals: plots update cleanly when data changes, no stale lines/legends, predictable behaviour when channels are added/removed or calibration changes, sensible handling of empty/NaN data, consistent real-time (pyqtgraph) vs. static (matplotlib) semantics. Partly depends on the outcome of the GUI backend evaluation — if the backend changes, this work may fold into that migration.

## I/O

- [ ] **Improved import/export** — review the existing `.npy` / MATLAB / CSV paths in `file.py`. Consider: better-documented CSV layout, MATLAB round-tripping, HDF5 / Parquet option for large datasets, consistent metadata handling.

## Plugins / separate repos

- [ ] **ML plugin as a separate repo** — keep `pydvma` dependency-light. Move/design any ML-based tooling (mode classification, signal denoising, anomaly detection, etc.) into its own repository that depends on `pydvma` rather than the other way round.
