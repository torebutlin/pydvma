# From the Qt Logger

The desktop **Qt logger** was removed in pydvma 2.0.0, when the web
logger reached full parity with it. `dvma.Logger(...)` and
`dvma.Oscilloscope(...)` no longer exist; using either raises an error
that points here.

**From a notebook, use [`dvma.launch(settings)`](running-locally.md#from-python-dvmalaunch)**
where you used `dvma.Logger(settings)`. It takes the same `MySettings`
and opens the web logger in your browser, and instead of a window it
returns a session you can pull captures from:

```python
settings = dvma.MySettings(channels=2, fs=44100, stored_time=2.0)
session = dvma.launch(settings)      # was: logger = dvma.Logger(settings)
# ... record in the browser ...
data = session.data
```

From a terminal, `pydvma-serve --open` starts the same app. Everything
you **script** (`MySettings`, `log_data`, the `calculate_*` functions,
`save_data`/`load_data`, and the `DataSet.plot_*` methods) is unchanged.

## What maps where

| Qt logger | Web logger |
| --------- | ---------- |
| `dvma.Logger(settings)` | `dvma.launch(settings)`, or `pydvma-serve --open` |
| `MySettings` fields (device, `fs`, `channels`, `stored_time`, …) | **Setup** stage, pre-filled from those settings |
| **Oscilloscope** window | **Live** stage, plus the small monitor docked on every stage |
| Record button | **Log Data** on the **Acquire** stage, with pretrigger and output signal |
| **Time** view | **Time** stage |
| **FFT** view | **Frequency** stage (FFT, power spectrum, PSD, CSD) |
| **TF** view and coherence | **TF** stage, with coherence overlay |
| **Sonogram** view | **Sonogram** stage, with damping estimates |
| Modal fitting | **Fit** stage |
| **Generate output** panel | output signal on the **Acquire** stage |
| Save, load, export | **Load Data** / **Save Dataset** in the header, and the **Export** stage |
| Per-channel calibration | **Calibrate** dialog (sensitivities and units) |
| **Scaling** tool (Best Match, x(iω)) | the TF card's [scaling](analysis.md#scaling-xi-and-best-match) controls |

!!! note "x(iω) no longer changes your data"
    The Qt **x(iω)** button multiplied the stored spectra in place. In
    the web logger, **x(iω)^p** changes only what is plotted, so the
    measured values are never altered and a modal fit always uses them.
    **Best Match** works as before, by setting the channels' calibration
    factors.

## Files carry over

The web logger reads and writes the same [`.dvma` files](dvma-format.md)
as the Qt logger did, and still opens `.npy` files saved by pydvma 1.4
and earlier. Record on the lab PC, save, and reopen the file at home in
the [browser app](https://torebutlin.github.io/pydvma/app/).

## Running the old Qt logger

The last version with the Qt GUI is the **`qt-final`** git tag:

```bash
git clone https://github.com/torebutlin/pydvma.git
cd pydvma
git checkout qt-final
pip install -e ".[qt,soundcard]"
```

If the web logger doesn't do something you relied on in the Qt logger,
please [report it](https://github.com/torebutlin/pydvma/issues).
