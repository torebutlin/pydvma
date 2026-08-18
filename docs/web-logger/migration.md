# From the Qt logger

The desktop **Qt Logger** (`dvma.Logger(...)`) has been **removed**. The
browser-based **web logger** reached full parity and is now the single
interactive interface. `dvma.Logger(...)` and `dvma.Oscilloscope(...)` no
longer exist — accessing either raises an error that points here. From a
notebook, the replacement is
[**`dvma.launch(settings)`**](#the-notebook-front-door-dvmalaunch). This
page maps what you did in the Qt logger onto where it lives now.

!!! info "The Python/notebook interface is unaffected"
    Everything you *script* — `MySettings`, `log_data`, `calculate_*`,
    `save_data`/`load_data`, and plotting via `DataSet.plot_*_data` — is
    a stable compatibility contract and is unchanged. Only the
    interactive Qt **windows** (`Logger`, `Oscilloscope`) were removed.
    If you script your acquisition and analysis, keep doing so — see the
    [Python interface guides](../user-guide/acquisition.md).

!!! note "Running the old Qt logger"
    The last version that still shipped the Qt GUI is preserved at the
    **`qt-final`** git tag. To run it, check out that tag (its `[qt]`
    extra still exists there):

    ```bash
    git checkout qt-final
    pip install -e ".[qt,soundcard]"
    ```

## Why switch

- **No install for analysis.** Students (and you) can open saved data
  in a browser with nothing to install — see
  [the three modes](index.md).
- **Soundcard acquisition in the browser**, and **NI acquisition**
  through a small local bridge, from the same UI.
- A cleaner, more maintainable interface with the rough edges of the
  Qt plotting/view-switching logic left behind.

## What maps where

| Qt Logger | Web logger |
| --------- | ---------- |
| `dvma.Logger(settings)` | [`dvma.launch(settings)`](#the-notebook-front-door-dvmalaunch) — same settings; returns a `Session` handle instead of a window |
| `MySettings(...)` fields (device, `fs`, `channels`, `stored_time`, ...) | **Setup** stage controls |
| Live **Oscilloscope** window | **Live** scope + the persistent mini-monitor (docked on every stage) |
| Record button / `log_data` | **Acquire** stage (with pretrigger arm and output stimulus) |
| **Time** view | **Time** stage |
| **FFT** view | **Frequency** stage (FFT / PSD / CSD) |
| **TF** view (+ coherence) | **TF** stage (+ coherence overlay) |
| **Sonogram** view | **Sonogram** stage (+ damping fit) |
| SDOF **modal fitting** | **Fit** stage (Fit 1/2/3, Reject, Refine, per-mode edit) |
| **Generate output** panel | **Acquire** output stimulus (sweep / white / Gaussian) — bridge only |
| Save / Load / Export | **Export** stage (`.dvma`, `.mat`, CSV, PNG/PDF) |
| Per-channel calibration | **Calibrate** dialog (sensitivity → cal factors, units) |
| **Scaling** tool — Best Match, x(iω) | TF card's **[scaling](analysis.md#scaling-xi-and-best-match)** group (Best match + x(iω)^p) |

!!! note "x(iω) is non-destructive in the web logger"
    The Qt Scaling tool's **x(iω)** button called `multiply_by_power_of_iw`,
    which **mutates** the stored `FreqData`/`TfData` in place. The web
    logger's **x(iω)^p** is instead a **per-set display transform** — it
    changes only what is plotted, never the stored arrays, so a set that
    recomputes or is re-fitted keeps its measured values. (It is persisted
    per set in the `.dvma` file and does not feed the modal fit.) **Best
    Match** matches Qt's maths and, like Qt's `set_calibration_factors_all`,
    writes through the calibration path — in the web logger that is the
    per-source-channel `channel_cal_factors`.

The data model is identical underneath: the web logger's analysis runs
the very same pydvma core in every mode — a pyodide worker in the
browser (Pages, JupyterLite), or natively in the `pydvma serve` process
when the app is served locally (the default there; `?enginehost=`
overrides, and the browser engine is the automatic fallback) — so
FFT/TF/windowing/modal maths are never reimplemented — results match
the desktop tool exactly.

## The notebook front door: `dvma.launch`

A labsheet notebook used to set `MySettings` and pop the Logger window:

```python
import pydvma as dvma
settings = dvma.MySettings(device_driver='soundcard', fs=44100,
                           channels=2, stored_time=2.0)
logger = dvma.Logger(settings)          # Qt window (removed; see qt-final)
```

`dvma.launch` takes the same `MySettings` and opens the web logger
instead — but where `Logger` gave you a window, `launch` gives you a
**handle to the running session**, so the notebook and the browser can
pass data back and forth:

```python
import pydvma as dvma

settings = dvma.MySettings(device_driver='soundcard', fs=44100,
                           channels=2, stored_time=2.0)
session = dvma.launch(settings)     # starts the server, opens the browser
print(session.url)                  # http://127.0.0.1:<port>/ (also printed)

# ... record in the browser: Setup is prefilled, press Log on Acquire ...

data = session.data                 # a fresh DataSet, captures included
data.calculate_fft_set(window='hann')
data.plot_freq_data()

session.push(data)                  # hand it back; the app offers to reload
session.close()
```

Installed from the `[serve]` extra
(`pip install "pydvma[serve,soundcard]"`), `launch` starts the whole
`pydvma-serve` stack — acquisition bridge, native compute engine,
[session journal](index.md#the-session-lives-in-pydvma-serve) and the
embedded UI — on a background thread **inside your kernel**, so it works
the same from a plain script and from inside Jupyter (whose kernel
already runs an event loop of its own). `MySettings` prefills **Setup**
exactly as [`--settings`](#pre-seeding-settings-with-settings) does, and
supplies the acquisition driver.

Useful arguments: `open_browser=False` starts the server without opening
a tab (`session.url` still tells you where it is), and `port=8760` pins
the port instead of taking a free one — handy for a fixed bookmark, at
the cost of failing if something already holds it. `Session` is a context
manager, so
`with dvma.launch(settings) as session:` stops the server on the way out.

### Getting data in and out

`session.data` **materialises a fresh `DataSet` on every access** — it is
a copy, not a live reference, so anything you do to it changes nothing
until you push it back. `session.push(data)` is the only write path, and
it **merges** rather than replaces:

- A capture carries a `unique_id`, so one you pulled, modified and pushed
  back **replaces** the stored copy in place — the pull → filter → push
  round trip updates data where it sits instead of duplicating it.
- Anything without an id — the spectra, transfer functions and sonograms
  you compute in the notebook — **appends**. Push the same computed set
  twice and you get two copies of it.
- An item you pulled carries the app's display state for it (channel
  labels, units, the set's analysis settings) invisibly through the round
  trip, so pushing it back preserves what you see on screen. An item you
  *built* in the notebook has none, so replacing a stored item with a
  newly built one clears that state and the app re-seeds its defaults on
  reload.

A connected app is never silently overwritten: it raises a *"pydvma
session updated from a notebook — reload?"* offer (with an empty tray it
simply loads the pushed session). Likewise, what `session.data` holds is
the session's *data* — captures and loaded sets — not the analysis views
the app computed from them, which are not part of the session document.
Compute what you need in the notebook.

`session.close()` stops the server; `session.data` still reads afterwards
(pulling your data out of a session you have finished with is the point),
but `push` does not, because there is no longer an app to notify.

A [worked notebook flow](../examples/basic.md#a-notebook-session-dvmalaunch)
runs through the whole cycle.

### Without a notebook

You do not need a kernel at all. The other two routes are unchanged (see
[the three modes](index.md)):

- **Analysis / soundcard, no install** — just open the Pages app at
  **`https://torebutlin.github.io/pydvma/app/`** and configure the
  capture in **Setup**. Nothing to launch from the notebook.

- **Lab PC with NI (or a local soundcard bridge)** — start the bridge
  from a terminal:

  ```bash
  pydvma-serve --driver nidaq --open      # or --driver soundcard
  ```

  This is the same server `dvma.launch` runs, minus the `Session`
  handle: it serves the app *and* the WebSocket bridge from one local
  port and opens your browser at it.

### Pre-seeding settings with `--settings`

`pydvma-serve --settings config.json` pre-loads a JSON file and
publishes it at the bridge's `/config` endpoint:

```bash
pydvma-serve --driver nidaq --settings my_lab_config.json --open
```

The app fetches `/config` on start. A JSON document there is both the
"opened through `pydvma serve`" signature (so the app **automatically
switches on live acquisition** rather than falling back to browser Web
Audio) **and a launch configuration the app consumes**: the served
`MySettings` fields **pre-fill Setup and Acquire** — sample rate,
channels, duration, the selected device (`device_driver` +
`device_index`, matched against the enumerated devices), the pretrigger
(`pretrig_samples`/`threshold`/`channel`/`timeout`, armed when a sample
count is given), the output stimulus, the NI voltage rails
(`VmaxNI`/`output_VmaxNI`), and IEPE/terminal settings where the NI group
is shown. A toast confirms *"Settings loaded from pydvma-serve
--settings"*.

This is the direct analogue of handing `MySettings` to `Logger(...)` — the
notebook (or a launch script) starts the bridge with your lab's
configuration and the student opens the tab already set up. The prefill
runs **once at boot** and only fills defaults, so any change you make
afterwards in Setup is never overwritten; unknown or malformed fields are
skipped silently.

The wire accepts more than the app draws. The bridge's settings
whitelist is derived from the `MySettings` signature, so fields with no
Setup control of their own still reach the recorder — `capture_fs`,
`oversample` and `lpf_on` (the
[capture rate](acquisition.md#capture-rate-and-delivered-rate) and its
oversampling rule), and `input_gain_db` / `input_mode` (the stated
preamp gain that derives an audio interface's
[input full scale](calibration.md#soundcard-input-gain-and-full-scale)).
Put them in the settings file and every capture taken through that
bridge carries them.

!!! note "Bridge auto-detection"
    You do not normally need to configure anything: opening the app
    *through* `pydvma serve` is detected automatically via `/config`.
    Advanced overrides also exist — a `?bridge=ws://host:port/ws` URL
    parameter, or a `window.__pydvma_bridge` global — but they are
    rarely needed.

## Files carry over

Data saved by the Qt logger opens directly in the web logger, and vice
versa — both read and write the same [`.dvma` format](dvma-format.md),
and both still open legacy `.npy` pickle files from pydvma ≤ 1.4.0. You
can record on the lab PC, save a `.dvma`, and re-open it later in the
no-install browser app at home.

## If you still need the old Qt logger

The Qt logger is gone from the current release, but nothing is lost: the
last version that shipped it is preserved at the **`qt-final`** git tag.

```bash
git checkout qt-final
pip install -e ".[qt,soundcard]"   # the [qt] extra exists on that tag
```

The web logger's round-6 parity audit closed the last gaps, which is why
the desktop GUI was retired. If you hit something the web logger does not
yet do, please report it.
