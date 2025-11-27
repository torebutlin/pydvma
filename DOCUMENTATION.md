# Documentation Guide

This project uses [MkDocs](https://www.mkdocs.org/) with the [Material theme](https://squidfunk.github.io/mkdocs-material/) to generate documentation.

## Quick Start

### View Documentation Online

Once deployed, the documentation will be available at:
`https://torebutlin.github.io/pydvma`

### Build Locally

1. **Install dependencies:**
   ```bash
   pip install -r requirements-docs.txt
   ```

2. **Serve documentation locally:**
   ```bash
   mkdocs serve
   ```
   Then open http://127.0.0.1:8000 in your browser.

3. **Build static site:**
   ```bash
   mkdocs build
   ```
   Output will be in the `site/` directory.

## Documentation Structure

```
docs/
├── index.md                 # Home page
├── getting-started/         # Getting started guides
│   ├── installation.md
│   ├── quickstart.md
│   └── basic-usage.md
├── user-guide/             # User guides
│   ├── acquisition.md
│   ├── analysis.md
│   ├── modal-analysis.md
│   ├── plotting.md
│   └── import-export.md
├── api/                    # API reference
│   ├── analysis.md
│   ├── acquisition.md
│   ├── datastructure.md
│   ├── plotting.md
│   ├── modal.md
│   ├── file.md
│   └── gui.md
├── examples/              # Examples
│   ├── basic.md
│   └── advanced.md
├── contributing.md        # Contributing guidelines
└── license.md            # License information
```

## Automatic Deployment

Documentation is automatically deployed to GitHub Pages when:
- Changes are pushed to the `master` or `main` branch
- The GitHub Actions workflow (`.github/workflows/docs.yml`) runs successfully

### First-Time Setup for GitHub Pages

1. Go to your repository settings on GitHub
2. Navigate to "Pages" in the left sidebar
3. Under "Source", select "Deploy from a branch"
4. Select the `gh-pages` branch
5. Click "Save"

The documentation will be deployed automatically on the next push to master/main.

## Editing Documentation

### Markdown Files

All documentation is written in Markdown. Files are located in the `docs/` directory.

### Adding New Pages

1. Create a new `.md` file in the appropriate directory
2. Add the page to `mkdocs.yml` under the `nav:` section
3. Use the existing pages as templates

### Code Blocks

Use fenced code blocks with language specification:

```python
import pydvma as dvma
settings = dvma.MySettings()
```

### Admonitions

Use admonitions for notes, warnings, etc.:

```markdown
!!! note
    This is a note.

!!! warning
    This is a warning.

!!! tip
    This is a tip.
```

### API Documentation

API reference pages use mkdocstrings to automatically generate documentation from docstrings:

```markdown
::: pydvma.analysis
    options:
      show_source: true
      heading_level: 2
```

### Mathematical Equations

Use LaTeX syntax for equations:

- Inline: `\( E = mc^2 \)`
- Display: `\[ E = mc^2 \]`

## Configuration

The main configuration file is `mkdocs.yml` in the repository root. Key sections:

- `site_name`: Site title
- `theme`: Theme configuration
- `plugins`: Extensions and plugins
- `nav`: Navigation structure
- `markdown_extensions`: Markdown features

## Troubleshooting

### Documentation doesn't build

Check that all required dependencies are installed:
```bash
pip install -r requirements-docs.txt
```

### Changes don't appear

1. Stop the local server (Ctrl+C)
2. Clear the cache: `rm -rf site/`
3. Restart: `mkdocs serve`

### GitHub Pages not updating

1. Check the Actions tab on GitHub for workflow status
2. Ensure GitHub Pages is configured correctly in repository settings
3. Verify the workflow has write permissions

## Resources

- [MkDocs Documentation](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [mkdocstrings Documentation](https://mkdocstrings.github.io/)
- [Python Markdown Extensions](https://facelessuser.github.io/pymdown-extensions/)

## Support

For issues with the documentation:
1. Check existing documentation in this guide
2. Review MkDocs documentation
3. Open an issue on GitHub
