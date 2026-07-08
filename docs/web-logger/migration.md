# From the Qt logger

The desktop **Qt Logger** (`dvma.Logger(...)`) is still available — it
ships in the `pydvma[qt]` extra and your existing labsheets keep working
unchanged. It is, however, **frozen** (bug-fixes only) while the
browser-based **web logger** becomes the recommended interface. This
page maps what you did in the Qt logger onto where it lives now.

!!! info "Nothing is being taken away yet"
    The Python/notebook interface (`MySettings`, `log_data`,
    `calculate_*`, `save_data`/`load_data`, `Logger`, `Oscilloscope`)
    is a stable compatibility contract and is unaffected. If you script
    your acquisition and analysis, keep doing so — see the
    [Python interface guides](../user-guide/acquisition.md). This page
    is about the interactive GUI.

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
the very same pydvma core (in a pyodide worker in the browser, or in the
`pydvma serve` process), so FFT/TF/windowing/modal maths are never
reimplemented — results match the desktop tool exactly.

## The labsheet launch path

A labsheet notebook used to set `MySettings` and pop the Logger window:

```python
import pydvma as dvma
settings = dvma.MySettings(device_driver='soundcard', fs=44100,
                           channels=2, stored_time=2.0)
logger = dvma.Logger(settings)          # Qt window
```

The web-logger equivalent depends on which mode you need (see
[the three modes](index.md)):

- **Analysis / soundcard, no install** — just open the Pages app at
  **`https://torebutlin.github.io/pydvma/app/`** and configure the
  capture in **Setup**. Nothing to launch from the notebook.

- **Lab PC with NI (or a local soundcard bridge)** — start the bridge
  instead of opening the Logger window:

  ```bash
  pydvma-serve --driver nidaq --open      # or --driver soundcard
  ```

  This serves the app *and* the WebSocket bridge from one local port and
  opens your browser at it.

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

## When to stay on the Qt logger

Until the web logger is confirmed as a full replacement, keep using the
Qt logger for anything it does that the web logger has not yet picked
up, and for established labsheets you would rather not change mid-term.
Report gaps you hit — the web logger is actively closing them.
