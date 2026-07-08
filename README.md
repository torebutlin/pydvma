# pydvma

A Python package for dynamics and vibration measurements and analysis.

[![Documentation](https://img.shields.io/badge/docs-online-blue)](https://torebutlin.github.io/pydvma/)
[![PyPI version](https://img.shields.io/pypi/v/pydvma)](https://pypi.org/project/pydvma/)

## About

pydvma is a modular library for data measurement and analysis in the context of dynamics and vibration, developed at the University of Cambridge Department of Engineering. It's designed for use in student laboratory experiments and research projects.

**Key features:**

- Data acquisition via soundcards or National Instruments DAQs
- Pre-trigger recording and PC-generated output stimulus for impulse/transfer-function measurements
- FFT, transfer functions, coherence, and spectrograms (STFT and CWT)
- Modal analysis tools (mode-fitting, damping estimation)
- A browser-based **web logger** with a live oscilloscope, analysis and modal-fitting views
- Export to `.dvma`, MATLAB and CSV; theme-invariant figure export (PNG/PDF)

## The web logger — the recommended interface

The interactive interface is now the **[web logger](https://torebutlin.github.io/pydvma/web-logger/)**, which runs in three modes over one shared analysis engine:

| Mode | Open it | Install |
| ---- | ------- | ------- |
| **Pages app** — analysis of saved files + soundcard capture | [torebutlin.github.io/pydvma/app/](https://torebutlin.github.io/pydvma/app/) | none |
| **Local bridge** — the same app driving real hardware (soundcard or NI-DAQ) | `pydvma-serve --open` | `pip install "pydvma[serve]"` |
| **JupyterLite** — `import pydvma` in a browser notebook | [torebutlin.github.io/pydvma/lite/](https://torebutlin.github.io/pydvma/lite/) | none |

> The earlier desktop **Qt logger** GUI has been **removed** now that the web logger has full parity (its last version is the `qt-final` git tag).

## Quick Start

Analyse or measure in the browser with **no install** — open the
[Pages app](https://torebutlin.github.io/pydvma/app/) and drag in a
`.dvma`, `.npy` or `.mat` file, or capture from a soundcard.

To drive real hardware (soundcard or NI-DAQ) from the same app on your
own machine:

```bash
pip install "pydvma[serve]"     # add [ni] for National Instruments
pydvma-serve --open             # serves the app + bridge, opens a browser
```

To script analysis and acquisition in Python:

```python
import pydvma as dvma

dataset = dvma.load_data('measurement.dvma')   # or record with log_data
freq = dvma.calculate_fft(dataset.time_data_list[0])
```

Plain `pip install pydvma` installs the analysis-only core (data
structures, FFT/TF/modal analysis, file I/O) with no hardware
dependencies — it runs anywhere, including in-browser under pyodide.
Native data format is `.dvma` (safe, pickle-free); `.npy` files saved
by older versions still load.

## Documentation

**Full documentation: [torebutlin.github.io/pydvma](https://torebutlin.github.io/pydvma/)**

- [Installation Guide](https://torebutlin.github.io/pydvma/getting-started/installation/) - Detailed setup instructions
- [Quick Start](https://torebutlin.github.io/pydvma/getting-started/quickstart/) - Get up and running quickly
- [User Guide](https://torebutlin.github.io/pydvma/user-guide/acquisition/) - Comprehensive usage guides
- [API Reference](https://torebutlin.github.io/pydvma/api/analysis/) - Detailed API documentation

## Contributing

Contributions are welcomed:

- Report bugs via [GitHub Issues](https://github.com/torebutlin/pydvma/issues)
- Submit pull requests for bug fixes and improvements
- Contact us for significant changes or new features

See the [Contributing Guide](https://torebutlin.github.io/pydvma/contributing/) for details.

## Support & citation

pydvma is **free and open for everyone** — no features are gated. If it
supports your teaching or research, the most valuable thing you can do is
**cite it**. This repository includes a
[`CITATION.cff`](CITATION.cff) file, so GitHub's "Cite this repository"
button and most reference managers can import the citation directly.

If your institution would like to support continued development, or you
would simply like to tell us how you use pydvma, get in touch:
**tb267@cam.ac.uk**. See the
[Support & citation page](https://torebutlin.github.io/pydvma/about/support/)
for details (a DOI will follow via Zenodo once a release is archived).

## License

BSD 3-Clause License - see [LICENSE](LICENSE) for details.
