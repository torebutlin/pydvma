# pydvma

A Python package for dynamics and vibration measurements and analysis.


## About pydvma

This is a modular library for data-measurement and analysis in the context of dynamics and vibration, for use in student laboratory experiments as well as for research projects.

A high-level interface allows straightforward application for common use-cases and a low-level interface provides more control when needed.

The aim is for a library that is simple to use and simple to maintain. It is not a full-featured GUI, but when used in conjunction with Jupyter Notebooks it is intended to provide the best of both worlds: interactive tools for specific tasks and command line interface for customisation.


## Getting started

Install using:
```
pip install pydvma --upgrade
```

Or clone this repository and install using:

```
python setup.py install
```

To get started, within a Jupyter Notebook or Python command line:

```python
import pydvma as dvma
settings = dvma.MySettings()
osc = dvma.Oscilloscope(settings)
```

## Roadmap

At present the library has basic functionality for:

- logging data using sound cards
- computing frequency domain data
- saving and plotting data

The plan is to include the following functionality:

- logging data using National Instrument DAQs
- computing and viewing sonograms / spectrograms (time-frequency plots)
- computing transfer functions
- modal analysis tools (e.g. circle fitting)
- extend the range of hardware that can be accessed from this library


## Contributer guidelines

Contributions to this project are welcomed, keeping in mind the project aims above:

- If you find a bug, please report using GitHub's issue tracker

- For bug-fixes and refinements: please feel free to clone the repository, make edits and create a pull request with a clear description of changes made.

- If you would like to make a more significant contribution or change, then please be in contact to outline your suggestion.

Please see the documentation for details of the code structure and templates for anticipated applications.
