# pydvma

A Python package for dynamics and vibration measurements and analysis.


## About pydvma

This is a modular library for data measurement and analysis in the context of dynamics and vibration, for use in student laboratory experiments as well as for research projects, developed at Cambridge University Engineering Department.

A high-level interface allows straightforward application for common use-cases and a low-level interface provides more control when needed.

The aim is for a library that is simple to use and simple to maintain. It is not a full-featured GUI, but when used in conjunction with Jupyter Notebooks it is intended to provide the best of both worlds: interactive tools for common tasks and a command line interface for customisation.


## Getting started

### Installation

The logger is recommended for use with Python 3.10.

```
pip install pydvma
```

If you would like soundcard acquisition then also install sounddevice:
```
pip install sounddevice
```

Or clone this repository and install using:
```
python setup.py install
```

Alternatively you can use the environment yml file provided:
```
conda env -name logger create -f logger.yml
conda activate logger
```

### Running the logger

To get started, open the file:
```
pydvma_template.ipynb
```

or within a Jupyter Notebook or Python console:
```python
%gui qt
import pydvma as dvma
settings = dvma.MySettings()
osc = dvma.Oscilloscope(settings)
logger = dvma.Logger(settings)
```

## Roadmap

At present the library has basic functionality for:

- logging data using soundcards or National Instrument DAQs (requires NiDAQmx to be installed from NI, windows only)
- logging with pre-trigger for impulse response measurements
- logging with pc generated output (soundcard and NIDAQ)
- computing frequency domain data
- computing transfer function data
- computing sonograms/spectrograms
- basic modal analysis tools (mode-fitting)
- saving and plotting data
- export to Matlab
- interactive tools for standard acquisition and analysis
- oscilloscope view of input signals

The plan is to include the following functionality:

- wider support for import/export
- more advanced modal analysis tools (e.g. global fitting)
- extend the range of hardware that can be accessed from this library


## Contributer guidelines

Contributions to this project are welcomed, keeping in mind the project aims above:

- If you find a bug, please report using GitHub's issue tracker

- For bug-fixes and refinements: please feel free to clone the repository, make edits and create a pull request with a clear description of changes made.

- If you would like to make a more significant contribution or change, then please be in contact to outline your suggestion.

Please see the documentation for details of the code structure and templates for anticipated applications.
<!-- pip install git+https://github.com/torebutlin/pydvma.git -->
<!-- pip install git+https://github.com/js2597/pydvma.git -->