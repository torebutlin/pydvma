# The web logger

The **web logger** is pydvma's browser-based interface for acquiring,
monitoring, analysing and exporting dynamics-and-vibration data. It is
the recommended way to use pydvma interactively, and is replacing the
desktop [Qt logger](migration.md) (which stays available, frozen, until
the replacement is complete).

It is **one interface that runs in three modes**, so the same tool
covers no-install analysis at home, soundcard measurements from any
laptop, and full NI acquisition on a lab PC.

## The three modes

| Mode | Where it runs | Data source | Install |
| ---- | ------------- | ----------- | ------- |
| **Pages app** | [`torebutlin.github.io/pydvma/app/`](https://torebutlin.github.io/pydvma/app/) | Analysis of saved files + **soundcard** capture via the browser's Web Audio API | **None** |
| **Local bridge** | your machine, via `pydvma-serve` | Real hardware — **soundcard or NI-DAQ** — driven by a local Python process | `pip install "pydvma[serve]"` (`[ni]` for NI) |
| **JupyterLite** | [`torebutlin.github.io/pydvma/lite/`](https://torebutlin.github.io/pydvma/lite/) | `import pydvma` in a notebook, running under pyodide | **None** |

All three share **one maths engine**: pydvma's analysis core (FFT, TF,
windowing, modal fitting) runs unchanged — in a pyodide web worker in
the browser, or in the `pydvma serve` process for the bridge — so
results are identical everywhere and never reimplemented in JavaScript.

### 1. Pages app — no install

The published app at
**[`torebutlin.github.io/pydvma/app/`](https://torebutlin.github.io/pydvma/app/)**
needs nothing installed. Open it in a browser and you can:

- **Load a saved file** (`.dvma`, legacy `.npy`, or `.mat`) and work
  through the full analysis and modal-fitting workflow; and
- **Capture live from a soundcard** using the browser's Web Audio API —
  a real measurement path, not just a demo (soundcards are widely used
  as low-cost DAQs).

Files never leave your machine — the analysis runs locally in your
browser. This is the mode to point students at for analysing lab data
at home.

!!! note "Browser (Web Audio) mode caveats"
    A browser cannot reach NI-DAQ hardware, and the OS/browser can apply
    hidden audio processing. pydvma requests the browser to disable echo
    cancellation, noise suppression and auto-gain by default so a
    measurement is not silently filtered — but a browser soundcard is
    still a consumer input. For calibrated or NI measurements, use the
    local bridge. See [Acquisition and setup](acquisition.md).

### 2. Local bridge — real hardware, from the same UI

`pydvma-serve` is a small local server that serves the *same* app and
drives your real hardware from it over a WebSocket. It is how you reach
**NI-DAQ** hardware (which no browser can touch) and how you get
uncompromised **soundcard** capture on the lab PC.

```bash
pip install "pydvma[serve]"       # add [ni] for National Instruments
pydvma-serve --open               # serves the UI + bridge, opens a browser
pydvma-serve --driver nidaq --open
```

The bundled UI is embedded in the installed wheel — no Node.js, no repo
checkout, no build step. The app auto-detects it was opened through the
bridge and switches live acquisition on. See
[Installation](../getting-started/installation.md#running-the-browser-app-locally-pydvma-serve)
and [NI hardware over the bridge](ni-hardware.md).

### 3. JupyterLite — `import pydvma` in the browser

For scripted analysis with no install, the
**[JupyterLite site](https://torebutlin.github.io/pydvma/lite/)** runs a
real pyodide Python kernel in your browser with pydvma pre-bundled. Drag
a `.dvma` or `.npy` file into its file browser, then
`dvma.load_data(...)` and use the full [Python API](../user-guide/analysis.md).
This is the notebook-shaped counterpart to the point-and-click app.

## The workflow (stages)

The app is organised as a set of **stages** you move through, with a
persistent **tray** of your datasets and a docked **mini-monitor** on
every stage:

1. **[Setup](acquisition.md)** — choose the device, sample rate,
   channels and duration (plus NI options when bridged).
2. **[Acquire](acquisition.md)** — record, with optional pretrigger and
   output stimulus.
3. **[Live](live-monitoring.md)** — a full oscilloscope: time, live FFT
   or Welch PSD, and level meters.
4. **[Time](analysis.md)** / **[Frequency](analysis.md)** /
   **[TF](analysis.md)** / **[Sonogram](analysis.md)** — the analysis
   views, with resolution and averaging controls.
5. **[Fit](modal-fitting.md)** — SDOF modal fitting with Refine and
   per-mode editing.
6. **[Export](export.md)** — save `.dvma`, export `.mat` / CSV / figures.

Per-channel **[calibration and units](calibration.md)** apply throughout,
and everything saves to the shared **[`.dvma` format](dvma-format.md)**.

## Roadmap

A few surfaces are **in flight** and not yet shipped — mentioned here so
you know they are coming, not so you look for them today:

- a **dark theme**;
- a **continuous-wavelet (CWT)** sonogram method alongside STFT; and
- refined axis navigation for special plot contexts (a Nyquist
  frequency-band brush, split Bode axes).

This page and the guides describe only what currently ships.
