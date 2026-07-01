# pydvma web UI — design & decision record

**Date:** 2026-07-01
**Status:** Approved (design); implementation staged
**Supersedes:** TODO Phase B item 6 ("GUI framework evaluation — produce a short decision record")

## Context

pydvma has two interfaces: a Python CLI (notebook/script use, full
customisation) and a Qt GUI (`gui.py`, 3,177 lines; qtpy → PyQt5 +
pyqtgraph + matplotlib-Qt5Agg) used in undergraduate labs. Labsheets
are Jupyter notebooks that set CLI settings then launch the Logger as
a popup window; an Oscilloscope (pyqtgraph, chosen for realtime feel)
launches from the notebook or from within the GUI.

Problems driving this decision:

- The Qt GUI is hard to maintain; plotting/view-switching logic has
  persistent rough edges.
- Students who want to analyse lab data at home must install the
  logger (Python + Qt stack); many don't manage or don't try.
- The interface doesn't feel modern or slick despite working well
  functionally.

Requirements gathered:

- **CLI must be retained unchanged** — it is the customisation path
  and the labsheet driver.
- No-install browser analysis is the core student need; browser
  soundcard acquisition is genuinely useful (soundcards are used as
  DAQs, not just demos); a single unified interface is the ideal.
- Labsheet format is not fixed to Jupyter, but embedded-in-notebook
  UIs are ruled out (tried; too much scrolling). A browser tab beside
  the instructions is acceptable.
- Maintenance is transitioning to Claude-supervised development;
  frontend technology choice is free, optimising for
  AI-maintainability. Python remains the backend.
- Everything must be reversible back to the current release.

Hard constraint: **NI-DAQmx cannot run in a browser.** Lab NI
acquisition always needs a native Python process on the lab PC. The
browser *can* do soundcard acquisition natively (Web Audio /
getUserMedia) and can run the analysis stack (numpy/scipy/matplotlib
all run under pyodide).

## Decision

**Adopt a staged migration to a unified web UI (Option B), with the
Qt GUI frozen (bugfix-only) until replaced.** No PySide6/Qt6
migration — effort is not spent modernising code slated for
replacement.

One web frontend, same UI in three modes:

| Mode | Where | Data source |
|---|---|---|
| Analysis | GitHub Pages, no install | pydvma core in pyodide; load/save `.npy` locally |
| Soundcard | GitHub Pages, no install | Web Audio API |
| Lab / NI | Lab PC | local `pydvma serve` process (nidaqmx + websocket); serves the UI itself so the lab has no internet dependency |

### Alternatives considered

- **A — Modernise Qt (qtpy→PySide6) + JupyterLite for home analysis.**
  Lowest risk but keeps two interfaces forever and the Qt maintenance
  burden; the "slick modern feel" ceiling is low. Rejected as the
  destination; its JupyterLite component is kept as Stage 1 here.
- **C — marimo-centred** (labsheet becomes a reactive `.py` app that
  exports to WASM for home use). Attractive one-artifact story, but
  the realtime oscilloscope would still need a custom JS widget, and
  it couples lab infrastructure to a younger framework. Rejected.
- **D — Panel/HoloViz** (server UI + `panel convert` to pyodide).
  Mature, pure Python, but callback-style maintenance similar to Qt
  and realtime plotting below pyqtgraph standard. Rejected.

## Reversibility strategy

- Tag **`v1.4.0`** on master before any work (done 2026-07-01;
  `setup.py` and `datastructure.py` versions verified in sync).
  Rollback = checkout/revert to the tag.
- **All new work is additive**: new directories (`lite/`, `webui/`)
  and new modules (`pydvma/serve.py`, plotting-core extraction). The
  Qt path is never edited except for bugfixes. Deleting the new
  directories restores today's system.
