# pydvma — Code Structure

Internal developer overview of the `pydvma` package. Complements (not replaces) the user-facing documentation under `docs/`.

> **Note:** The `docs/` folder was partly AI-generated and has not yet been fully verified against the code. Treat `docs/` as secondary to the source itself until the audit (see `TODO.md`) is done.

## Purpose

`pydvma` is a modular Python library for dynamics and vibration measurements and analysis, developed at Cambridge University Engineering Department. It is deliberately two-faced:

- **GUI mode** — an interactive PyQt + pyqtgraph application aimed at student lab use. Common tasks (log, view oscilloscope, compute TFs, fit modes, export) are exposed through a single window.
- **CLI / scripting mode** — the same underlying functions are importable for researchers who want to embed acquisition and analysis in their own scripts and notebooks.

## Top-level layout

```
pydvma/
├── pydvma/                     # The package itself
│   ├── __init__.py             # Public API — re-exports ~30 names
│   ├── gui.py                  # Main PyQt Logger application (~129 KB)
│   ├── gui_tk.py               # Older tkinter variant (legacy)
│   ├── oscilloscope.py         # Real-time pyqtgraph oscilloscope widget
│   ├── acquisition.py          # High-level log_data / output_signal / signal_generator
│   ├── streams.py              # Recorder (soundcard) + Recorder_NI (PyDAQmx) classes
│   ├── analysis.py             # FFT, CSD, TF, sonogram, damping
│   ├── modal.py                # Modal parameter fitting (scipy least-squares)
│   ├── datastructure.py        # DataSet + TimeData/FreqData/TfData/... classes
│   ├── plotting.py             # Matplotlib PlotData class, legend/picking helpers
│   ├── file.py                 # Load/save .npy, MATLAB import/export, CSV, figure save
│   ├── options.py              # MySettings / Output_Signal_Settings
│   └── testdata.py             # Synthetic signal generators for demos & testing
├── docs/                       # MkDocs (Material theme) — see note above
├── .github/workflows/docs.yml  # Builds & deploys docs to gh-pages
├── setup.py                    # Setuptools metadata (v1.0.0)
├── mkdocs.yml
├── README.md
└── LICENSE                     # BSD 3-Clause
```

No `tests/` directory exists. No console-script entry points are registered.

## Module responsibilities

### `gui.py` — the interactive application
- `Logger` (main `QMainWindow`) — tabs, toolbars, plots, signal controls.
- Supporting windows: `PreviewWindow`, `DampingFitWindow`, `KeyPressWindow`.
- Frame setup methods: `setup_frame_tools_scaling`, `setup_frame_tools_generate_output`, etc.
- Uses `qtpy` as the Qt abstraction; in practice backed by PyQt5.

### `streams.py` — hardware abstraction
- `Recorder` — sounddevice-based (cross-platform soundcards).
- `Recorder_NI` — PyDAQmx-based (National Instruments DAQ devices).
- Device discovery: `get_devices_soundcard`, `get_devices_NI`.
- Output setup: `setup_output_soundcard`, `setup_output_NI`.
- Trigger logic (pre-trigger buffer + threshold detect) lives in the `Recorder.callback()` chain.
- Input voltage range comes from `settings.VmaxNI`; output from `settings.output_VmaxNI`. Soundcard inputs are currently float32 normalised to [-1, +1].

### `acquisition.py` — high-level entry points
- `log_data(settings)` — orchestrates a recording.
- `output_signal(...)` — drives a generated signal out.
- `signal_generator(...)` — builds gaussian / uniform / swept-sine signals with ramp windows.

### `analysis.py` — signal processing
- `calculate_fft` — `numpy.fft.rfft`.
- `calculate_cross_spectrum_matrix` — Welch-based CSD via `scipy.signal.csd` in a nested channel loop (exploits Hermitian symmetry, still O(N_ch²)).
- `calculate_cross_spectra_averaged` — ensemble averaging.
- `calculate_tf`, `calculate_tf_averaged` — H1/H2-style TF from the CSD ratio.
- `calculate_sonogram` — `scipy.signal.spectrogram` in complex mode, wrapped in `SonoData`.
- `calculate_damping_from_sono` — exponential-decay fit on sonogram slices.
- `multiply_by_power_of_iw`, `clean_impulse`, `best_match`.

### `modal.py` — modal fitting
- `modal_fit_single_channel`, `modal_fit_all_channels`.
- Rational-fraction-polynomial-style model with residual terms, multiplied by `(jω)^p` to cover acceleration / velocity / displacement data (`p = 2, 1, 0`).
- `scipy.optimize.least_squares` with bounds; 3-dB bandwidth used for the initial guess (`f_3dB`).
- No mode-shape code — only per-channel modal parameters (fₙ, ζₙ, amplitude, phase).

### `datastructure.py` — data classes
- `DataSet` container plus per-domain classes: `TimeData`/`TimeDataList`, `FreqData`/`FreqDataList`, `CrossSpecData`/`CrossSpecDataList`, `TfData`/`TfDataList`, `SonoData`/`SonoDataList`, `ModalData`/`ModalDataList`, `MetaData`/`MetaDataList`.
- Per-channel calibration factors live on the list classes: `get_calibration_factors`, `set_calibration_factor`, `set_calibration_factors_all`.

### `plotting.py` — plotting
- `PlotData` — matplotlib-backed plot object with an `update()` method.
- Qt5Agg backend (`FigureCanvas`, `NavigationToolbar` from `matplotlib.backends.backend_qt5agg`).
- Legend handling (`update_legend`) supports draggable, multi-column, click-to-toggle legends, but legend labels come from the data objects — there is no in-GUI relabelling.

### `file.py` — I/O
- `load_data` / `save_data` — primary format is `.npy` (pickled `DataSet`).
- `import_from_matlab_jwlogger`, `export_to_matlab`, `export_to_matlab_jwlogger`.
- `export_to_csv`, `save_fig`.

## Dependencies (by role)

- **GUI & plotting:** `qtpy` + PyQt5, `pyqtgraph`, `matplotlib`, `seaborn`, optional `qdarktheme`.
- **Scientific:** `numpy`, `scipy`, `peakutils`.
- **Hardware:** `sounddevice` (always), `PyDAQmx` (optional, for NI).
- **Docs:** MkDocs + Material, `mkdocstrings`.

## Tests & CI

- **Tests:** none. `testdata.py` produces synthetic signals used for manual checks and demos.
- **CI:** `.github/workflows/docs.yml` builds and deploys MkDocs to GitHub Pages on pushes to master.

## How to navigate

- Want to change a GUI control or layout? → `gui.py`, plus the relevant `setup_frame_*` method.
- Want to change how data is captured? → `streams.py` (hardware) then `acquisition.py` (orchestration).
- Want to add an analysis routine? → `analysis.py` and add a matching `*Data`/`*DataList` in `datastructure.py` if new output type.
- Want to change plotting? → `plotting.py`.
- Want to change file formats? → `file.py`.
