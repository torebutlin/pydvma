# Installation

!!! tip "You may not need to install anything"
    The **[browser app](https://torebutlin.github.io/pydvma/app/)**
    analyses saved files and records from your computer's soundcard, and
    **[JupyterLite](https://torebutlin.github.io/pydvma/lite/)** runs
    pydvma in a browser notebook. Neither needs an install. Install
    pydvma when you want lab hardware (an audio interface or NI-DAQ),
    `dvma.launch` from a notebook, or Python on your own machine.

## Install

pydvma needs Python 3.11 or later. If you don't have Python yet,
install [Anaconda](https://www.anaconda.com/download) (or Miniconda).
Then open **Anaconda Prompt** (Windows) or a terminal (macOS, Linux) and
run:

```bash
conda create -n pydvma python=3.13
conda activate pydvma
pip install "pydvma[full]" jupyterlab ipympl
```

This gives you everything for lab use: soundcard and NI acquisition, the
`pydvma-serve` browser bridge, and JupyterLab with interactive plots.
Every new terminal needs `conda activate pydvma` first. To install into
an environment you already have instead, run only the last line.

To upgrade later:

```bash
pip install --upgrade "pydvma[full]"
```

Keep the quotes around `"pydvma[full]"`: without them, zsh (the macOS
default shell) reports `no matches found`.

### Choosing extras

`pydvma[full]` is the simple choice. If you want a smaller install, the
pieces are separate:

| Install | What it adds |
| ------- | ------------ |
| `pip install pydvma` | The analysis core: data structures, FFT/TF/modal analysis, plotting, file I/O. No hardware drivers; runs anywhere, including in the browser. |
| `pip install "pydvma[soundcard]"` | Soundcard and audio-interface acquisition (`sounddevice`). |
| `pip install "pydvma[ni]"` | National Instruments acquisition (`nidaqmx`); also needs the NI-DAQmx driver, [below](#national-instruments-hardware). |
| `pip install "pydvma[serve]"` | The `pydvma-serve` bridge and `dvma.launch` (`websockets`). |
| `pip install "pydvma[full]"` | All of the above. |

Extras combine, for example `pip install "pydvma[serve,soundcard]"`.
The bridge on its own records nothing: pair `serve` with the backend
you use. A backend that is not installed is skipped **without any
error**; it simply doesn't appear in the device list. If a device is
missing, check its extra first.

## National Instruments hardware

NI hardware needs NI's own driver as well as the Python package. It is
available for Windows and Linux only; there is no NI-DAQmx for macOS,
where soundcard acquisition and all the analysis still work.

1. Install the **[NI-DAQmx driver](https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html)**
   (the latest version for your OS).
2. Install the Python package, if `pydvma[full]` didn't already:
   `pip install "pydvma[ni]"`.

## Check it works

```bash
pydvma-serve --list-devices
```

This lists every input device pydvma can see, grouped by physical
device, with the recommended backend marked and whether its voltage
scale is known. If a whole driver's devices are missing, its extra (or,
for NI, the NI-DAQmx driver) is not installed. The same listing is
available from Python as `dvma.list_available_devices()`.

Then carry on with the **[Quick Start](quickstart.md)**.

## Troubleshooting

**`No module named 'pydvma'`**: pydvma is installed in a different
environment from the one you are running. Run `conda activate pydvma`
(or select that environment as your notebook kernel) and try again.

**Plots don't appear in Jupyter**: `%matplotlib widget` needs `ipympl`
installed in the same environment as the kernel. Install it, then
restart the kernel.

**A device is missing, or `pydvma-serve` records a test signal instead
of your device**: run `pydvma-serve --list-devices` and check the
[extras](#choosing-extras). With no usable soundcard, `pydvma-serve`
falls back to a built-in test-signal generator.

**`pip install "pydvma[qt]"` fails**: the desktop Qt logger was removed
in 2.0.0, and the web logger replaces it. See
[From the Qt logger](../web-logger/migration.md).

## Installing from source

To work on pydvma itself:

```bash
git clone https://github.com/torebutlin/pydvma.git
cd pydvma
pip install -e ".[full]"
```

See [Contributing](../contributing.md) for the development workflow.
