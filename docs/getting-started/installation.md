# Installation

## Requirements

The logger is recommended for use with Python 3.10 or later.

## Basic Installation

The simplest way to install pydvma is using pip:

```bash
pip install pydvma
```

## Installation from Source

To install from source, clone the repository and use setup.py:

```bash
git clone https://github.com/torebutlin/pydvma.git
cd pydvma
python setup.py install
```

## Using Anaconda

If you use Anaconda, you can create a dedicated environment with all required packages:

```bash
conda create -n py310 python=3.10
conda activate py310
conda install numpy scipy jupyter matplotlib pyqtgraph
pip install pydvma
```

## Optional Dependencies

### Soundcard Acquisition

For soundcard-based data acquisition, install sounddevice:

```bash
pip install sounddevice
```

### National Instruments Acquisition

For National Instruments DAQ devices:

1. Install the NI-DAQmx v17.6 driver from National Instruments: [Download here](https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html#288272)
2. Install pydaqmx:

```bash
pip install pydaqmx
```

!!! note "Windows Only"
    National Instruments DAQ support is currently only available on Windows.

## Verifying Installation

To verify your installation, open a Python console and try:

```python
import pydvma as dvma
print(dvma.__version__)
```

If no errors occur, pydvma is successfully installed!

## Troubleshooting

### Common Issues

**Import Error: No module named 'pydvma'**

Make sure pydvma is installed in the correct Python environment. If using virtual environments or Anaconda, ensure you've activated the correct environment.

**Qt Platform Plugin Error**

If you encounter Qt-related errors, try installing a specific Qt binding:

```bash
pip install pyqt5
```

**Matplotlib Backend Issues**

If plots don't display correctly, try setting the matplotlib backend:

```python
import matplotlib
matplotlib.use('Qt5Agg')
```

For Jupyter notebooks, use:

```python
%matplotlib qt
```

## Next Steps

Once installation is complete, proceed to the [Quick Start](quickstart.md) guide to begin using pydvma.
