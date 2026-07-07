# Installation

## Requirements

- Python 3.11 or later (Python 3.13 recommended)
- Anaconda or Miniconda (recommended for managing dependencies)

## Step 1: Install Anaconda

If you don't already have Anaconda installed, download it from:

**[Download Anaconda](https://www.anaconda.com/download)**

Follow the installer instructions for your operating system.

## Step 2: Install pydvma

### Option A: Quick Installation (Recommended)

Open the **Anaconda Prompt** (Windows) or terminal (Mac/Linux) and run:

```bash
conda install numpy scipy jupyter matplotlib pyqtgraph ipympl ipywidgets jupyterlab
pip install "pydvma[full]"
```

`pydvma[full]` pulls in the GUI (Qt/pyqtgraph) and both acquisition
backends (`sounddevice` for soundcards, `nidaqmx` for National
Instruments hardware) — everything you need for lab use. See
[Installation options](#installation-options) below if you only need
a subset.

### Option B: Installation in a Dedicated Environment

Creating a separate environment keeps pydvma and its dependencies isolated from other projects:

```bash
# Create a new environment
conda create --name pydvma-env python=3.13

# Activate the environment
conda activate pydvma-env

# Install dependencies and pydvma
conda install numpy scipy jupyter matplotlib pyqtgraph ipympl ipywidgets jupyterlab
pip install "pydvma[full]"
```

!!! tip "Activating your environment"
    Each time you open a new Anaconda Prompt, you'll need to activate your environment with `conda activate pydvma-env` before using pydvma.

## Installation options

pydvma is split into a small analysis-only core plus optional
"extras" for the GUI and each acquisition backend, so you only pull
in what you need:

| Install command | What you get |
| ---------------- | ------------- |
| `pip install pydvma` | Analysis-only core: data structures, FFT/TF/modal analysis, file I/O. No Qt, no hardware drivers — runs anywhere, including in-browser. |
| `pip install "pydvma[qt,soundcard]"` | Core + GUI (Logger/Oscilloscope, via `qtpy`/`PyQt5`/`pyqtgraph`) + soundcard acquisition (`sounddevice`). |
| `pip install "pydvma[ni]"` | Core + National Instruments acquisition backend (`nidaqmx`). Windows/Linux only — see below. |
| `pip install "pydvma[serve]"` | Core + the `pydvma-serve` bridge (`websockets` only), which serves the browser app locally and drives real hardware from it. See [Running the browser app locally](#running-the-browser-app-locally-pydvma-serve). |
| `pip install "pydvma[full]"` | Everything: GUI plus both acquisition backends and the serve bridge. Recommended for lab use. |

The rest of this page uses `pydvma[full]` throughout, but swap in
whichever extra matches what you need.

## Running the browser app locally (`pydvma-serve`)

pydvma also has a browser-based app (analysis plus live acquisition) that
you can run straight from a `pip` install — no Node.js, no repo checkout,
no build step. The built UI is bundled inside the wheel and served by a
tiny local bridge that also drives your real hardware.

```bash
pip install "pydvma[serve]"      # or pydvma[full]
pydvma-serve --open              # serves the app and opens your browser
```

`pydvma-serve` listens on `http://127.0.0.1:8760` (loopback only). Pick a
data source with `--driver`:

```bash
pydvma-serve --driver mock       # demo signal generator, no hardware
pydvma-serve --driver soundcard  # needs pydvma[soundcard]
pydvma-serve --driver nidaq      # needs pydvma[ni] + NI-DAQmx (Win/Linux)
```

Useful flags: `--port` (change the port), `--ui-dir` (serve a UI directory
you built yourself instead of the bundled one), `--open` (open a browser
on start). Run `pydvma-serve --help` for the full list.

!!! note "Which UI is served"
    `pydvma-serve` serves, in order of preference: an explicit `--ui-dir`;
    the freshly built `webui/dist` if you are running from a source
    checkout; otherwise the UI bundled in the installed wheel. If none is
    available it shows a short help page with the WebSocket bridge still
    live at `/ws`.

!!! info "Maintainers: bundling the UI into the wheel"
    The bundled UI lives at `pydvma/_webui` and is a build artefact (not
    committed). To produce a release wheel that contains it:

    ```bash
    cd webui && npm ci && npm run vendor   # fetch pyodide + build engine wheels
    cd .. && python scripts/stage_webui.py # runs `npm run build`, mirrors dist -> pydvma/_webui
    python -m build --wheel                # fat wheel: contains pydvma/_webui
    ```

    The separate lean "engine" wheel that the browser loads via pyodide is
    built by `webui/scripts/build-wheels.sh` with `PYDVMA_LEAN_WHEEL=1`,
    which the in-tree build backend honours by excluding `pydvma/_webui`.
    Source distributions never contain the staged UI, so build the fat
    wheel directly from the staged tree (not from an sdist).

## Step 3: Download the Template Notebook

Download the template notebook to get started quickly:

**[Download pydvma_template.ipynb](https://raw.githubusercontent.com/torebutlin/pydvma/master/pydvma_template.ipynb)** (right-click and "Save link as...")

Save it to a folder on your computer where you want to work with your data.

## Step 4: Run Jupyter Notebook

Open the **Anaconda Prompt** and run:

```bash
jupyter notebook --notebook-dir="C:\path\to\your\folder"
```

Replace `C:\path\to\your\folder` with the path to the folder where you saved the template notebook. This will open Jupyter in your browser where you can open and run the template.

!!! tip "Quick navigation"
    Alternatively, you can simply run `jupyter notebook` and navigate to your folder using the Jupyter file browser.

## Optional: National Instruments DAQ Support

For National Instruments hardware (Windows or Linux — NI-DAQmx is not
available on macOS):

1. **Download and install the NI-DAQmx driver**:

   **[Download NI-DAQmx](https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html)**

   Use the latest version that supports your OS. The `nidaqmx` Python
   wrapper tracks NI-DAQmx ABI changes and will print a clear error
   on mismatch.

2. **Install the Python bindings** (already included if you installed
   `pydvma[full]` above; use this if you started from plain `pydvma`):

   ```bash
   pip install "pydvma[ni]"
   ```

!!! note "macOS"
    NI-DAQmx has no macOS driver, so the NI path is unavailable on
    Mac. Soundcard acquisition still works on all platforms; analysis
    functions are pure-Python and run anywhere.

## Verifying Installation

To verify your installation, open a Python console or Jupyter notebook and try:

```python
import pydvma as dvma
print("pydvma installed successfully!")
```

If no errors occur, you're ready to go!

## Troubleshooting

### Common Issues

**Import Error: No module named 'pydvma'**

Make sure pydvma is installed in the correct Python environment. If using a dedicated environment, ensure you've activated it with `conda activate pydvma-env`.

**Qt Platform Plugin Error**

If you encounter Qt-related errors, make sure the GUI extra is installed:

```bash
pip install "pydvma[qt]"
```

**Matplotlib Backend Issues**

If plots don't display correctly in Jupyter, add this to the first cell of your notebook:

```python
%matplotlib widget
```

**Soundcard Not Detected**

Ensure the soundcard extra is installed and your audio device is properly connected:

```bash
pip install "pydvma[soundcard]"
```

You can list available audio devices with:

```python
import sounddevice as sd
print(sd.query_devices())
```

## Installation from Source

For development or to get the latest changes:

```bash
git clone https://github.com/torebutlin/pydvma.git
cd pydvma
pip install -e .
```

## Next Steps

Once installation is complete, proceed to the [Quick Start](quickstart.md) guide to begin using pydvma.
