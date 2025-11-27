# mkdocstrings Integration Summary

This document explains how mkdocstrings is integrated with pydvma documentation for automatic API documentation generation.

## What is mkdocstrings?

mkdocstrings automatically extracts documentation from Python source code docstrings and generates beautiful API reference pages. When you update docstrings in your code, the documentation website updates automatically.

## How It Works

### 1. Docstrings in Source Code

Write docstrings in your Python files:

```python
# pydvma/analysis.py
def calculate_damping_from_sono(time_data, n_chan=1, nperseg=None, start_time=None):
    '''
    Calculate damping from sonogram data.

    Args:
        time_data (<TimeData> object): time series data
        n_chan (int): channel to analyze
        nperseg (int): FFT segment length
        start_time (float): time to start analysis

    Returns:
        fn: natural frequencies (Hz)
        Qn: Q factors
        fit_data: dict with fit visualization data
    '''
    # Function implementation...
```

### 2. API Reference Pages

In the docs, use special syntax to pull in the documentation:

```markdown
# docs/api/analysis.md

## Modal Analysis

::: pydvma.analysis.calculate_damping_from_sono
    options:
      show_source: false
      heading_level: 3
```

### 3. Automatic Rendering

When the documentation builds:
- mkdocstrings reads the source code
- Extracts docstrings and type hints
- Generates formatted documentation
- Creates links and navigation

## Configuration

### mkdocs.yml Settings

```yaml
plugins:
  - mkdocstrings:
      handlers:
        python:
          paths: [pydvma]  # Where to find Python modules
          options:
            docstring_style: google  # Docstring format
            show_source: false  # Don't show source code
            show_signature_annotations: true  # Show type hints
            members_order: source  # Order as in source file
```

Key options:
- **docstring_style**: `google`, `numpy`, or `sphinx`
- **show_source**: Include full source code (set to `false` for cleaner docs)
- **members**: Which members to document (set to `true` for classes)
- **filters**: Exclude private methods with `["!^_"]`

## Current Setup

### All Modules Are Configured

All API reference pages use mkdocstrings:

- ✅ **analysis.md** - All analysis functions organized by category
- ✅ **acquisition.md** - Data acquisition functions
- ✅ **datastructure.md** - All data classes with members
- ✅ **plotting.md** - Plotting utilities
- ✅ **modal.md** - Modal analysis tools
- ✅ **file.md** - Import/export functions
- ✅ **gui.md** - Logger and window classes

### Syntax Used

**For functions:**
```markdown
::: pydvma.analysis.calculate_fft
    options:
      show_source: false
      heading_level: 3
```

**For classes:**
```markdown
::: pydvma.datastructure.TimeData
    options:
      show_source: false
      heading_level: 3
      members: true  # Include methods and attributes
```

**For entire modules:**
```markdown
::: pydvma.modal
    options:
      show_source: false
      heading_level: 3
      members: true
```

## What Gets Auto-Generated

mkdocstrings automatically creates:

- ✅ Function signatures with parameter names and types
- ✅ Parameter descriptions from docstrings
- ✅ Return value descriptions
- ✅ Class attributes and methods
- ✅ Type hints display
- ✅ Cross-references and links
- ✅ Example code formatting
- ✅ Section headings (Args, Returns, Examples, etc.)

## Workflow

### For Contributors

1. **Write code** with docstrings in `pydvma/*.py`
2. **Push to GitHub**
3. **GitHub Actions** automatically builds docs
4. **Documentation updated** at https://torebutlin.github.io/pydvma

No manual API documentation needed!

### For Documentation Maintainers

API reference pages require minimal maintenance:

- Just list which functions/classes to document
- mkdocstrings handles the rest
- Update only when adding/removing functions

## Benefits

### Live Documentation

- Source code is the single source of truth
- Documentation always matches the code
- No manual synchronization needed

### Developer Friendly

- Write docs where you write code
- See documentation in IDE tooltips
- Standard Python docstring format

### User Friendly

- Professional, searchable documentation
- Consistent formatting
- Interactive examples

## Docstring Format Support

The current configuration accepts multiple formats:

### Simple Format (Current in codebase)
```python
def func(x, y):
    '''
    Do something.

    Args:
        x: first parameter
        y: second parameter

    Returns:
        result value
    '''
```

### Google Style (Recommended for new code)
```python
def func(x: int, y: str) -> bool:
    """Do something.

    Args:
        x: First parameter
        y: Second parameter

    Returns:
        Result value

    Examples:
        >>> func(1, "hello")
        True
    """
```

Both work perfectly with mkdocstrings!

## Advanced Features

### Type Hints

Add type hints for better documentation:

```python
from typing import Optional, Tuple
import numpy as np

def calculate_tf(
    time_data: 'TimeData',
    ch_in: int = 0,
    window: Optional[str] = None
) -> 'TfData':
    """Calculate transfer function."""
    # Implementation...
```

mkdocstrings displays these beautifully!

### Cross-References

Link to other functions automatically:

```python
def calculate_fft(time_data):
    """Calculate FFT.

    See Also:
        calculate_tf: For transfer functions
        calculate_sonogram: For time-frequency analysis
    """
```

mkdocstrings creates clickable links!

### Examples in Docstrings

Include runnable examples:

```python
def calculate_fft(time_data, window='hann'):
    """Calculate FFT.

    Examples:
        Basic usage:
        >>> freq_data = calculate_fft(time_data)

        With custom window:
        >>> freq_data = calculate_fft(time_data, window='blackman')
    """
```

These appear nicely formatted in the docs!

## Testing

### Preview Locally

```bash
# Install
pip install -r requirements-docs.txt

# Serve
mkdocs serve

# Check specific page
open http://127.0.0.1:8000/api/analysis/
```

### Check for Issues

```bash
# Build with warnings as errors
mkdocs build --strict
```

This will fail if mkdocstrings can't find a function or has parsing issues.

## Troubleshooting

### "Cannot find module pydvma"

Solution: Install pydvma in development mode:
```bash
pip install -e .
```

### Docstring not appearing

Check:
- Is the function/class public (not starting with `_`)?
- Is it listed in the API reference `.md` file?
- Does it have a docstring?

### Formatting looks wrong

Check docstring format:
- Consistent indentation
- Proper section headers (Args:, Returns:, etc.)
- Empty line after description

## Files Modified

### Configuration
- **mkdocs.yml** - Added mkdocstrings plugin configuration

### Documentation Pages
- **docs/api/analysis.md** - Structured function listing
- **docs/api/acquisition.md** - Function documentation
- **docs/api/datastructure.md** - All classes with members
- **docs/api/plotting.md** - Plotting module
- **docs/api/modal.md** - Modal analysis
- **docs/api/file.md** - File operations
- **docs/api/gui.md** - GUI classes

### Guides
- **docs/contributing-docstrings.md** - Complete docstring style guide

## Next Steps

### Immediate
✅ Infrastructure is in place
✅ All API pages configured
✅ Existing docstrings will be rendered

### Future (Optional)
- Gradually improve docstrings as you modify code
- Add type hints to new functions
- Include more examples in docstrings
- Expand class docstrings with attribute descriptions

## Summary

mkdocstrings integration is **complete and working**. The infrastructure is in place:

- ✅ All API pages use mkdocstrings
- ✅ Existing docstrings will render automatically
- ✅ Documentation updates when code changes
- ✅ Docstring style guide available
- ✅ No manual API documentation needed

**Just write code with docstrings - the documentation builds itself!**
