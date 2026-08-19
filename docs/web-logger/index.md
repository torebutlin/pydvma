# The web logger

The **web logger** is pydvma's browser-based interface for acquiring,
monitoring, analysing and exporting dynamics-and-vibration data. It is
the interactive way to use pydvma, and has **replaced** the earlier
desktop [Qt logger](migration.md), which was removed once the web logger
reached full parity.

!!! info "New in 2.0.0"
    **pydvma 2.0.0 is the first release built around the web logger.**
    Removing the desktop Qt GUI is a breaking change, hence the major
    version bump. The last version that shipped the Qt logger is the
    [`qt-final` git tag](migration.md); everything you *script* in Python
    is unchanged.

It is **one interface that runs in three modes**, so the same tool
covers no-install analysis at home, soundcard measurements from any
laptop, and full NI acquisition on a lab PC.

## The three modes

| Mode | Where it runs | Data source | Install |
| ---- | ------------- | ----------- | ------- |
| **Pages app** | [`torebutlin.github.io/pydvma/app/`](https://torebutlin.github.io/pydvma/app/) | Analysis of saved files + **soundcard** capture via the browser's Web Audio API | **None** |
| **Local bridge** | your machine, via `pydvma-serve` | Real hardware — **soundcard or NI-DAQ** — driven by a local Python process | `pip install "pydvma[serve,soundcard]"` (`[ni]` for NI) |
| **JupyterLite** | [`torebutlin.github.io/pydvma/lite/`](https://torebutlin.github.io/pydvma/lite/) | `import pydvma` in a notebook, running under pyodide | **None** |

All three share **one maths engine**: pydvma's analysis core (FFT, TF,
windowing, modal fitting) runs unchanged everywhere — in a pyodide web
worker in the browser (Pages, JupyterLite), or natively in the
`pydvma serve` process itself when the app is served locally, which is
the default there. Either way results are identical and never
reimplemented in JavaScript; see the [local bridge](#2-local-bridge-real-hardware-from-the-same-ui)
section below for what the native engine changes in practice.

### 1. Pages app — no install

The published app at
**[`torebutlin.github.io/pydvma/app/`](https://torebutlin.github.io/pydvma/app/)**
needs nothing installed. Open it in a browser and you can:

- **Load a saved file** (`.dvma`, legacy `.npy`, or `.mat`) and work
  through the full analysis and modal-fitting workflow; and
- **Capture live from a soundcard** using the browser's Web Audio API —
  a real measurement path, not just a demo (soundcards are widely used
  as low-cost DAQs).

Files never leave your machine — the analysis runs locally in your
browser. This is the mode to point students at for analysing lab data
at home.

!!! note "Browser (Web Audio) mode caveats"
    A browser cannot reach NI-DAQ hardware, and the OS/browser can apply
    hidden audio processing. pydvma requests the browser to disable echo
    cancellation, noise suppression and auto-gain by default so a
    measurement is not silently filtered — but a browser soundcard is
    still a consumer input. For calibrated or NI measurements, use the
    local bridge. See [Acquisition and setup](acquisition.md).

### 2. Local bridge — real hardware, from the same UI

`pydvma-serve` is a small local server that serves the *same* app and
drives your real hardware from it over a WebSocket. It is how you reach
**NI-DAQ** hardware (which no browser can touch) and how you get
uncompromised **soundcard** capture on the lab PC.

```bash
pip install "pydvma[serve,soundcard]"   # add [ni] for National Instruments
pydvma-serve --open                     # serves the UI + bridge, opens a browser
pydvma-serve --driver nidaq --open
```

`[serve]` alone installs the bridge but no acquisition backend, and a
missing backend is quiet — `pydvma-serve --list-devices` simply omits
that driver's section rather than reporting an error. Name the backends
you need, or install `pydvma[full]`.

The bundled UI is embedded in the installed wheel — no Node.js, no repo
checkout, no build step. The app auto-detects it was opened through the
bridge and switches live acquisition on. See
[Installation](../getting-started/installation.md#running-the-browser-app-locally-pydvma-serve)
and [NI hardware over the bridge](ni-hardware.md).

The bridge also changes *where the maths runs*. Opened through
`pydvma-serve`, the app runs analysis in a **native engine** — ordinary
CPython on your machine, reached over a second local WebSocket — instead
of the in-browser pyodide worker. This is a performance and reach
upgrade, not a behaviour change: it removes the browser worker's ~2 GB
wasm32 memory ceiling (the CWT/sonogram budget alone rises from
0.75 GiB to 8 GiB), runs at full BLAS speed, and makes **Stop** on a
long calculation kill a subprocess in milliseconds instead of rebooting
the whole engine. It is on by default whenever the app is served
locally; the **BusyChip** tooltip (top of the app, next to the busy
spinner) names the active engine so you can always tell which one you
are on. If the native host is unreachable or running a mismatched
`pydvma` version, the app falls back to the browser engine automatically
and raises a one-shot toast explaining why. To force a specific engine —
for testing, or if you hit a native-only quirk — append `?enginehost=`
to the URL with `native`, `pyodide`, or an explicit `ws://` URL.

#### The session lives in `pydvma-serve`

Served locally, the **serve process holds the authoritative copy of your
session**. The same debounced autosave that writes to browser storage also
posts to the server, and every capture is registered server-side the moment
it is taken — so a capture is safe even if the tab closes inside the
autosave's two-second window.

- **Close the tab and reopen it**: the app offers *"Restore session from
  pydvma-serve?"*. The session is still on the server; closing the tab
  cost you nothing.
- **If the serve process itself died**, the next `pydvma-serve` start finds
  the session file it left behind and the app offers *"Recover session from
  a previous pydvma-serve run?"*. **Dismiss** deletes the file, so it is
  never offered again. The file lives in the system temp directory;
  `pydvma-serve --session-dir DIR` puts it somewhere you choose.

Neither is automatic — both are offers you accept or dismiss. The
browser-side autosave still works exactly as it did (see
[Autosave and session restore](export.md#autosave-and-session-restore)),
and the **Pages app is unchanged** — with no serve process there is no
server-side journal, and the browser autosave is all there is, exactly as
before. When both the server and the browser hold a session, the server's
copy is the one offered.

!!! note "What a restore brings back"
    The **data**: your captures, loaded sets, calibration, units, channel
    labels and any saved modal fit — plus any analysis results that are
    already **part of the document**.

    Computed results become part of the document when you press **Save
    Dataset**: saving materialises the FFT and TF views into real items
    (see [what Save writes](export.md#what-save-writes-data-with-its-processing)),
    and from then on they ride the autosave and the journal like any other
    item, so a restore brings them back too. Analysis you computed but
    never saved is **not** in the session document — re-run it after
    restoring. On the native engine that is quick.

#### `dvma.launch` — the notebook front door

From a notebook or script, `dvma.launch` starts all of the above from your
kernel and hands back a handle to the running session:

```python
import pydvma as dvma

session = dvma.launch(dvma.MySettings(device_driver='soundcard',
                                      fs=8000, channels=2, stored_time=2.0))
# ... record in the browser ...
data = session.data          # a fresh DataSet, captures included
data.calculate_fft_set(window='hann')
session.push(data)           # hand it back; the app offers to reload
session.close()
```

It runs the server on a background thread inside the calling process, so it
behaves the same in a plain script and inside Jupyter, and `MySettings`
prefills **Setup** just as `--settings` does. This is the replacement for
the removed `dvma.Logger` — see [From the Qt logger](migration.md#the-notebook-front-door-dvmalaunch)
for the full story and [Basic Examples](../examples/basic.md#a-notebook-session-dvmalaunch)
for a worked flow. `pydvma-serve --open` starts exactly the same server
when you do not need a kernel handle.

### 3. JupyterLite — `import pydvma` in the browser

For scripted analysis with no install, the
**[JupyterLite site](https://torebutlin.github.io/pydvma/lite/)** runs a
real pyodide Python kernel in your browser with pydvma pre-bundled. Drag
a `.dvma` or `.npy` file into its file browser, then
`dvma.load_data(...)` and use the full [Python API](../user-guide/analysis.md).
This is the notebook-shaped counterpart to the point-and-click app.

## The workflow (stages)

The app is organised as a set of **stages** you move through, with a
persistent **tray** of your datasets and a docked **mini-monitor** on
every stage:

1. **[Setup](acquisition.md)** — choose the device, sample rate,
   channels and duration (plus NI options when bridged).
2. **[Acquire](acquisition.md)** — record, with optional pretrigger and
   output stimulus.
3. **[Live](live-monitoring.md)** — a full oscilloscope: time, live FFT
   or Welch PSD, and level meters.
4. **[Time](analysis.md)** / **[Frequency](analysis.md)** /
   **[TF](analysis.md)** / **[Sonogram](analysis.md)** — the analysis
   views, with resolution and averaging controls.
5. **[Nonlin](nonlin.md)** — a Schoukens best-linear-approximation
   measurement that separates measurement noise from nonlinear
   distortion.
6. **[Fit](modal-fitting.md)** — SDOF modal fitting with Refine and
   per-mode editing.
7. **[Export](export.md)** — save `.dvma`, export `.mat` / CSV / figures.

Per-channel **[calibration and units](calibration.md)** apply throughout,
and everything saves to the shared **[`.dvma` format](dvma-format.md)**.

Across the top, the **header** carries **Load Data**, **Save Figure**
and **Save Dataset**, plus a **light/dark theme toggle** (the sun/moon
button). The theme follows your operating system by default; toggling
it remembers your choice for next time.

## Roadmap

Nothing major in flight right now — see the repo's `dev/` notes for
what's next. This page and the guides describe only what currently
ships.
