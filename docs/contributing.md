# Contributing to pydvma

Contributions to this project are welcomed! This page provides guidelines for contributing.

## Project Goals

Keep in mind the project aims:

- Simple to use
- Simple to maintain
- Modular architecture
- Work well with Jupyter notebooks
- Suitable for teaching and research

## Reporting Issues

If you find a bug:

1. Check if it's already reported in [GitHub Issues](https://github.com/torebutlin/pydvma/issues)
2. If not, create a new issue with:
   - Clear description of the problem
   - Steps to reproduce
   - Expected vs actual behavior
   - Your environment (OS, Python version, pydvma version)

## Contributing Code

### Bug Fixes and Refinements

For bug fixes and small improvements:

1. Fork the repository
2. Create a branch for your changes
3. Make your changes with clear commit messages
4. Test your changes
5. Create a pull request with a clear description

### Significant Contributions

For larger changes or new features:

1. Open an issue to discuss your proposal first
2. Wait for feedback before starting work
3. Follow the same process as above once approved

## Development Setup

```bash
# Clone repository
git clone https://github.com/torebutlin/pydvma.git
cd pydvma

# Install in development mode
pip install -e .

# Install development dependencies
pip install pytest sphinx mkdocs mkdocs-material mkdocstrings[python]
```

## Code Style

- Follow PEP 8 guidelines
- Use meaningful variable names
- Add docstrings for new functions
- Comment complex logic
- Keep functions focused and modular

## Testing

Test your changes:

```python
# Test basic functionality
import pydvma as dvma

settings = dvma.MySettings()
# ... test your changes
```

## Documentation

Update documentation when adding features:

- Add docstrings to new functions
- Update relevant user guide pages
- Add examples if appropriate

## Pull Request Guidelines

A good pull request:

- Has a clear title and description
- Explains what changed and why
- References related issues
- Includes tests if applicable
- Updates documentation if needed
- Keeps changes focused on one topic

## Questions?

If you have questions about contributing, open an issue or contact the maintainers.

## License

By contributing, you agree that your contributions will be licensed under the BSD 3-Clause License.
