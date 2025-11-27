# Documentation Setup Summary

This document summarizes the MkDocs documentation structure that has been created for the pydvma project.

## 🎯 Key Feature: Live API Documentation with mkdocstrings

**The documentation automatically pulls from your source code docstrings!**

When you update docstrings in `pydvma/*.py`, the API documentation updates automatically. No need to manually maintain API reference pages - mkdocstrings handles it all.

See [MKDOCSTRINGS_INTEGRATION.md](MKDOCSTRINGS_INTEGRATION.md) for details.

## Files Created

### Configuration Files

1. **mkdocs.yml** - Main MkDocs configuration
   - Material theme with dark/light mode toggle
   - Navigation structure
   - Plugins: search, mkdocstrings for API docs
   - Markdown extensions for code highlighting, admonitions, math

2. **requirements-docs.txt** - Documentation dependencies
   - mkdocs
   - mkdocs-material
   - mkdocstrings[python]
   - pymdown-extensions

3. **.github/workflows/docs.yml** - GitHub Actions workflow
   - Automatically deploys docs to GitHub Pages on push to master/main
   - Builds docs for pull request preview

4. **DOCUMENTATION.md** - Complete guide for documentation maintenance

### Documentation Pages (docs/)

#### Home & Meta
- **index.md** - Home page with project overview
- **contributing.md** - Contribution guidelines
- **license.md** - License information
- **README.md** - Documentation directory guide

#### Getting Started
- **getting-started/installation.md** - Installation instructions
- **getting-started/quickstart.md** - Quick start guide
- **getting-started/basic-usage.md** - Basic concepts and usage

#### User Guide
- **user-guide/acquisition.md** - Data acquisition guide
- **user-guide/analysis.md** - Data analysis guide
- **user-guide/modal-analysis.md** - Modal analysis guide with damping from sonogram
- **user-guide/plotting.md** - Plotting and visualization
- **user-guide/import-export.md** - Import/export guide

#### API Reference (Auto-generated with mkdocstrings)
- **api/analysis.md** - Analysis module API (pulls from source docstrings)
- **api/acquisition.md** - Acquisition module API (auto-generated)
- **api/datastructure.md** - Data structures API (auto-generated)
- **api/plotting.md** - Plotting module API (auto-generated)
- **api/modal.md** - Modal analysis module API (auto-generated)
- **api/file.md** - File operations module API (auto-generated)
- **api/gui.md** - GUI module API (auto-generated)

!!! note "These pages auto-update when source code docstrings change"

#### Examples
- **examples/basic.md** - Basic usage examples
- **examples/advanced.md** - Advanced examples

#### Contributing
- **contributing.md** - Contribution guidelines
- **contributing-docstrings.md** - Comprehensive docstring style guide

#### Supporting Files
- **docs/javascripts/mathjax.js** - MathJax configuration for equations
- **MKDOCSTRINGS_INTEGRATION.md** - Details on mkdocstrings setup

## Next Steps

### 1. Install Documentation Dependencies

```bash
pip install -r requirements-docs.txt
```

### 2. Test Locally

```bash
mkdocs serve
```

Open http://127.0.0.1:8000 to preview the documentation.

### 3. Enable GitHub Pages

To enable automatic deployment:

1. Go to your GitHub repository settings
2. Navigate to "Settings" > "Pages"
3. Under "Source", select "Deploy from a branch"
4. Select the `gh-pages` branch
5. Click "Save"

### 4. Push to GitHub

```bash
git add .
git commit -m "Add MkDocs documentation structure"
git push origin master
```

The GitHub Actions workflow will automatically build and deploy the documentation.

### 5. Access Documentation

After the first deployment, documentation will be available at:
**https://torebutlin.github.io/pydvma**

## Documentation Features

### Material Theme
- Modern, responsive design
- Dark/light mode toggle
- Search functionality
- Navigation tabs and sections
- Mobile-friendly

### Code Examples
- Syntax highlighting for Python code
- Copy button for code blocks
- Inline code annotations

### API Documentation
- Auto-generated from docstrings using mkdocstrings
- Links to source code
- Proper type hints display

### Markdown Extensions
- Admonitions (notes, warnings, tips)
- Tabbed content
- Mathematical equations (MathJax)
- Task lists

## Updating Documentation

### Adding New Pages

1. Create a new `.md` file in the appropriate `docs/` subdirectory
2. Add the page to `mkdocs.yml` under the `nav:` section
3. Write content using Markdown
4. Test locally with `mkdocs serve`
5. Commit and push

### Editing Existing Pages

1. Edit the `.md` file directly
2. Changes will auto-reload if running `mkdocs serve`
3. Commit and push when satisfied

### API Documentation

API reference pages use mkdocstrings to automatically extract documentation from docstrings in the Python source code. To update:

1. Edit docstrings in the source code (e.g., `pydvma/analysis.py`)
2. Documentation will automatically reflect the changes
3. No need to manually update API reference pages

## Maintenance

### Regular Updates

- Keep examples up-to-date with API changes
- Update user guides when adding features
- Add new examples for new functionality
- Keep installation instructions current

### Testing

Before major releases:
1. Build docs locally: `mkdocs build --strict`
2. Check for broken links
3. Verify code examples work
4. Review for clarity and completeness

## Troubleshooting

### Build Failures

If the GitHub Actions workflow fails:
1. Check the Actions tab on GitHub for error messages
2. Build locally to reproduce: `mkdocs build --strict`
3. Fix issues and push again

### Missing Dependencies

If mkdocstrings can't find modules:
- Ensure the package is importable
- Check Python path settings
- Verify docstring format (numpy style)

## Resources

- [MkDocs Documentation](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [mkdocstrings](https://mkdocstrings.github.io/)
- [Python Markdown Extensions](https://facelessuser.github.io/pymdown-extensions/)

## Summary

This documentation setup provides:
- ✅ Professional, modern documentation site
- ✅ Automatic deployment via GitHub Actions
- ✅ Auto-generated API documentation
- ✅ Comprehensive user guides and examples
- ✅ Search functionality
- ✅ Mobile-friendly responsive design
- ✅ Easy to maintain and update

The documentation is now ready to use and will be automatically deployed when you push to GitHub!
