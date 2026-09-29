# pydvma

**pydvma** measures and analyses dynamics and vibration data: impulse
(hammer) tests, transfer functions, spectra, sonograms and modal fits,
recorded with a soundcard or with National Instruments DAQ hardware. It
is developed at the Cambridge University Engineering Department for
student laboratories and research.

It has two front-ends over one analysis engine:

- the **web logger**, a point-and-click app in your browser for
  acquiring, monitoring, analysing, fitting and exporting data; and
- the **Python interface**, `import pydvma as dvma` in a notebook or
  script, for anything you want to automate or customise.

The two work together: `dvma.launch()` opens the web logger from a
Jupyter notebook and hands every capture back to Python.

## Which way in?

| I want to… | Use | Install |
| ---------- | --- | ------- |
| Analyse a saved file, or measure with my computer's soundcard | the [browser app](https://torebutlin.github.io/pydvma/app/) | nothing |
| Measure with lab hardware (an audio interface or NI-DAQ) | `pydvma-serve --open` | `pip install "pydvma[full]"` |
| Measure in the browser **and** analyse in a Jupyter notebook | `session = dvma.launch(settings)` | `pip install "pydvma[full]"` |
| Script acquisition and analysis in Python | `import pydvma as dvma` | `pip install "pydvma[full]"`, or nothing in [JupyterLite](https://torebutlin.github.io/pydvma/lite/) |

The **[Quick Start](getting-started/quickstart.md)** takes each of these
in a few steps, and **[Installation](getting-started/installation.md)**
covers the install options.

## What it does

- **Acquisition** from soundcards, audio interfaces and NI-DAQ hardware,
  with a pretrigger for impulse tests and a generated output (sweeps,
  noise) for transfer-function measurements
- **Live monitoring**: oscilloscope, live spectrum and level meters
- **Analysis**: FFT, power spectrum and PSD, cross-spectra, transfer
  functions with coherence, sonograms (STFT and wavelet) and damping
  estimates
- **Modal fitting**, including shared poles across several measurements,
  and best-linear-approximation separation of noise from nonlinear
  distortion
- **Calibration and units** per channel
- **Saving and export**: the `.dvma` format, MATLAB, CSV and figures
  (PNG/PDF)

## Finding your way around

- **[Getting Started](getting-started/installation.md)**: installation,
  the quick start, and Python basics
- **[Web Logger](web-logger/index.md)**: the browser app, stage by stage
- **[Python Interface](user-guide/acquisition.md)**: acquisition, analysis
  and modal fitting from code
- **[API Reference](api/analysis.md)**: every public function and class
- **[Examples](examples/basic.md)**: complete worked measurements

Coming from the old desktop Qt logger? It was removed in 2.0.0; see
[From the Qt logger](web-logger/migration.md).

## Contributing, citing, licence

Bug reports and pull requests are welcome; see
[Contributing](contributing.md). If pydvma supports your teaching or
research, please [cite it](about/support.md). pydvma is released under
the [BSD 3-Clause License](license.md).
