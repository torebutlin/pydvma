# Docstring Style Guide

The API reference is generated from the docstrings in `pydvma/*.py` by
**mkdocstrings**. What you write in a docstring is what users read, so
the format matters: a docstring the parser cannot read fails the
documentation build.

## Format: Google style

Every docstring uses Google style, with `Args:`, `Returns:` and so on.
Two things that look like docstrings but do not render properly:

- **NumPy style** (`Parameters` over a row of dashes). The parser does
  not read it, so the whole docstring appears as one block of prose with
  no parameter table.
- **Sphinx roles** such as `:func:` and `:class:`. They appear
  literally. Use plain backticks: `` `calculate_tf` ``.

Start with a one-line summary in the imperative mood, then a blank line,
then any further detail. Do not open with a label such as "Note:" or
"Provenance:": the first line is the summary shown in the page.

```python
def calculate_fft(time_data, time_range=None, window=None):
    """Calculate the FFT of a single-capture TimeData.

    The frequency resolution is the reciprocal of the duration of the
    selected segment.

    Args:
        time_data (TimeData): The capture to transform.
        time_range (list or np.ndarray, optional): Two-element
            ``[start, stop]`` in seconds. None (the default) uses the
            whole record.
        window (str, optional): A ``scipy.signal.windows`` name such as
            ``'hann'``, or None for a rectangular window.

    Returns:
        freq_data (FreqData): The complex one-sided spectrum and its
            frequency axis.

    Examples:
        >>> freq_data = calculate_fft(time_data, window='hann')
    """
```

pydvma's functions carry no type annotations, so the parser takes the
types from the docstring: **every `Args:` and `Returns:` entry needs its
type in parentheses**, as `name (type): description`. That applies to a
single return value too. Write `freq_data (FreqData): ...`; `FreqData: ...`
is read as a name with no type and warns. For several return values, give
one such line per value. Real exemplars to copy from:

- `pydvma.analysis.calculate_damping_from_sono`: `Args:` and a
  multi-value `Returns:`.
- `pydvma.datastructure.TimeData`: a class with an `Attributes:` list.
- `pydvma.options.MySettings`: a long class docstring that states its
  conventions up front.

## Class docstrings

Describe what the object holds and give an `Attributes:` list. Describe
any constructor arguments that are not also attributes in the same
docstring.

```python
class TimeData:
    """One block of acquired time-series data plus its metadata.

    Attributes:
        time_axis (np.ndarray): Sample times in seconds.
        time_data (np.ndarray): Shape ``(n_samples, n_channels)``, in volts.
        units (list[str] or None): Engineering units per channel.
        channel_cal_factors (np.ndarray): Per-channel multipliers from
            volts to engineering units. Defaults to all-ones.
    """
```

## What the parser does with each section

| Section | Rule | If you get it wrong |
| ------- | ---- | ------------------- |
| `Args:` | One entry per parameter, `name (type): description`. Indent a continuation line four spaces further than its entry. | A missing `(type)` gives "No type or annotation for parameter". A continuation indented two spaces gives a "Confusing indentation" warning. |
| `Returns:` | One `name (type): description` line per returned value. Indent a continuation line further than its entry. | Prose here, or `Type: description`, gives "No type or annotation for returned value", and each unindented line of a paragraph counts as a separate value. To describe a return in prose, write a paragraph after the `Args:` block instead of a `Returns:` section. |
| `Raises:` | Only `ExceptionType: description` entries. | Prose under `Raises:` fails with "Failed to get 'exception: description' pair". |
| `Warnings:` | The plural is a list of `WarningType: description` pairs. | Prose under it fails with "Failed to get 'warning: description' pair" and is dropped. For a callout, write `Warning:` (singular). |
| `Warning:`, `Note:`, `Notes:`, `See Also:`, `References:` | Rendered as a titled callout box. | `See Also:` is not turned into links. |
| `Examples:` | `>>>` blocks are shown with highlighting. | They are not run as tests. |
| `Attributes:` | For classes. | |

Each of these warnings stops `python -m mkdocs build --strict`, which CI
runs on every push and pull request.

## What belongs in the docstring

Put in the docstring everything a user needs to call the function
correctly:

- units (Hz, seconds, volts) and shapes;
- constraints and conventions, including hardware limits such as
  voltage ranges, terminal modes, clock routing and sample-rate
  ladders;
- what is returned, and any argument that is changed in place;
- what is raised.

Put in a code comment the reasoning behind the implementation: why a
particular NumPy stride is used, what an earlier bug looked like, how
the algorithm was derived. A constraint that only lives in a `#`
comment is invisible on the published page.

Keep docstrings as short as the facts allow, and link to the relevant
user guide page for a worked example rather than repeating it.

When you edit a function, check its docstring against what the code now
does and correct it, even if your change was unrelated.

## Adding a function to the API reference

The API pages under `docs/api/` list their entries by hand. A new public
function or class does not appear until you add one line to the matching
page:

```markdown
::: pydvma.analysis.calculate_fft
```

Settings that apply to every entry (heading level, no source listing)
are set once in `mkdocs.yml`. Do not repeat them per entry. A class is
rendered with its public members automatically; do not add
`members: true`, which switches off the filter that hides `_private`
methods and shows them all.

## Checking your docstrings

Build the site with the same strictness as CI:

```bash
python -m mkdocs build --strict
```

Then open the API page for your module to read it as a user would:

```bash
python -m mkdocs serve
```

Install the dependencies as described under
[Documentation](contributing.md#documentation).

## Publishing

The documentation is built and deployed by GitHub Actions on every push
to `master`. Pull requests get the strict build only. Changes appear on
the site a few minutes after the push.

## Further reading

- [Google Python Style Guide, section on docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)
- [PEP 257, docstring conventions](https://peps.python.org/pep-0257/)
- [mkdocstrings documentation](https://mkdocstrings.github.io/)
