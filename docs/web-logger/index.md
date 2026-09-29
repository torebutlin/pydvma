# The Web Logger

The **web logger** is pydvma's point-and-click app for acquiring,
monitoring, analysing, fitting and exporting dynamics and vibration
data. It runs in your browser, in one of two ways:

| | **In the browser** | **Served locally** |
| - | ------------------ | ------------------ |
| Open it | [torebutlin.github.io/pydvma/app/](https://torebutlin.github.io/pydvma/app/) | `pydvma-serve --open`, or `dvma.launch()` from Python |
| Install | nothing | `pip install "pydvma[full]"` |
| Records from | your computer's soundcard, through the browser | soundcards, audio interfaces and NI-DAQ hardware, directly |
| Analysis runs | in the browser | in Python on your machine: faster, and no browser memory limit |
| Your session | kept in the browser's storage | also held by the server, so it survives closing the tab |

The app itself is identical either way, and so is the maths: the same
pydvma analysis code runs in both, so results match exactly. Files never
leave your machine. [Running Locally](running-locally.md) covers
`pydvma-serve` and `dvma.launch` in full.

!!! note "Measuring through the browser"
    A browser can't reach NI hardware, and operating systems and
    browsers may process a soundcard signal. pydvma asks the browser to
    turn off echo cancellation, noise suppression and automatic gain, but
    for calibrated or NI measurements, run the app locally. See
    [Acquisition & Setup](acquisition.md).

For scripted analysis with nothing installed there is also
**[JupyterLite](https://torebutlin.github.io/pydvma/lite/)**: a Python
notebook in your browser with pydvma ready to import. Upload a `.dvma`
or `.npy` file into its file browser, then `dvma.load_data(filename=...)`
and use the [Python interface](../user-guide/analysis.md).

## The stages

The app is a row of **stages** you move through. Your datasets sit in the
**tray** alongside, and a small live monitor is docked on every stage.

1. **[Setup](acquisition.md)**: choose the device, sample rate, channels
   and duration (plus NI options for NI hardware).
2. **[Acquire](acquisition.md)**: record, with an optional pretrigger and
   output signal.
3. **[Live](live-monitoring.md)**: a full oscilloscope with live spectrum
   and level meters.
4. **[Time](analysis.md)**, **[Frequency](analysis.md)** and
   **[TF](analysis.md)**: the analysis views, with resolution and
   averaging controls.
5. **[Nonlin](nonlin.md)**: separates measurement noise from nonlinear
   distortion (a best linear approximation measurement).
6. **[Sonogram](analysis.md)**: time-frequency view and damping
   estimates.
7. **[Fit](modal-fitting.md)**: modal fitting, with per-mode editing.
8. **[Export](export.md)**: save `.dvma`, export MATLAB, CSV and figures.

Setup, Acquire, Live and Nonlin are enabled only when a live input is
available, and Fit once there is a transfer function to fit.
[Calibration and units](calibration.md) apply throughout, and
everything saves to the [`.dvma` format](dvma-format.md).

Across the top, the header has **Load Data**, **Save Figure** and
**Save Dataset**, and a light/dark theme toggle (the sun/moon button),
which follows your operating system until you choose.
