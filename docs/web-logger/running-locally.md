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
| `--save-dir DIR` | the app's starting [working folder](export.md#where-files-go), where Save and Load open (default: the folder you run the command in) |
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

Saves from the app go into the notebook's own folder by default; see
[where files go](export.md#where-files-go). `session.save_dir` is that
folder, and `launch(save_dir=...)` starts somewhere else.

`launch` takes a few optional arguments: `open_browser=False` starts
without opening a tab, and `port=8760` uses a fixed port (for a
bookmark) instead of a free one chosen for you. Called with no settings,
`dvma.launch()` opens with the app's defaults. `window=` and
`tf_averaging=` set the analysis defaults for captures, as described
under [changing settings](#changing-settings-from-the-notebook) below.

### 2. Record in the browser

Use the app as usual: check signals on **Live**, then press **Log Data**
on **Acquire**. Each capture reaches the session as soon as it is taken,
so the notebook can see it without you saving anything.

### Changing settings from the notebook

A lab often needs different settings as it goes on: a short noise
capture, then a long one, then the hammer with the trigger armed. Keep
the app open and change its settings from the notebook:

```python
settings = dvma.MySettings(channels=2, fs=3000, stored_time=6,
                           pretrig_samples=100, pretrig_threshold=0.25,
                           device_driver='nidaq')
session.apply_settings(settings, window=None, tf_averaging='across')
```

```text
logger settings: 3000 Hz, 2 ch, 6 s, trigger armed on ch 0 at 0.25 V, window none, TF averaging across (applied in 1 app tab)
```

Every open app tab fills in **Setup** and the trigger from `settings`,
the same way `launch` does at the start, and shows a note saying the
settings came from the notebook. A tab you open or reload later starts
from them too. If no tab is open, the line says so and the settings
apply when you open one.

- **The new settings replace the old ones whole.** A setting left at
  `None` clears that setting in the app. `pretrig_samples` defaults to
  `None`, so going back from the hammer settings to a noise capture
  disarms the trigger with no extra step:

    ```python
    session.apply_settings(dvma.MySettings(channels=2, fs=3000, stored_time=30,
                                           device_driver='nidaq'),
                           window='hann', tf_averaging='within')
    ```

- **Nothing changes during a capture.** While the app is logging, armed
  and waiting for a trigger, or part way through a **Nonlin** run, the
  call raises an error and the app keeps its settings. Let the capture
  finish, or press **Stop**, and run the cell again.
- **The input stream is reopened when it needs to be**, as it is after
  you edit Setup by hand: a new sample rate, channel count, device or NI
  range takes effect at the next capture, or when you next start the
  live monitor.
- **`window`** sets the analysis window on both the **Frequency** and
  **TF** cards: `'hann'`, `'hamming'`, or `None` for no window (as
  everywhere in pydvma; `'none'` works too). **`tf_averaging`** sets the
  TF averaging: `'within'` averages frames inside each capture (for
  noise), `'across'` averages across the captures in the app (for
  repeated hammer hits), and `'none'` uses a single frame. Both apply to
  the captures you take from then on, and to loaded data that records no
  analysis settings, such as a file written from Python. Data already in
  the app keeps its own, and so does a file saved from the app, which
  always records its window and averaging: it reopens exactly as it was
  saved, and an *across sets* default never pulls it into an average.
  Leave either out and the app keeps its current choice;
  `session.apply_settings(window='hann')`, with no settings, changes only
  the window.

`pretrig_threshold=None`, the default, means 5 % of the input's full
scale: 0.25 V on a ±5 V NI range. That is also the app's default, and
the default when Python records with `log_data`.

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

The pre-fill covers the sample rate, channels, duration, device,
pretrigger (`pretrig_samples`, `pretrig_threshold`, `pretrig_channel`,
`pretrig_timeout`), the NI settings (`VmaxNI`, `output_VmaxNI`,
`NI_mode`, `input_channels_spec`, and `iepe_excit_current_A`, whose
first value applies to every channel), and the output device and
channels. Other fields are ignored: in particular the input gain and
full scale (`input_gain_db`, `VmaxSC`) and channel sensitivities, which
you set in Setup and the Calibrate dialog. The file is read once when
the app opens and only fills in starting values; anything you change in
Setup afterwards stays changed.

A setting the file leaves out keeps the app's own value. A setting
written as `null` clears it to the app's default (`"pretrig_samples":
null` leaves the trigger disarmed, `"pretrig_threshold": null` uses 5 %
of full scale). `dvma.launch` always sends every setting, including the
ones that are `None`, which is how `session.apply_settings` can disarm a
trigger.

Two more keys set the analysis defaults for captures, as `window=` and
`tf_averaging=` do in Python:

```json
{
  "analysis_window": "none",
  "tf_averaging": "across"
}
```

A JSON file can also pre-fill the output signal, which `MySettings` has
no fields for:

```json
{
  "output": {"type": "sweep", "amp": 0.5, "f1": 10, "f2": 1000, "duration": 2.0}
}
```

`type` is `sweep`, `uniform` or `gaussian`.

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
