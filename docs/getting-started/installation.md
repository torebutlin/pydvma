# Installation

## Requirements

- Python 3.10 or later (Python 3.13 recommended)
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
| `pip install "pydvma[full]"` | Everything: GUI plus both acquisition backends. Recommended for lab use. |

The rest of this page uses `pydvma[full]` throughout, but swap in
whichever extra matches what you need.

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
