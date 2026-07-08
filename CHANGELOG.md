# Changelog

All notable changes to pydvma are documented here. This project
follows [semantic versioning](https://semver.org/).

## 2.0.0 — 2026-07-08

First release since the browser-based **web logger** replaced the
removed Qt desktop GUI. Because the desktop `Logger`/`Oscilloscope`
API is gone, this is a breaking change and warrants the major bump.
PyPI remains the package channel (`pip install pydvma`); GitHub Pages
serves only the hosted app and documentation.

### Breaking

- **The Qt desktop GUI has been removed.** `pydvma/gui.py` and the
  orphaned `oscilloscope.py` / `logger_tester.py` are deleted along
  with the Qt-only tests.
- **The `[qt]` extra is gone.** `pip install pydvma[qt]` now errors on
  an unknown extra — the honest signal that the desktop GUI is retired.
  Use `pip install pydvma[serve]` + `pydvma-serve` instead.
- **`dvma.Logger` and `dvma.Oscilloscope` now raise an actionable
  tombstone** on access, pointing at the web logger and the migration
  docs.
- The last version that shipped the Qt GUI is the **`qt-final`** git
  tag — revert there if the desktop logger is ever needed.

### Added — the web logger

- **Three ways to run it:**
  - **Pages app** (no install) — analysis + Web Audio soundcard
    acquisition in the browser, at
    <https://torebutlin.github.io/pydvma/app/>.
  - **`pydvma-serve` local bridge** — `pip install pydvma[serve]`
    then `pydvma-serve` serves the wheel-embedded UI and bridges to
    local hardware. Drivers: `mock`, `soundcard`, `nidaqmx`.
    NI acquisition is hardware-verified (multi-channel capture,
    sample-exact pretrigger, output stimulus sweep).
  - **JupyterLite** — the analysis core running under Pyodide.
- **Acquisition:** basic/full Setup, capability-clamped NI options
  (IEPE, terminal config, sample-rate ladders, voltage rails),
  armed pretrigger with editable sample count (browser and bridge),
  output stimulus generator (`signal_generator` parity), persistent
  mini-oscilloscope and a Live scope (FFT / Welch PSD).
- **Analysis:** FFT, PSD, cross-spectrum pair (E[X*Y]),
  transfer function + coherence, Clean Impulse; sonogram via STFT
  **and CWT** (dependency-free Morlet) with damping fits;
  unit-aware axes and live recompute.
- **Modal fitting:** Fit 1/2/3, **multi-set shared poles**
  (joint `TfDataList` fit), Reject, **Refine** (auto-revert),
  per-mode mute/delete/undo; fits render as tray cards and persist in
  `.dvma` as Python-readable `ModalData`.
- **Scaling:** **Best Match** (via calibration factors) plus a
  non-destructive **x(iω)^p display transform**; calibration dialog
  (sensitivity + units).
- **Export:** `.dvma`, MATLAB `.mat`, CSV (parity with the file API),
  and theme-invariant PNG/PDF figures.
- **UI:** hover-expand axis toolbar with undo/redo history,
  draggable Nyquist/Bode/coherence axis navigation, and a no-flash
  **dark theme** toggle.
- Legacy files continue to load (2019 pre-list pickles are
  normalised; derived kinds seed views; orphan-TF convention).

### Documentation

- A full **Web Logger** section is published on the docs site,
  including a migration guide from the retired Qt GUI:
  <https://torebutlin.github.io/pydvma/web-logger/>

## 1.5.0 and earlier

Pre-2.0.0 history (the notebook + Qt-GUI era) is not itemised here.
See the git log and the `v1.5.0`, `v1.4.0`, … release tags, and the
`qt-final` tag for the last Qt-GUI commit.
