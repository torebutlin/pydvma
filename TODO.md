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
- [x] **Fix bare `except:` clauses** — done. All 18 bare `except:` sites (post-PyDAQmx cleanup) replaced with specific tuples per call site: hardware/driver paths catch `(AttributeError, TypeError, IndexError, OSError, RuntimeError)` as appropriate; matplotlib axis-limit paths catch `(ValueError, IndexError, TypeError)`; matplotlib legend-visibility paths catch `(AttributeError, NameError)` (legend is None before first data). Removed one dead block in `options.py` (`eval('int'+str(nbits))` — the name was never in scope so the try always failed and `settings.format` was never read).
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
- [x] **Audit trigger & logging logic across hardware paths** — done. Confirmed the trigger/pretrigger state machine is byte-for-byte identical between `Recorder` (soundcard) and `Recorder_NI_nidaqmx` (NI); documented it in the `Recorder` class docstring with a cross-reference from `Recorder_NI_nidaqmx`. Documented the pretrigger positioning invariant (first above-threshold sample lands at exactly index `pretrig_samples` in the returned buffer) on `log_data`, and added `tests/test_acquisition_hardware.py::test_pretrigger_positioning` to enforce it on every device. Tightened the `MySettings` construction guard (`pretrig_samples > chunk_size` now raises `ValueError` with a helpful message, not a bare `Exception`) and added a matching defence-in-depth guard in `log_data` for post-construction mutation. Remaining divergence: data units (soundcard = ±1 normalised float32; NI = raw volts) — folds into the next item.
- [x] **Evaluate driver choice for NI hardware** — nidaqmx chosen; PyDAQmx removed after one clean hardware session across USB-6003, USB-6212, and cDAQ.
- [x] **Remove PyDAQmx path** — done. `Recorder_NI_PyDAQmx`, `setup_output_NI_pydaqmx`, the PyDAQmx import, and the `ni_backend` setting are all gone. `Recorder_NI` is kept as an alias for `Recorder_NI_nidaqmx` for one release to soften external imports.
- [x] **Turn off -1…+1 input scaling** — done. `log_data` now returns voltages on both paths and `log_data(output=...)` / `signal_generator(amplitude=...)` take voltages. Soundcard gains a `VmaxSC` (and `output_VmaxSC`) calibration field, default 1.0 so uncalibrated users see identical numeric behaviour; NI uses existing `VmaxNI` / `output_VmaxNI`. Oscilloscope and level-bar displays still show ±1 normalised (divide by `settings.input_vmax()` at plot time) so stacked multi-channel views are unchanged. Clipping warning now checks against `0.95 * input_vmax()`. Breaking change for NI users: `signal_generator(amplitude=X)` now means X volts, not X × full-scale.
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
