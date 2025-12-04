# pydvma

A Python package for dynamics and vibration measurements and analysis.

[![Documentation](https://img.shields.io/badge/docs-online-blue)](https://torebutlin.github.io/pydvma/)
[![PyPI version](https://img.shields.io/pypi/v/pydvma)](https://pypi.org/project/pydvma/)

## About

pydvma is a modular library for data measurement and analysis in the context of dynamics and vibration, developed at Cambridge University Engineering Department. It's designed for use in student laboratory experiments and research projects.

**Key features:**

- Data acquisition via soundcards or National Instruments DAQs
- Pre-trigger recording for impulse response measurements
- FFT, transfer functions, and spectrograms
- Modal analysis tools (mode-fitting, damping estimation)
- Interactive GUI with oscilloscope view
- Export to MATLAB and CSV

## Quick Start

```bash
pip install pydvma
```

```python
import pydvma as dvma

%matplotlib qt
settings = dvma.MySettings()
logger = dvma.Logger(settings)
```

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

## License

BSD 3-Clause License - see [LICENSE](LICENSE) for details.