- **Logical split, not physical.** No file moves or subpackage
  reshuffles. Saved `.npy` data pickles pydvma classes, so module
  paths like `pydvma.datastructure.DataSet` are a compatibility
  contract with every student data file ever saved. The core/GUI
  split is enforced by tests ("base install imports with zero
  Qt/sounddevice/nidaqmx"), not by directory structure.
- Work happens on master in small commits (solo-maintainer workflow;
  no branch — agreed 2026-07-01).

### Compatibility contracts (must hold at every stage)

1. `import pydvma as dvma` public API unchanged: existing labsheets
   run verbatim (`MySettings`, `Logger`, `Oscilloscope`, `log_data`,
   `load_data`, `DataSet` methods, …).
2. Files saved by ≤ 1.4.0 (pickle `.npy`) remain loadable forever
   via the legacy reader — which requires pickled class module paths
   to stay valid (hence the physical-layout freeze). New-format
   `.dvma` files (Stage 0.5) are decoupled from code layout.
3. Existing test suite (157 passed / 4 hardware-skipped) stays green.

## Stage 0 — packaging split (small)

Goal: `pip install pydvma` (base) is pure-Python, importable with no
Qt / sounddevice / nidaqmx / seaborn present. The earlier import-time
work (lazy `__getattr__`, deferred heavy imports) did most of the
surgery already.

- Replace `setup.py` with **`pyproject.toml`**. Base deps: `numpy`,
  `scipy`, `matplotlib`, `peakutils`. Extras: `pydvma[qt]` (qtpy,
  pyqt5, pyqtgraph, seaborn), `pydvma[ni]` (nidaqmx),
  `pydvma[soundcard]` (sounddevice), `pydvma[full]` (all). This also
  fixes the known packaging bug (nidaqmx hard-required; qtpy/pyqt5
  missing).
- Single-source the version (read `datastructure.VERSION` or move to
  package metadata; either way one authoritative location).
- Make the remaining eager hardware names in `pydvma/__init__.py`
  (line 26: `Recorder`, `Recorder_NI`, `start_stream`, `REC`, …)
  lazy or import-guarded so base import touches no hardware modules.
- **Import-surface regression test**: create a minimal venv with the
  base install only; assert `import pydvma` succeeds and every public
  name resolves (lazy ones resolve on access where their extra is
  present; raise a helpful ImportError naming the extra where not).

## Stage 0.5 — file format v2 (container format)

The current save format is a pickle of live Python objects
(`np.save(filename, dataset)` with `allow_pickle=True`). It is
single-language, unversioned, a code-execution risk on load, and it
couples the file format to the code layout (pickles store class
module paths). Replace it as the *default* write format; keep the
legacy reader permanently.

- **Format:** a zip container, extension **`.dvma`**, containing
  `manifest.json` plus plain `.npy` arrays saved with
  `allow_pickle=False`. The manifest carries: `format_version`,
  `pydvma_version`, a `storage` field (see below), and per-item
  entries (kind — TimeData/FreqData/TfData/…, array member paths,
  settings as a plain dict, units, calibration factors, test names,
  timestamps, ids). Exact field list is an implementation-plan
  detail; the manifest is the documented schema.
- **Reading:** `load_data` sniffs magic bytes — zip → v2 reader,
  `.npy` pickle → legacy reader. **Files saved by ≤ 1.4.0 remain
  loadable forever.**
- **Headless fix (same stage):** `load_data(path)` / file-path
  arguments work with no GUI present; the no-argument Qt file dialog
  becomes GUI-layer sugar only.
- **Large-file hook:** zip members are written with optional
  DEFLATE compression (`zipfile` handles this transparently on
  read — trivial, so implemented now). The manifest's `storage`
  field (`"npy"` today) is the versioned extension point for a
  future HDF5 or chunked backend for genuinely large captures —
  deliberately *not* implemented now; tracked in TODO (I/O section,
  existing HDF5/Parquet item).
- **Why it matters for the interfaces:** the format becomes the
  contract instead of the class layout. JS can read/write `.dvma`
  natively (jszip + a small npy parser) so the Stage 2 frontend can
  open files without waking pyodide; files are safe to share; schema
  versioning becomes real. Note the physical-layout freeze stays
  regardless — legacy pickle files reference today's class paths
  forever (or would need pickle-shim mapping if the package is ever
  reorganised) — but new data stops adding to that constraint.
- **Tests:** v2 round-trip across all data kinds; legacy 1.4.0
  reference file loads; sniffing dispatch; MATLAB/CSV export paths
  unaffected.

## Stage 1 — JupyterLite analysis site (target: ready for October)

- New `lite/` directory. Extend the existing `docs.yml` Pages
  workflow to build JupyterLite (pyodide kernel) into the published
  site at `…/pydvma/lite/`, next to the MkDocs docs. (Deployment is
  `mkdocs gh-deploy` to the `gh-pages` branch, so the JupyterLite
  build output must be added to that branch's tree alongside the
  MkDocs output — not placed under `docs/`, where MkDocs would try
  to process it.)
- CI builds the pure-Python pydvma wheel from the repo and bundles it
  so browser users get `import pydvma as dvma` with zero install.
  Remaining deps resolve in pyodide: numpy/scipy/matplotlib are
  prebuilt; peakutils is pure Python via micropip.
- Starter notebook mirroring the labsheet analysis idiom: drag `.npy`
  into the JupyterLite file browser → `dvma.load_data()` → calc
  FFT/TF → plot (`%matplotlib widget` via ipympl).
- **Plotting-core extraction** (the one refactor touching existing
  code): `plotting.py` imports qtpy at module top, so
  `DataSet.plot_tf_data()` would fail under pyodide. Extract the
  pure-matplotlib figure logic into a new module (e.g.
  `pydvma/_plot_core.py`); `plotting.py` keeps its path and public
  names and delegates. Qt-less environments get working plots;
  `PlotData` behaviour is unchanged.
- CI smoke test: under pyodide, load a checked-in reference `.npy`
  (saved by 1.4.0) and run the analysis golden path.

## Stage 2 — unified web app

Architecture fixed now; detailed design in a follow-up spec once the
gate (below) passes.

- `webui/`: **Svelte + TypeScript + Vite.** Components: `Scope`
  (canvas/WebGL realtime rendering — the pyqtgraph replacement),
  `Logger` panel (settings, log/save/load, analysis actions), and
  Plotly.js for static analysis plots.
- **One maths engine everywhere**: the browser runs pydvma core in a
  pyodide web worker for all analysis. FFT/TF/windowing is never
  reimplemented in JS.
- **Swappable data sources** behind one TS interface:
  `WebAudioSource` (browser soundcard) / `BridgeSource` (websocket to
  local `pydvma serve`) / `FileSource` (saved data — reads `.dvma`
  natively in JS; legacy pickle files via pyodide).
- `pydvma serve` (new module + `pydvma[serve]` extra): local Python
  process wrapping the existing `streams`/`acquisition` code,
  streaming chunks over websocket and serving the built UI
  statically. `MockRecorder` (already in the codebase) enables
  hardware-free bridge tests; NI verification happens in a Windows
  hardware session, last.
- Deployment: same GitHub Pages site, e.g. `…/pydvma/app/`.
- **Gate:** the first deliverable is a scope prototype (Web Audio →
  canvas at 60 fps target) to validate the realtime feel. If it
  disappoints, stop at Stage 1 + frozen Qt; sunk cost is small.

## Testing & CI summary

- Stage 0: import-surface test in minimal venv; suite stays green.
- Stage 0.5: `.dvma` round-trip across all data kinds; legacy 1.4.0
  reference file loads via sniffing reader; headless `load_data`.
- Stage 1: pyodide smoke test (reference-`.npy` load + analysis);
  Pages build in CI.
- Stage 2: Playwright end-to-end with synthesised audio; bridge unit
  tests against `MockRecorder`; scope frame-rate measurement in the
  prototype.
- Pickle-compat test (checked-in 1.4.0 reference file) runs from
  Stage 0 onward.

## Sequencing

All of Stage 0, Stage 0.5, Stage 1, and the Stage 2 scope prototype
are Mac-runnable (soundcard + pyodide). Only the NI bridge needs the
Windows machine. Qt GUI remains the lab interface until Stage 2 is
proven; nothing in Stages 0–1 changes what students see in October
except gaining the no-install analysis site.
