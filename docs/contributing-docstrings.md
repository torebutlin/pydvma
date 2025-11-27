# Docstring Style Guide

This guide explains how to write docstrings for pydvma that will automatically appear in the documentation.

## Overview

pydvma uses **mkdocstrings** to automatically extract documentation from Python docstrings. When you update docstrings in the source code, the changes automatically appear in the online documentation.

## Docstring Format

The codebase currently uses a simple format. You can use either:

1. **Simple Args format** (current style in most of the codebase)
2. **Google style** (recommended for new docstrings)

Both will be parsed correctly by mkdocstrings.

## Simple Args Format (Current)

```python
def calculate_fft(time_data, time_range=None, window=None):
    '''
    Calculate FFT of time domain data.

    Args:
        time_data (<TimeData> object): time series data
        time_range: 2x1 numpy array to specify data segment to use
        window (str): window function name ('hann', 'blackman', etc.)

    Returns:
        <FreqData> object containing frequency domain data
    '''
    # Implementation...
```

## Google Style Format (Recommended for New Code)

```python
def calculate_fft(time_data, time_range=None, window=None):
    """Calculate FFT of time domain data.

    Computes the Fast Fourier Transform of the input time series data,
    with optional windowing and time range selection.

    Args:
        time_data (TimeData): Time series data to transform
        time_range (array-like, optional): 2-element array [start, end]
            specifying the time segment to use. If None, uses all data.
        window (str, optional): Window function name. Options include
            'hann', 'hamming', 'blackman', or None for rectangular window.
            Defaults to None.

    Returns:
        FreqData: Frequency domain representation of the input data,
            containing the complex spectrum and frequency axis.

    Examples:
        >>> freq_data = calculate_fft(time_data, window='hann')
        >>> magnitude = np.abs(freq_data.freq_data)

    Notes:
        The frequency resolution is determined by the duration of the
        selected time segment: Δf = 1/duration
    """
    # Implementation...
```

## Class Docstrings

```python
class TimeData:
    """Container for time-domain measurement data.

    Stores time series data along with metadata, settings, and axis
    information. Supports multi-channel data.

    Attributes:
        time_axis (ndarray): Time vector in seconds
        time_data (ndarray): Signal data, shape (samples, channels)
        settings: Acquisition settings object
        test_name (str): Name identifier for this measurement
        unique_id (str): Unique identifier for data traceability

    Examples:
        >>> time_data = TimeData(t, y, settings, test_name='test_01')
        >>> channel_0 = time_data.time_data[:, 0]
    """

    def __init__(self, time_axis, time_data, settings, test_name='', id_link=None):
        """Initialize TimeData object.

        Args:
            time_axis (ndarray): Time vector
            time_data (ndarray): Signal data array
            settings: Settings object
            test_name (str, optional): Test identifier
            id_link (str, optional): Link to parent data ID
        """
        # Implementation...
```

## Type Hints

Add type hints where possible:

```python
from typing import Optional, Union, Tuple
import numpy as np

def calculate_tf(
    time_data: 'TimeData',
    ch_in: int = 0,
    time_range: Optional[np.ndarray] = None,
    window: Optional[str] = None,
    N_frames: int = 1,
    overlap: float = 0.5
) -> 'TfData':
    """Calculate transfer function from time domain data.

    Args:
        time_data: Input time series data
        ch_in: Index of input channel
        time_range: Time segment [start, end] or None for all data
        window: Window function name or None
        N_frames: Number of segments for averaging
        overlap: Overlap fraction between segments (0 to 1)

    Returns:
        Transfer function data with coherence
    """
    # Implementation...
```

## Sections in Docstrings

Common sections (all optional):

- **Args**: Function/method parameters
- **Returns**: Return value description
- **Raises**: Exceptions that may be raised
- **Examples**: Usage examples
- **Notes**: Additional information
- **References**: Citations or links
- **See Also**: Related functions
- **Warnings**: Important warnings for users

## Examples Section

Provide practical examples:

```python
def calculate_damping_from_sono(time_data, n_chan=1, nperseg=None, start_time=None):
    """Calculate damping from sonogram analysis of free decay.

    Analyzes the decay of spectral peaks in a sonogram to extract
    modal parameters including natural frequencies and damping ratios.

    Args:
        time_data (TimeData): Time series containing free decay response
        n_chan (int): Channel index to analyze. Defaults to 1.
        nperseg (int, optional): FFT segment length for sonogram.
            If None, automatically determined based on signal length.
        start_time (float, optional): Time to start analysis in seconds.
            If None, automatically detected from pretrigger settings.

    Returns:
        tuple: A tuple containing:
            - fn (ndarray): Natural frequencies in Hz
            - Qn (ndarray): Quality factors (Q = 1/(2ζ))
            - fit_data (dict): Dictionary with fit visualization data:
                - 't': time axis
                - 'fits': list of fit dictionaries for each mode

    Examples:
        >>> # Single impact test
        >>> fn, Qn, fit_data = calculate_damping_from_sono(time_data, n_chan=1)
        >>> zeta = 1 / (2 * Qn)  # Convert Q to damping ratio
        >>> print(f"Mode 1: f={fn[0]:.1f} Hz, ζ={zeta[0]:.4f}")

        >>> # Specify custom parameters
        >>> fn, Qn, fit_data = calculate_damping_from_sono(
        ...     time_data,
        ...     n_chan=0,
        ...     nperseg=1024,
        ...     start_time=0.05
        ... )

    Notes:
        The method identifies frequency peaks in the initial spectrum and
        tracks their exponential decay over time. Better results are obtained
        with:
        - Good signal-to-noise ratio
        - Sufficient decay duration (several oscillation periods)
        - Appropriate nperseg choice based on frequency spacing

    See Also:
        calculate_sonogram: Compute the underlying sonogram
        calculate_tf: Alternative method for modal identification
    """
    # Implementation...
```

## What Gets Documented

mkdocstrings automatically extracts:

- ✅ Function and method signatures
- ✅ Parameter descriptions from docstrings
- ✅ Return value descriptions
- ✅ Class attributes
- ✅ Examples
- ✅ Type hints (if provided)

## Testing Your Docstrings

### Local Preview

```bash
# Install dependencies
pip install -r requirements-docs.txt

# Serve documentation locally
mkdocs serve
```

Navigate to the API reference page for your module to see how it looks.

### Docstring Linting

Use `pydocstyle` to check docstring quality:

```bash
pip install pydocstyle
pydocstyle pydvma/analysis.py
```

## Migration Strategy

To gradually improve documentation:

1. **New code**: Use Google-style docstrings with type hints
2. **Existing code**: Update docstrings as you modify functions
3. **Priority**: Focus on user-facing functions first
4. **No rush**: The current simple format works; improve over time

## Best Practices

### Do ✅

- Describe what the function does in one clear sentence
- Document all parameters and return values
- Provide at least one usage example
- Explain units (Hz, seconds, etc.)
- Note important limitations or assumptions

### Don't ❌

- Don't duplicate information already in type hints
- Don't describe implementation details (use code comments instead)
- Don't write overly long docstrings (link to user guide for details)
- Don't forget to update docstrings when changing function behavior

## Live Documentation Updates

When you push changes to GitHub:

1. Commit updated source files with new docstrings
2. Push to master/main branch
3. GitHub Actions automatically rebuilds documentation
4. Changes appear online within minutes

No need to manually update API reference pages - mkdocstrings handles it automatically!

## Further Reading

- [Google Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [PEP 257 - Docstring Conventions](https://www.python.org/dev/peps/pep-0257/)
- [mkdocstrings Documentation](https://mkdocstrings.github.io/)
