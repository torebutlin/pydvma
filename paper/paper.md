---
title: 'pydvma: browser-based dynamics and vibration measurement and analysis for teaching and research'
tags:
  - Python
  - vibration
  - dynamics
  - modal analysis
  - data acquisition
  - signal processing
  - engineering education
authors:
  - name: Tore Butlin
    orcid: 0000-0000-0000-0000  # PLACEHOLDER — replace with Tore's real ORCID before submission
    affiliation: 1
affiliations:
  - name: Department of Engineering, University of Cambridge, United Kingdom
    index: 1
date: 8 July 2026
bibliography: paper.bib
---

<!--
DRAFT for review — do NOT submit as-is.
Outstanding before submission: replace the placeholder ORCID above;
archive a tagged release on Zenodo and add its DOI; confirm the word
count (JOSS target ~250–1000 words of body text). See paper/README.md.
-->

# Summary

`pydvma` (Python Dynamics and Vibration Measurement and Analysis) is an
open-source package for acquiring, visualising, analysing and fitting
vibration data. It combines a data-acquisition front end with a
signal-processing and modal-analysis core, and presents them through a
single browser-based interface that runs in three modes: a zero-install
web app for analysing saved files and capturing from a soundcard; a
local Python bridge (`pydvma-serve`) that drives laboratory hardware
— soundcards or National Instruments (NI) DAQ devices — from the same
app; and a JupyterLite notebook for scripted analysis with no install.
All three share one analysis engine — the same Python code runs either
in a Pyodide [@pyodide] WebAssembly worker in the browser or in the
bridge process — so results are identical everywhere and never
reimplemented in JavaScript. A scriptable Python API underpins the same
functionality for research workflows. `pydvma` is built on NumPy
[@harris2020numpy], SciPy [@virtanen2020scipy] and Matplotlib
[@hunter2007matplotlib], and stores data in a safe, self-describing
`.dvma` container that older `.npy` files still load.

# Statement of need

Measuring and interpreting vibration — recording time signals,
estimating frequency spectra and transfer functions, and extracting
modal parameters such as natural frequencies and damping ratios — is a
core activity in both undergraduate mechanics teaching and research in
structural dynamics [@ewins2000modal]. In practice this is often served
by commercial data-acquisition and modal-analysis suites that are
expensive, tied to specific hardware, and installed only on dedicated
laboratory machines. That model is a poor fit for teaching at scale and
for reproducible research: students cannot analyse their data at home,
and analysis pipelines are locked inside proprietary tools.

`pydvma` addresses this gap with a free, open, and hardware-agnostic
alternative. Its distinguishing feature is the combination of a
**no-install browser interface** with an optional **local bridge to
real laboratory hardware**: a student can capture data on a lab PC
connected to an NI DAQ, save a `.dvma` file, and later open the exact
same interface at home — with Python running inside the browser — to
finish the analysis, with no software to install and no data leaving
their machine. Because the acquisition path also supports ordinary
soundcards, low-cost measurements are possible on any laptop. The tool
was developed for laboratory teaching at the University of Cambridge
Department of Engineering and is equally suited to research use where a
scriptable, inspectable, and citable analysis core matters more than a
closed commercial workflow.

# Functionality

`pydvma` provides an end-to-end workflow organised as a sequence of
stages with a persistent tray of datasets:

- **Acquisition** from soundcards (via the browser Web Audio API or the
  bridge) and NI-DAQ devices (via the bridge), with configurable sample
  rate, channels and duration, hardware-accurate **pre-trigger**
  recording for impulse-response measurements, and **generated output
  stimulus** (including swept sine) for driven transfer-function tests.
- A live **oscilloscope** showing the time signal, a live FFT or Welch
  power spectral density, and per-channel level meters.
- **Analysis** views computing FFTs, power and cross-spectral densities,
  transfer functions with coherence, and time–frequency spectrograms via
  both the short-time Fourier transform and a dependency-free continuous
  wavelet (Morlet) transform, with user control over frequency
  resolution and averaging.
- **Modal fitting** of single-degree-of-freedom resonances, including
  joint fitting of shared poles across multiple measurements, iterative
  refinement, and per-mode editing [@ewins2000modal].
- Per-channel **calibration and units** applied consistently throughout,
  and **export** to the native `.dvma` format, MATLAB and CSV files, and
  publication-ready figures.

The analysis core is usable directly from Python
(`import pydvma as dvma`) for scripted and reproducible research, and is
covered by an automated test suite. Documentation, including a full web
logger guide and API reference, is published online.

# Acknowledgements

We thank colleagues and students in the University of Cambridge
Department of Engineering for feedback that shaped the tool through its
use in laboratory teaching. <!-- TODO (Tore): add named contributors,
and any grant or funding acknowledgements, before submission. -->

# References
