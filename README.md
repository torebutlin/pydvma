# pydvma

[![Documentation](https://img.shields.io/badge/docs-online-blue)](https://torebutlin.github.io/pydvma/)
[![PyPI version](https://img.shields.io/pypi/v/pydvma)](https://pypi.org/project/pydvma/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21888383.svg)](https://doi.org/10.5281/zenodo.21888383)

**pydvma** measures and analyses dynamics and vibration data: impulse
(hammer) tests, transfer functions, spectra, sonograms and modal fits,
recorded with a soundcard or with National Instruments DAQ hardware. It
is developed at the University of Cambridge Department of Engineering
for student laboratories and research.

It has a point-and-click **web logger** that runs in your browser, and a
**Python interface** (`import pydvma as dvma`) for scripting. The two
work together: `dvma.launch()` opens the web logger from a Jupyter
notebook and hands every capture back to Python.

## Getting started

| I want to… | Use | Install |
| ---------- | --- | ------- |
| Analyse a saved file, or measure with my computer's soundcard | the [browser app](https://torebutlin.github.io/pydvma/app/) | nothing |
| Measure with lab hardware (an audio interface or NI-DAQ) | `pydvma-serve --open` | `pip install "pydvma[full]"` |
| Measure in the browser **and** analyse in a Jupyter notebook | `session = dvma.launch(settings)` | `pip install "pydvma[full]"` |
| Script acquisition and analysis in Python | `import pydvma as dvma` | `pip install "pydvma[full]"` |

The [Quick Start](https://torebutlin.github.io/pydvma/getting-started/quickstart/)
takes each of these in a few steps.

## Documentation

**[torebutlin.github.io/pydvma](https://torebutlin.github.io/pydvma/)**:
installation, the quick start, a guide to every stage of the web logger,
the Python interface, and the API reference.

## Contributing

Bug reports and pull requests are welcome via
[GitHub Issues](https://github.com/torebutlin/pydvma/issues); for larger
changes, please get in touch first. See the
[Contributing guide](https://torebutlin.github.io/pydvma/contributing/).

## Citing and supporting pydvma

pydvma is free and open for everyone. If it supports your teaching or
research, please **cite it**: GitHub's "Cite this repository" button
reads [`CITATION.cff`](https://github.com/torebutlin/pydvma/blob/master/CITATION.cff), and every release is archived on
[Zenodo](https://doi.org/10.5281/zenodo.21888383). To support continued
development, or to tell us how you use pydvma, email
**tb267@cam.ac.uk**. More on the
[Support & citation page](https://torebutlin.github.io/pydvma/about/support/).

## License

BSD 3-Clause License. See [LICENSE](https://github.com/torebutlin/pydvma/blob/master/LICENSE).
