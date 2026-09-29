# Running Locally: `pydvma-serve` and `dvma.launch`

The web logger at
[torebutlin.github.io/pydvma/app/](https://torebutlin.github.io/pydvma/app/)
runs entirely in your browser. Installed pydvma can also serve the same
app from your own machine, which gives it:

- **lab hardware**: NI-DAQ devices, which no browser can reach, and
  soundcards and audio interfaces without the browser's audio
  processing, with calibrated full scales where pydvma knows the device;
- **native analysis**: calculations run in ordinary Python on your
  machine, faster and with far more memory than the browser allows; and
- **a safe session**: your captures are held by the server, so closing
  the tab loses nothing.

There are two ways to start it. They run the same server:

- **`pydvma-serve`** from a terminal, when you just want the app; and
- **`dvma.launch()`** from Python, which also gives your notebook a
  handle for pulling data out and pushing data back.

Both need `pip install "pydvma[full]"` (see
[Installation](../getting-started/installation.md)).

## From a terminal: `pydvma-serve`

```bash
pydvma-serve --open
```

This starts the server and opens the app in your browser at
`http://127.0.0.1:8760`. Stop it with Ctrl+C in the terminal.

| Option | Effect |
| ------ | ------ |
| `--open` | open the app in a browser tab on start |
| `--list-devices` | print what is plugged in, grouped by physical device, with the recommended backend and calibration status, then exit (`--list-kind output` or `all` for outputs) |
| `--driver {auto,soundcard,nidaq,mock}` | the device the app's **Default** entry records from. `auto` (the default) uses your computer's default input, or a built-in test signal if there is none; `mock` always uses the test signal |
| `--settings FILE` | pre-fill Setup from a JSON file ([below](#pre-filling-setup)) |
| `--port N` | listen on another port (default `8760`) |
| `--session-dir DIR` | where the session file is kept (default: the system temp folder) |

The server only accepts connections from your own machine. Run
`pydvma-serve --help` for every option.

## From Python: `dvma.launch`

### 1. Launch

```python
import pydvma as dvma
%matplotlib widget

settings = dvma.MySettings(channels=2, fs=8000, stored_time=2.0)
session = dvma.launch(settings)
```

A browser tab opens on the app with **Setup** filled in from `settings`.
The address is printed and is also `session.url`. The server runs in the
background inside your Python process, so the notebook stays usable and
it works the same from a plain script.

`launch` takes a few optional arguments: `open_browser=False` starts
without opening a tab, and `port=8760` uses a fixed port (for a
bookmark) instead of a free one chosen for you. Called with no settings,
`dvma.launch()` opens with the app's defaults.

### 2. Record in the browser

Use the app as usual: check signals on **Live**, then press **Log Data**
on **Acquire**. Each capture reaches the session as soon as it is taken,
so the notebook can see it without you saving anything.

### 3. Pull the data into Python

```python
data = session.data
print(len(data.time_data_list), 'captures')

data.calculate_tf_set(ch_in=0, window='hann', N_frames=8)
data.plot_tf_data()
```

`session.data` is a fresh **copy** each time you read it, so change it
freely: nothing reaches the app until you push it back. It holds the
session's captures, any files loaded in the app, and the app's FFT and
transfer-function results **from the last time you pressed Save
Dataset**. Analysis the app shows but that you have not saved is not
included; compute what you need in Python. Results that came from the
app record how they were made:

```python
data.tf_data_list[0].source_settings    # {'calc': 'tf', 'window': 'hann', ...}
```

### 4. Push data back (optional)

```python
session.push(data)
```

The app then offers *"pydvma session updated from a notebook —
reload?"*, so nothing on screen is replaced without your say-so (with
an empty app it simply loads). Items are matched by their identity:

- anything you pulled and changed **replaces** its original;
- anything you created in Python, such as a spectrum you computed, is
  **added**; pushing the same object again replaces it rather than
  adding a copy; and
- pushing back an unchanged pull changes nothing.

If you change a capture's samples and push it back, any results the app
saved for that capture were computed from the old samples. The app
notices and marks the capture **⚠ source changed**, one click from a
recompute.

!!! note "Files from before pydvma 2.4"
    Analysis results inside files saved by older versions carry no
    identity, so pushing them repeatedly adds copies. Re-save the file in
    the app, or recompute the results in Python, to fix this.

### 5. Save and finish

```python
dvma.save_data(data, filename='my_test.dvma')

# or save part of it: the fourth capture (index 3) and everything computed from it
dvma.save_data(data, filename='measurement_3.dvma', sets=[3])

session.close()
```

After `close()` the server has stopped, but `session.data` still reads.
To close automatically, even if a cell fails, use a `with` block:

```python
with dvma.launch(settings) as session:
    ...
    data = session.data
```

## Pre-filling Setup

`dvma.launch(settings)` pre-fills Setup from its `MySettings`. The
terminal equivalent is a JSON file of the same settings:

```json
{
  "device_driver": "nidaq",
  "device_index": 0,
  "channels": 4,
  "fs": 12800,
  "stored_time": 2.0,
  "pretrig_samples": 200
}
```

```bash
pydvma-serve --settings lab.json --open
```

Any `MySettings` argument can go in the file, including ones with no
Setup control, such as `input_gain_db`, which then apply to every
capture. The file is read once when the app opens and only fills in
starting values; anything you change in Setup afterwards stays changed.
Unknown fields are ignored.

## Your session is kept safe

When the app is served locally, the server holds the working copy of
your session, and saves it to a file as it changes.

- **Close the tab and reopen it**, and the app offers to restore the
  session.
- **If the server itself stopped** (a crash, or the computer restarted),
  the next `pydvma-serve` or `dvma.launch` finds the file it left behind
  and the app offers to recover it. **Dismiss** deletes that file.

A restore brings back your captures, loaded files, calibration, units,
channel labels, any modal fit, and the analysis results you last saved
with **Save Dataset**. Re-run anything else; with native analysis that is
quick.

## Where the analysis runs

Served locally, the app sends its calculations to the pydvma server
instead of running them in the browser. The results are identical (it is
the same code), but large sonograms and wavelet transforms that the
browser can't fit in memory now work, everything runs at full speed, and
**Stop** interrupts a long calculation immediately.

If the server can't do the analysis, for example because the app and the
installed pydvma are different versions, the app falls back to the
browser automatically and says so. While a calculation runs, hover over
the busy indicator at the top of the app to see which engine it is using. To choose one yourself,
add `?enginehost=native` or `?enginehost=pyodide` to the address.
