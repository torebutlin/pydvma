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
pip install sounddevice pydvma
```

### Option B: Installation in a Dedicated Environment

Creating a separate environment keeps pydvma and its dependencies isolated from other projects:

```bash
# Create a new environment
conda create --name pydvma-env python=3.13

# Activate the environment
conda activate pydvma-env

# Install dependencies and pydvma
conda install numpy scipy jupyter matplotlib pyqtgraph ipympl ipywidgets jupyterlab
pip install sounddevice pydvma
```

!!! tip "Activating your environment"
    Each time you open a new Anaconda Prompt, you'll need to activate your environment with `conda activate pydvma-env` before using pydvma.

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

For National Instruments hardware (Windows only):

1. **Download and install NI-DAQmx driver** (version 17.6 recommended):

   **[Download NI-DAQmx](https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html)**

2. **Install the Python bindings**:

   ```bash
   pip install pydaqmx
   ```

!!! note "Windows Only"
    National Instruments DAQ support is only available on Windows. Soundcard acquisition works on all platforms.

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

If you encounter Qt-related errors, try installing PyQt5:

```bash
pip install pyqt5
```

**Matplotlib Backend Issues**

If plots don't display correctly in Jupyter, add this to the first cell of your notebook:

```python
%matplotlib qt
```

**Soundcard Not Detected**

Ensure sounddevice is installed and your audio device is properly connected:

```bash
pip install sounddevice
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
