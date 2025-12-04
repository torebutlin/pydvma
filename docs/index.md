# pydvma

A Python package for dynamics and vibration measurements and analysis.

## About pydvma

This is a modular library for data measurement and analysis in the context of dynamics and vibration, for use in student laboratory experiments as well as for research projects, developed at Cambridge University Engineering Department.

A high-level interface allows straightforward application for common use-cases and a low-level interface provides more control when needed.

The aim is for a library that is simple to use and simple to maintain. It is not a full-featured GUI, but when used in conjunction with Jupyter Notebooks it is intended to provide the best of both worlds: interactive tools for common tasks and a command line interface for customisation.

## Features

At present the library has basic functionality for:

- Logging data using soundcards or National Instrument DAQs
- Logging with pre-trigger for impulse response measurements
- Logging with PC generated output (soundcard and NIDAQ)
- Computing frequency domain data (FFT)
- Computing transfer function data
- Computing sonograms/spectrograms
- Basic modal analysis tools (mode-fitting, damping estimation)
- Saving and plotting data
- Export to Matlab and CSV
- Interactive tools for standard acquisition and analysis
- Oscilloscope view of input signals

## Quick Start

### Installation

```bash
pip install pydvma
```

### Basic Usage

```python
import pydvma as dvma
import matplotlib

%matplotlib widget
settings = dvma.MySettings()
logger = dvma.Logger(settings)
```

For more detailed instructions, see the [Getting Started](getting-started/installation.md) guide.

## Documentation Overview

- **[Getting Started](getting-started/installation.md)**: Installation and setup instructions
- **[User Guide](user-guide/acquisition.md)**: Comprehensive guides for common tasks
- **[API Reference](api/analysis.md)**: Detailed API documentation
- **[Examples](examples/basic.md)**: Practical examples and tutorials

## Contributing

Contributions to this project are welcomed, keeping in mind the project aims above:

- If you find a bug, please report using GitHub's issue tracker
- For bug-fixes and refinements: please feel free to clone the repository, make edits and create a pull request with a clear description of changes made
- If you would like to make a more significant contribution or change, then please be in contact to outline your suggestion

See the [Contributing](contributing.md) page for more details.

## License

This project is licensed under the BSD 3-Clause License - see the [License](license.md) page for details.
