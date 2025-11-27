# Documentation Quick Reference

Quick links to documentation-related files.

## 📚 Main Documentation Files

- **[DOCS_SETUP_SUMMARY.md](DOCS_SETUP_SUMMARY.md)** - Complete overview of what was created
- **[MKDOCSTRINGS_INTEGRATION.md](MKDOCSTRINGS_INTEGRATION.md)** - How mkdocstrings auto-generates API docs
- **[DOCUMENTATION.md](DOCUMENTATION.md)** - Full guide for maintaining documentation
- **[.mkdocs_quickref.md](.mkdocs_quickref.md)** - Quick reference for common commands

## 🚀 Quick Start

### Build Locally

```bash
# Install dependencies
pip install -r requirements-docs.txt

# Serve with auto-reload
mkdocs serve
```

Open http://127.0.0.1:8000

### Deploy to GitHub Pages

1. **Enable GitHub Pages**:
   - Go to repository Settings → Pages
   - Source: "Deploy from a branch"
   - Branch: `gh-pages`

2. **Push to GitHub**:
   ```bash
   git add .
   git commit -m "Add MkDocs documentation"
   git push origin master
   ```

3. **Access**: https://torebutlin.github.io/pydvma

## 🎯 Key Features

### ✨ Automatic API Documentation

**Your docstrings are the documentation!**

Update docstrings in `pydvma/*.py` → API docs update automatically.

Example:
```python
# pydvma/analysis.py
def calculate_fft(time_data, window='hann'):
    """Calculate FFT of time series.

    Args:
        time_data: Input time series
        window: Window function name

    Returns:
        Frequency domain data
    """
```

This automatically appears in the API reference! See [MKDOCSTRINGS_INTEGRATION.md](MKDOCSTRINGS_INTEGRATION.md).

### 📝 Docstring Style Guide

New to writing docstrings? See **[docs/contributing-docstrings.md](docs/contributing-docstrings.md)** for:
- Format examples
- Best practices
- What to document

## 📁 Documentation Structure

```
pydvma/
├── mkdocs.yml                    # Main configuration
├── requirements-docs.txt         # Doc dependencies
├── docs/                         # All documentation
│   ├── index.md                 # Home page
│   ├── getting-started/         # Installation & setup
│   ├── user-guide/              # Usage guides
│   ├── api/                     # API reference (auto-generated!)
│   ├── examples/                # Code examples
│   └── contributing-docstrings.md
└── .github/workflows/docs.yml   # Auto-deployment
```

## 🔄 Workflow

### For Code Contributors

1. Write code with docstrings
2. Push to GitHub
3. Documentation builds automatically
4. Live at https://torebutlin.github.io/pydvma

### For Documentation Contributors

1. Edit files in `docs/`
2. Preview: `mkdocs serve`
3. Push to GitHub
4. Deploys automatically

## 🛠️ Common Tasks

### Add a New Page

1. Create `docs/section/newpage.md`
2. Add to `mkdocs.yml` navigation
3. Write content in Markdown

### Update API Docs

**Just update the docstrings in the source code!** mkdocstrings handles the rest.

### Add New Function to API Docs

Edit the relevant `docs/api/*.md` file:

```markdown
::: pydvma.module.new_function
    options:
      show_source: false
      heading_level: 3
```

## 📖 Documentation Resources

- [MkDocs](https://www.mkdocs.org/)
- [Material Theme](https://squidfunk.github.io/mkdocs-material/)
- [mkdocstrings](https://mkdocstrings.github.io/)
- [Markdown Guide](https://www.markdownguide.org/)

## 🆘 Need Help?

- **Build issues**: Check [DOCUMENTATION.md](DOCUMENTATION.md#troubleshooting)
- **mkdocstrings issues**: See [MKDOCSTRINGS_INTEGRATION.md](MKDOCSTRINGS_INTEGRATION.md#troubleshooting)
- **General questions**: Open a GitHub issue

## 📊 Status

- ✅ Documentation infrastructure complete
- ✅ All modules configured for mkdocstrings
- ✅ Auto-deployment workflow ready
- ✅ User guides written
- ✅ Examples provided
- ✅ Docstring style guide available

**Ready to deploy!**
