# pydvma — TODO / Backlog

Backlog of items to review, fix, add or investigate. Loosely grouped; not in priority order.

## Housekeeping & review

- [ ] **General code review** — full pass over the package for clarity, dead code, duplication, error handling, and consistency.
- [ ] **Audit documentation accuracy** — the current `docs/` were Claude-generated and appear to contain invented/added content. Cross-check every page in `docs/` against the real behaviour in `pydvma/`. Don't assume `docs/` is correct when reading unfamiliar parts of the code.
- [ ] **Set up a test suite** — no `tests/` directory exists today. Target `pytest`, covering at least: `analysis.py` (FFT, CSD, TF on known signals from `testdata.py`), `modal.py` (fits on synthetic modes), `datastructure.py` (calibration, list ops), `file.py` (round-trip save/load, CSV, MATLAB). Decide how to mock/skip the hardware-dependent paths (`streams.py`).

## Analysis features

- [ ] **Faster TF / PSD / CSD** — `calculate_cross_spectrum_matrix` (`pydvma/analysis.py`) loops `scipy.signal.csd` over every channel pair. Investigate a vectorised version (compute all FFTs once, build the CSD matrix from outer products of segment FFTs, average, apply window correction). Benchmark vs. current implementation.
- [ ] **CWT / wavelet time-frequency analysis** — currently only `calculate_sonogram` (STFT-based spectrogram) exists. Add continuous wavelet transform for non-stationary signals; decide on library (e.g. `pywt`) and whether to add a `WaveletData`/`WaveletDataList` pair.
- [ ] **Simple mode-shape plotter** — combine output of `modal_fit_all_channels` with per-channel position coordinates to draw mode shapes (1D line of accelerometers, 2D grid, etc.). No mode-shape code exists today.

## Acquisition, hardware & signal handling

- [ ] **Add NI cDAQ (compactDAQ) support** — support connecting to cDAQ chassis modules alongside the existing NI DAQ path. Check where the current `Recorder_NI` would need to change.
- [ ] **Audit trigger & logging logic across hardware paths** — verify trigger, pre-trigger buffer, and stop conditions behave the same for soundcard (`Recorder`) and NI (`Recorder_NI`). Document actual behaviour.
- [ ] **Evaluate driver choice for NI hardware** — currently `PyDAQmx`. Assess migrating to `nidaqmx` (the NI-maintained Python wrapper) or another modern alternative. Compare API, feature coverage (cDAQ, synchronisation, analog output), maintenance status.
- [ ] **Turn off -1…+1 input scaling** — soundcard input is normalised to float32 [-1, +1]. Change so that input is returned in volts (or physical units once calibration applied), and make use of `settings.VmaxNI` (and any equivalent soundcard value) to scale correctly.
- [ ] **Easier / GUI-based calibration handling** — calibration factors exist per channel (`set_calibration_factor` etc.) but the GUI workflow for capturing and applying them is awkward. Design a cleaner flow (known-input calibration, sensitivity entry, save/load calibration sets).
- [ ] **Better control of output signals** — review `signal_generator` and the GUI output frame: expose amplitude, offset, timing, ramp, sweep parameters more cleanly; preview; save/reload signal definitions.

## GUI & plotting

- [ ] **Allow legend relabelling** — `update_legend` in `plotting.py` reads labels from the data objects; add GUI-level relabelling so plots can be customised without editing data.
- [ ] **Evaluate migration to a better GUI backend** — current stack is qtpy → PyQt5 + pyqtgraph + matplotlib-Qt5Agg. Review whether PyQt6/PySide6, or an alternative (e.g. web-based) would be a better fit long-term, given lab deployment constraints.

## I/O

- [ ] **Improved import/export** — review the existing `.npy` / MATLAB / CSV paths in `file.py`. Consider: better-documented CSV layout, MATLAB round-tripping, HDF5 / Parquet option for large datasets, consistent metadata handling.

## Plugins / separate repos

- [ ] **ML plugin as a separate repo** — keep `pydvma` dependency-light. Move/design any ML-based tooling (mode classification, signal denoising, anomaly detection, etc.) into its own repository that depends on `pydvma` rather than the other way round.
