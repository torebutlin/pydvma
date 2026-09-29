# Quick Start

There are four ways in. Pick the one that matches what you want to do;
each takes a few minutes.

1. [In the browser, nothing installed](#1-in-the-browser-nothing-installed):
   analyse a saved file, or measure with your computer's soundcard.
2. [From a Jupyter notebook](#2-from-a-jupyter-notebook-dvmalaunch):
   record in the web logger, analyse in Python. The usual lab route.
3. [On a lab PC, without a notebook](#3-on-a-lab-pc-without-a-notebook):
   the web logger with direct access to lab hardware.
4. [Scripting in Python](#4-scripting-in-python): record and analyse
   entirely from code.

Routes 2 to 4 need pydvma [installed](installation.md) on your machine.

## 1. In the browser, nothing installed

1. Open **[torebutlin.github.io/pydvma/app/](https://torebutlin.github.io/pydvma/app/)**.
2. **To analyse a saved file**, press **Load Data** and pick a `.dvma`,
   `.npy` or `.mat` file.<br>
   **To measure**, open **Setup**, choose your input, sample rate,
   channels and duration, then press **Log Data** on **Acquire**. The
   browser asks for microphone permission the first time.
3. Look at the results in the **Time**, **Frequency**, **TF** and
   **Sonogram** stages, and fit modes in **Fit**.
4. Press **Save Dataset** to keep a `.dvma` file you can reopen anywhere.

Everything runs inside your browser, and your files never leave your
machine. The browser can't reach NI hardware and may process the
soundcard signal, so use route 2 or 3 for calibrated or NI
measurements. The [Web Logger guide](../web-logger/index.md) covers
every stage.

## 2. From a Jupyter notebook: `dvma.launch`

`dvma.launch` opens the web logger from your notebook. You record
point-and-click in the browser, and every capture is available back in
Python.

1. **Start Jupyter** in the folder where you want to keep your data:

    ```bash
    conda activate pydvma
    cd path/to/your/folder
    jupyter lab
    ```

2. **Launch the web logger** from a notebook cell:

    ```python
    import pydvma as dvma
    %matplotlib widget

    settings = dvma.MySettings(channels=2, fs=8000, stored_time=2.0)
    session = dvma.launch(settings)
    ```

    A browser tab opens on the web logger with **Setup** already filled
    in from `settings` (the address is also printed, in case the tab
    doesn't open). The notebook stays usable while it runs.

3. **Record in the browser.** Check your signals on **Live**, then press
   **Log Data** on **Acquire**, as many times as you need. Each capture
   reaches the session as soon as it is taken; you don't need to save
   first.

4. **Pull the captures into the notebook** whenever you like:

    ```python
    data = session.data                 # a DataSet with every capture so far
    data.calculate_tf_set(ch_in=0, window='hann')
    data.plot_tf_data()
    ```

5. **Save**, and **close** the session when you have finished:

    ```python
    dvma.save_data(data, filename='my_test.dvma')
    session.close()
    ```

`settings` only pre-fills Setup; you can change anything there in the
browser. With no `device` given, pydvma records from your computer's
default input. For NI hardware, let pydvma suggest safe settings for the
device (index 0 here; `dvma.list_available_devices()` shows the
options):

```python
settings = dvma.MySettings(channels=4, stored_time=2.0,
                           **dvma.suggest_ni_settings(0))
```

The **[template notebook](https://raw.githubusercontent.com/torebutlin/pydvma/master/pydvma_template.ipynb)**
(right-click, *Save link as…*) has these cells ready to run.
[Running locally](../web-logger/running-locally.md) explains the session
in full, including sending data back to the app with `session.push`.

## 3. On a lab PC, without a notebook

From a terminal:

```bash
pydvma-serve --open
```

This serves the same web logger on your own machine and opens it in your
browser, with direct access to soundcards, audio interfaces and NI
hardware. Everything then works as in route 1. Useful options:

- `pydvma-serve --list-devices` shows what is plugged in, then exits.
- `pydvma-serve --driver nidaq --open` makes NI the default device.
- `pydvma-serve --settings lab.json --open` pre-fills Setup from a file.

See [Running locally](../web-logger/running-locally.md) for the details.

## 4. Scripting in Python

```python
import pydvma as dvma

settings = dvma.MySettings(channels=2, fs=8000, stored_time=2.0)
data = dvma.log_data(settings)      # records for stored_time seconds

data.calculate_fft_set(window='hann')
data.calculate_tf_set(ch_in=0, window='hann')
data.plot_time_data()
data.plot_tf_data()

dvma.save_data(data, filename='my_test.dvma')
```

`log_data` records from your default soundcard and returns a `DataSet`.
To reopen a saved file, use `data = dvma.load_data(filename='my_test.dvma')`.
No hardware to hand? `data = dvma.create_test_impulse_data()` gives you
a synthetic impulse test to practise on. The same code runs with nothing
installed in [JupyterLite](https://torebutlin.github.io/pydvma/lite/)
(analysis only, no recording).

## Next steps

- [Python basics](basic-usage.md): the data model and settings behind
  the code above.
- [Web Logger](../web-logger/index.md): each stage of the app in detail.
- [Examples](../examples/basic.md): complete worked measurements.
