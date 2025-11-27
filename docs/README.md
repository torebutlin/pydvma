# Documentation

This directory contains the source files for the pydvma documentation.

## Building the Documentation Locally

### Install Dependencies

```bash
pip install -r requirements-docs.txt
```

### Build and Serve

```bash
# Serve locally with auto-reload
mkdocs serve

# Build static site
mkdocs build
```

The documentation will be available at `http://127.0.0.1:8000`

## Documentation Structure

- `getting-started/`: Installation and quick start guides
- `user-guide/`: Comprehensive usage guides
- `api/`: API reference documentation
- `examples/`: Example code and tutorials

## Contributing to Documentation

When contributing documentation:

1. Follow the existing structure and style
2. Use clear, concise language
3. Include code examples where appropriate
4. Test code examples to ensure they work
5. Build locally to check formatting

## Deployment

Documentation is automatically deployed to GitHub Pages when changes are pushed to the master/main branch via GitHub Actions.
