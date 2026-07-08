# pydvma

A Python package for dynamics and vibration measurements and analysis.

## About pydvma

This is a modular library for data measurement and analysis in the context of dynamics and vibration, for use in student laboratory experiments as well as for research projects, developed at Cambridge University Engineering Department.

A high-level interface allows straightforward application for common use-cases and a low-level interface provides more control when needed.

The aim is for a library that is simple to use and simple to maintain. It is not a full-featured GUI, but when used in conjunction with Jupyter Notebooks it is intended to provide the best of both worlds: interactive tools for common tasks and a command line interface for customisation.

## Features

At present the library has basic functionality for:

- Logging data using soundcards or National Instruments DAQs
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

## Two interfaces, one analysis core

pydvma has two front-ends over the same analysis engine:

- the **[web logger](web-logger/index.md)** — a browser-based interface
  for acquiring, monitoring, analysing, fitting and exporting data. This
  is the **recommended** way to use pydvma interactively, and it runs in
  three modes (below); and
- the **Python interface** — `import pydvma as dvma` in a notebook or
  script, for full customisation and scripted workflows.

A desktop **Qt logger** GUI is also still available, but it is now
**legacy** (bug-fixes only) as the web logger replaces it — see
[From the Qt logger](web-logger/migration.md).

## The web logger — no install for two of the three modes

| Mode | Open it | What you get |
| ---- | ------- | ------------ |
| **Pages app** | [torebutlin.github.io/pydvma/app/](https://torebutlin.github.io/pydvma/app/) | Full analysis of saved files **plus soundcard capture** — nothing to install |
| **Local bridge** | `pip install "pydvma[serve]"`, then `pydvma-serve --open` | The same app driving **real hardware** (soundcard or **NI-DAQ**) on your machine |
| **JupyterLite** | [torebutlin.github.io/pydvma/lite/](https://torebutlin.github.io/pydvma/lite/) | `import pydvma` in a browser notebook — no install |

Saved a dataset in the lab? Open the
**[Pages app](https://torebutlin.github.io/pydvma/app/)** (or the
[JupyterLite notebook](https://torebutlin.github.io/pydvma/lite/)) and
drag your `.dvma`, `.npy` or `.mat` file straight in — Python runs inside
your browser, and files never leave your machine. See
[the web logger guide](web-logger/index.md) for the full workflow.

## Quick start

### Analyse or measure in the browser — no install

Open **[torebutlin.github.io/pydvma/app/](https://torebutlin.github.io/pydvma/app/)**
and either load a saved file or capture from a soundcard. Full walkthrough:
[the web logger](web-logger/index.md).

### Drive real hardware locally

```bash
pip install "pydvma[serve]"     # add [ni] for National Instruments
pydvma-serve --open             # serves the app + bridge, opens a browser
pydvma-serve --driver nidaq --open
```

See [Installation](getting-started/installation.md) and
[NI hardware over the bridge](web-logger/ni-hardware.md).

### Script it in Python

```python
import pydvma as dvma

dataset = dvma.load_data('measurement.dvma')   # or record with log_data
freq = dvma.calculate_fft(dataset.time_data_list[0])
```

Install the Python interface with `pip install pydvma` (analysis-only
core; add `[qt,soundcard,ni]` for the desktop logger and hardware
backends). See [Installation](getting-started/installation.md) and the
[Python interface guides](user-guide/acquisition.md).

## Documentation Overview

- **[Getting Started](getting-started/installation.md)**: Installation and setup instructions
- **[Web Logger](web-logger/index.md)**: The browser-based interface — acquisition, live monitoring, analysis, modal fitting, calibration and export
- **[Python Interface](user-guide/acquisition.md)**: Scripting acquisition and analysis in notebooks
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
