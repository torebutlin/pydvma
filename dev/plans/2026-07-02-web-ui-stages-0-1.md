# pydvma Web UI Stages 0–1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Stage 0 (packaging split), Stage 0.5 (`.dvma` container file format), and Stage 1 (JupyterLite no-install analysis site) from `dev/2026-07-01-web-ui-design.md`.

**Architecture:** All work is additive or test-guarded; the Qt GUI is frozen. Base `pip install pydvma` becomes pure-Python (numpy/scipy/matplotlib/peakutils) with Qt/hardware as extras. The default save format becomes a zip container (`manifest.json` + plain `.npy` arrays, no pickle) with the legacy pickle reader kept forever. A JupyterLite site is built from `lite/` and deployed next to the MkDocs docs on GitHub Pages.

**Tech Stack:** setuptools/pyproject.toml, zipfile+json+numpy (no new runtime deps), jupyterlite-core + jupyterlite-pyodide-kernel (build-time only), existing pytest suite.

**Constraints (from spec — hold at every task):**
- Public API unchanged: `import pydvma as dvma; dvma.MySettings / log_data / load_data / Logger` all work as today.
- No file moves; class module paths stay (`pydvma.datastructure.DataSet` etc.).
- Existing suite (157 passed / 4 hardware-skipped on Mac) stays green: run `python -m pytest tests/ -q` before each commit.
- Environment: Mac, `/opt/anaconda3/bin/python3` (3.13), repo installed editably.

---

## File structure

```
pyproject.toml                    # NEW — replaces setup.py
setup.py                          # DELETED (Task 1)
pydvma/container.py               # NEW — .dvma v2 serialisers (Task 5)
pydvma/file.py                    # MODIFIED — sniffing load, v2 default save (Task 6)
pydvma/plotting.py                # MODIFIED — delete dead Qt imports (Task 7)
pydvma/options.py                 # MODIFIED — seaborn fallback in set_plot_colours (Task 8)
pydvma/__init__.py                # MODIFIED — helpful ImportError for lazy names (Task 3)
tests/test_packaging.py           # NEW — version sync + core import surface (Tasks 1–3)
tests/test_container.py           # NEW — v2 round-trips + legacy load (Tasks 4–6)
tests/data/reference_dataset_v140.npy   # NEW — checked-in legacy pickle file (Task 4)
dev/make_reference_dataset.py     # NEW — generator for the above (Task 4)
lite/jupyter_lite_config.json     # NEW (Task 9)
lite/content/pydvma_analysis.ipynb# NEW (Task 10)
.github/workflows/docs.yml        # MODIFIED — build lite into site/lite (Task 11)
requirements-docs.txt             # MODIFIED — add jupyterlite packages (Task 11)
.gitignore                        # MODIFIED — !tests/data/*.npy, lite build dirs (Tasks 4, 9)
```

---

## Stage 0 — packaging

### Task 1: Replace setup.py with pyproject.toml

**Files:** Create `pyproject.toml`; delete `setup.py`; create `tests/test_packaging.py`

- [ ] **Step 1: Write the failing version-sync test**

Create `tests/test_packaging.py`:

```python
# -*- coding: utf-8 -*-
"""Packaging guarantees: version sync and the core import surface.

The core import-surface tests enforce the *logical* core/GUI split
from dev/2026-07-01-web-ui-design.md: `import pydvma` must succeed
with no Qt binding, no sounddevice, no nidaqmx and no seaborn
present. They simulate missing packages with a meta-path blocker in
a subprocess rather than a separate venv, so they run in the normal
suite.
"""
import pathlib
import re
import subprocess
import sys

import pydvma

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_pyproject_version_matches_datastructure():
    # pyproject.toml is the packaging truth; datastructure.VERSION is
    # stamped into every saved file. They must agree (this test
    # replaces the old "keep in sync" comment discipline).
    import tomllib
    with open(REPO_ROOT / 'pyproject.toml', 'rb') as f:
        pyproject = tomllib.load(f)
    assert pyproject['project']['version'] == pydvma.datastructure.VERSION
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: FAIL with `FileNotFoundError` (no pyproject.toml yet).

- [ ] **Step 3: Create `pyproject.toml` and delete `setup.py`**

Create `pyproject.toml` (version stays 1.4.0 for now — bump is Task 13):

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "pydvma"
version = "1.4.0"          # keep in sync with pydvma/datastructure.py (enforced by tests/test_packaging.py)
description = "Python package for dynamics and vibration measurement and analysis"
readme = "README.md"
license = { text = "BSD 3-Clause License" }
authors = [{ name = "Tore Butlin", email = "tb267@cam.ac.uk" }]
requires-python = ">=3.9"
# Base install is the pure-Python core: data structures, analysis,
# file I/O, matplotlib plotting. It must import and work with no Qt
# binding and no hardware driver present (runs under pyodide).
dependencies = [
    "numpy",
    "scipy",
    "matplotlib",
    "peakutils",
]

[project.optional-dependencies]
# GUI (Logger / Oscilloscope / PlotData interactivity)
qt = ["qtpy", "PyQt5", "pyqtgraph", "seaborn"]
# acquisition backends
soundcard = ["sounddevice"]
ni = ["nidaqmx"]
full = ["pydvma[qt,soundcard,ni]"]

[project.urls]
Homepage = "https://github.com/torebutlin/pydvma"

[tool.setuptools]
packages = ["pydvma"]

[tool.setuptools.package-data]
pydvma = ["*.png"]
```

Then `git rm setup.py`.

Check the icon ships: `ls pydvma/*.png` — if nothing is found, gui.py's `_resource_files('pydvma').joinpath('icon.png')` resolves against the repo-root `icon.png` only in editable installs; in that case copy it in: `git mv icon.png pydvma/icon.png` is **wrong** (root icon may be referenced elsewhere) — instead `cp icon.png pydvma/icon.png && git add pydvma/icon.png`.

- [ ] **Step 4: Reinstall editably and verify test + suite pass**

Run:
```bash
python -m pip install -e . --no-deps
python -m pytest tests/test_packaging.py -v
python -m pytest tests/ -q
```
Expected: packaging test PASS; suite green (157 passed / 4 skipped, plus the new test).

- [ ] **Step 5: Verify a wheel builds and is pure Python**

```bash
python -m pip wheel . --no-deps -w /tmp/pydvma_wheel_check
ls /tmp/pydvma_wheel_check
```
Expected: exactly one `pydvma-1.4.0-py3-none-any.whl` (the `py3-none-any` tag is what pyodide/micropip needs).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git rm setup.py
git commit -m "build: pyproject.toml with core deps + qt/soundcard/ni extras

Base install is now pure-Python (numpy/scipy/matplotlib/peakutils);
Qt stack, sounddevice and nidaqmx move to extras. Fixes the packaging
bug where nidaqmx was hard-required and qtpy/pyqt5 were missing."
```

### Task 2: Core import-surface test

**Files:** Modify `tests/test_packaging.py`

- [ ] **Step 1: Add the blocked-import subprocess test**

Append to `tests/test_packaging.py`:

```python
# Names that must NOT be needed to import pydvma or use its core.
_BLOCKED = "qtpy,PyQt5,PySide2,PySide6,pyqtgraph,sounddevice,nidaqmx,seaborn,qdarktheme"

_BLOCKER_PRELUDE = """
import sys
BLOCKED = set({blocked!r}.split(','))
class _Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in BLOCKED:
            raise ImportError(name + ' is blocked: core pydvma must not need it')
sys.meta_path.insert(0, _Blocker())
import matplotlib
matplotlib.use('Agg')
""".format(blocked=_BLOCKED)


def _run_core_python(body):
    """Run `body` in a subprocess where the GUI/hardware packages are
    unimportable, simulating a base (no-extras) install."""
    return subprocess.run(
        [sys.executable, '-c', _BLOCKER_PRELUDE + body],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


def test_core_import_without_qt_or_hardware():
    result = _run_core_python("""
import pydvma as dvma
# public core names all resolve
settings = dvma.MySettings(channels=2, fs=1000, device_driver='mock')
td = dvma.create_test_impulse_data(noise_level=0)
data = dvma.DataSet(td)
data.calculate_fft_set()
data.calculate_tf_set()
assert len(data.tf_data_list) == 1
print('CORE-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'CORE-OK' in result.stdout


def test_core_mock_acquisition_without_qt_or_hardware():
    # The mock recorder path (used by the future web bridge tests)
    # must also be Qt/hardware-free.
    result = _run_core_python("""
import pydvma as dvma
settings = dvma.MySettings(channels=2, fs=1000, stored_time=0.1,
                           viewed_time=None, device_driver='mock')
data = dvma.log_data(settings)
assert data.time_data_list[0].time_data.shape[1] == 2
print('MOCK-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'MOCK-OK' in result.stdout
```

- [ ] **Step 2: Run them**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: both new tests PASS already (streams.py/options.py guard their hardware imports today). If either FAILS, the stderr shows which module pulled a blocked import at import time — fix by deferring that import into the function that needs it (same pattern as `options.set_plot_colours`), then re-run.

- [ ] **Step 3: Commit**

```bash
git add tests/test_packaging.py
git commit -m "test: core import surface needs no Qt/sounddevice/nidaqmx"
```

### Task 3: Helpful ImportError for lazy GUI names

**Files:** Modify `pydvma/__init__.py:38-53`; modify `tests/test_packaging.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
def test_lazy_gui_names_raise_helpful_error_without_qt():
    result = _run_core_python("""
import pydvma as dvma
try:
    dvma.Logger
except ImportError as e:
    print('MSG:', e)
""")
    assert result.returncode == 0, result.stderr
    assert 'pip install pydvma[qt]' in result.stdout
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_packaging.py::test_lazy_gui_names_raise_helpful_error_without_qt -v`
Expected: FAIL — the raw `ImportError: qtpy is blocked...` propagates without the extras hint.

- [ ] **Step 3: Wrap the lazy import**

In `pydvma/__init__.py`, replace the body of `__getattr__`:

```python
def __getattr__(name):
    mod_name = _LAZY_NAMES.get(name)
    if mod_name is not None:
        import importlib
        try:
            mod = importlib.import_module(mod_name, __name__)
        except ImportError as e:
            raise ImportError(
                'pydvma.{} needs the GUI dependencies (qtpy, PyQt5, '
                'pyqtgraph). Install them with: pip install pydvma[qt]. '
                'Original error: {}'.format(name, e)
            ) from e
        return getattr(mod, name)
    raise AttributeError(
        'module {!r} has no attribute {!r}'.format(__name__, name)
    )
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_packaging.py tests/test_gui_logic.py -q` (gui tests confirm the happy path still lazy-loads).
Expected: PASS.

```bash
git add pydvma/__init__.py tests/test_packaging.py
git commit -m "feat: point at pip install pydvma[qt] when GUI deps missing"
```

---

## Stage 0.5 — `.dvma` container format

### Task 4: Pin the legacy pickle format with a checked-in reference file

Run this task BEFORE touching `file.py` — the reference file must be written by today's code.

**Files:** Create `dev/make_reference_dataset.py`, `tests/data/reference_dataset_v140.npy`; modify `.gitignore`, `tests/test_container.py` (new)

- [ ] **Step 1: Write the generator script**

Create `dev/make_reference_dataset.py`:

```python
# -*- coding: utf-8 -*-
"""Generate tests/data/reference_dataset_v140.npy — a legacy pickle
save from pydvma 1.4.0, checked in so the legacy reader path is
pinned forever. Run once from the repo root:

    python dev/make_reference_dataset.py

Regenerating it later (with newer code) would defeat the point; only
rerun if you deliberately need a new reference epoch.
"""
import os
import numpy as np
import pydvma as dvma

assert dvma.datastructure.VERSION == '1.4.0', 'reference must be written by 1.4.0'

td = dvma.create_test_impulse_data(noise_level=0)
td.test_name = 'reference impulse'
td.units = ['N', 'm/s']
data = dvma.DataSet(td)
data.calculate_fft_set()
data.calculate_tf_set(ch_in=0)
data.calculate_cross_spectrum_matrix_set(window='hann')
data.calculate_sono_set()

out = os.path.join('tests', 'data', 'reference_dataset_v140.npy')
os.makedirs(os.path.dirname(out), exist_ok=True)
data.save_data(out)
print('wrote', out)
```

- [ ] **Step 2: Un-ignore the reference file**

In `.gitignore`, directly below the `*.npy` line, add:

```
!tests/data/*.npy
```

- [ ] **Step 3: Generate and sanity-check the file**

```bash
python dev/make_reference_dataset.py
python -c "
import pydvma as dvma
d = dvma.load_data(filename='tests/data/reference_dataset_v140.npy')
assert len(d.time_data_list) == 1 and len(d.tf_data_list) == 1
print('reference OK:', d.pydvma_version)
"
```
Expected: `reference OK: 1.4.0`.

- [ ] **Step 4: Write the legacy-load regression test**

Create `tests/test_container.py`:

```python
# -*- coding: utf-8 -*-
"""Tests for the .dvma container format (format v2) and the legacy
pickle reader. See dev/2026-07-01-web-ui-design.md, Stage 0.5."""
import pathlib

import numpy as np
import pytest

import pydvma as dvma

DATA_DIR = pathlib.Path(__file__).resolve().parent / 'data'
REFERENCE_V140 = DATA_DIR / 'reference_dataset_v140.npy'


def test_legacy_pickle_file_still_loads():
    # Contract: files saved by <=1.4.0 remain loadable forever.
    d = dvma.load_data(filename=str(REFERENCE_V140))
    assert d.pydvma_version == '1.4.0'
    assert len(d.time_data_list) == 1
    assert d.time_data_list[0].units == ['N', 'm/s']
    assert len(d.freq_data_list) == 1
    assert len(d.tf_data_list) == 1
    assert len(d.cross_spec_data_list) == 1
    assert len(d.sono_data_list) == 1
    assert np.isfinite(d.tf_data_list[0].tf_data).all()
```

- [ ] **Step 5: Run it, then commit**

Run: `python -m pytest tests/test_container.py -v`
Expected: PASS.

```bash
git add dev/make_reference_dataset.py tests/data/reference_dataset_v140.npy tests/test_container.py .gitignore
git commit -m "test: pin legacy 1.4.0 pickle save format with reference file"
```

### Task 5: `pydvma/container.py` — v2 serialisers

**Files:** Create `pydvma/container.py`; modify `tests/test_container.py`

- [ ] **Step 1: Write the failing round-trip tests**

Append to `tests/test_container.py`:

```python
from pydvma import container, datastructure, options


def _make_full_dataset():
    td = dvma.create_test_impulse_data(noise_level=0)
    td.test_name = 'roundtrip'
    td.units = ['N', 'm/s']
    data = dvma.DataSet(td)
    data.calculate_fft_set()
    data.calculate_tf_set(ch_in=0)
    data.calculate_cross_spectrum_matrix_set(window='hann')
    data.calculate_sono_set()
    # a ModalData with one synthetic mode: [fn, zn, an*N, pn*N, rk*N, rm*N], N=2
    md = datastructure.ModalData(settings=td.settings)
    md.add_mode(np.array([100.0, 0.01, 1.0, 2.0, 0.1, 0.2, 0.0, 0.0, 0.0, 0.0]))
    data.add_to_dataset(md)
    return data


def test_v2_roundtrip_all_kinds(tmp_path):
    data = _make_full_dataset()
    path = tmp_path / 'roundtrip.dvma'
    container.save(data, str(path))
    loaded = container.load(str(path))

    td0, td1 = data.time_data_list[0], loaded.time_data_list[0]
    np.testing.assert_array_equal(td0.time_data, td1.time_data)
    np.testing.assert_array_equal(td0.time_axis, td1.time_axis)
    assert td1.units == ['N', 'm/s']
    assert td1.test_name == 'roundtrip'
    assert td1.unique_id == td0.unique_id            # uuid.UUID preserved
    assert td1.timestamp == td0.timestamp            # datetime preserved
    np.testing.assert_array_equal(td1.channel_cal_factors, td0.channel_cal_factors)

    fd0, fd1 = data.freq_data_list[0], loaded.freq_data_list[0]
    np.testing.assert_array_equal(fd0.freq_data, fd1.freq_data)  # complex survives
    assert fd1.id_link == td0.unique_id

    tf0, tf1 = data.tf_data_list[0], loaded.tf_data_list[0]
    np.testing.assert_array_equal(tf0.tf_data, tf1.tf_data)
    np.testing.assert_array_equal(tf0.tf_coherence, tf1.tf_coherence)
    assert tf1.flag_modal_TF == tf0.flag_modal_TF

    cs0, cs1 = data.cross_spec_data_list[0], loaded.cross_spec_data_list[0]
    np.testing.assert_array_equal(cs0.Pxy, cs1.Pxy)
    np.testing.assert_array_equal(cs0.Cxy, cs1.Cxy)

    sd0, sd1 = data.sono_data_list[0], loaded.sono_data_list[0]
    np.testing.assert_array_equal(sd0.sono_data, sd1.sono_data)

    md0, md1 = data.modal_data_list[0], loaded.modal_data_list[0]
    np.testing.assert_array_equal(md0.M, md1.M)
    np.testing.assert_array_equal(md0.fn, md1.fn)    # summary attrs rebuilt
    assert md1.channels == md0.channels

    assert loaded.pydvma_version == data.pydvma_version


def test_v2_roundtrip_settings(tmp_path):
    settings = options.MySettings(channels=3, fs=12800, device_driver='mock',
                                  channel_sensitivities=[0.1, 0.1, 0.0023])
    td = dvma.create_test_impulse_data(noise_level=0)
    td.settings = settings
    data = dvma.DataSet(td)
    path = tmp_path / 's.dvma'
    container.save(data, str(path))
    s1 = container.load(str(path)).time_data_list[0].settings
    assert isinstance(s1, options.MySettings)
    assert s1.fs == 12800 and s1.channels == 3
    assert isinstance(s1.channel_sensitivities, np.ndarray)
    np.testing.assert_array_equal(s1.channel_sensitivities,
                                  settings.channel_sensitivities)
    assert s1.input_vmax() == settings.input_vmax()  # methods work on restored object


def test_v2_roundtrip_none_coherence(tmp_path):
    # TfData from stepped-sine / matlab import has tf_coherence=None
    settings = options.MySettings(channels=2, device_driver='mock')
    tf = datastructure.TfData(np.arange(10.0), np.ones((10, 1), dtype=complex),
                              None, settings)
    data = dvma.DataSet(tf)
    path = tmp_path / 'nc.dvma'
    container.save(data, str(path))
    tf1 = container.load(str(path)).tf_data_list[0]
    assert tf1.tf_coherence is None
    np.testing.assert_array_equal(tf1.tf_data, tf.tf_data)


def test_v2_no_pickle_anywhere(tmp_path):
    # every .npy member must load with allow_pickle=False
    import io
    import zipfile
    data = _make_full_dataset()
    path = tmp_path / 'p.dvma'
    container.save(data, str(path))
    with zipfile.ZipFile(str(path)) as zf:
        names = zf.namelist()
        assert 'manifest.json' in names
        for name in names:
            if name.endswith('.npy'):
                np.load(io.BytesIO(zf.read(name)), allow_pickle=False)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest tests/test_container.py -v`
Expected: the four new tests ERROR with `ImportError: cannot import name 'container'`; the legacy test still passes.

- [ ] **Step 3: Implement `pydvma/container.py`**

```python
# -*- coding: utf-8 -*-
"""The .dvma container file format (format v2).

A ``.dvma`` file is a zip archive holding ``manifest.json`` plus one
plain ``.npy`` file (saved with ``allow_pickle=False``) per array
attribute. Unlike the legacy ``.npy`` pickle format, it contains no
executable content, is versioned, and is independent of pydvma's
class layout — the manifest schema, not the Python object graph, is
the contract. It is also readable outside Python (unzip + any npy
parser), which the browser interface relies on.

Layout::

    manifest.json                    # schema below
    arrays/0000_time_axis.npy        # one member per array attribute
    arrays/0000_time_data.npy
    arrays/0001_freq_axis.npy
    ...

Manifest schema (format_version 1)::

    {
      "format": "dvma-dataset",
      "format_version": 1,
      "pydvma_version": "<version that wrote the file>",
      "storage": "npy",              # extension point for future
                                     # HDF5 / chunked backends
      "items": [
        {
          "kind": "TimeData",        # class name in datastructure.py
          "arrays": {"time_axis": "arrays/0000_time_axis.npy", ...},
          "meta": {...},             # scalars: see _META_FIELDS
          "settings": {...} | null   # MySettings.__dict__, JSON-encoded
        },
        ...
      ]
    }

Scalar values use small type tags so JSON round-trips losslessly:
``{"__uuid__": "..."}, {"__datetime__": "<isoformat>"},
{"__array__": [...]}``; everything else is a plain JSON value.

Use `save` / `load`; `file.save_data` and `file.load_data` call them
for you (load sniffs the format from the file's magic bytes, so old
pickle ``.npy`` files keep working).
"""
import datetime
import io
import json
import uuid
import zipfile

import numpy as np

from . import datastructure
from . import options

FORMAT_NAME = 'dvma-dataset'
FORMAT_VERSION = 1

# Array attributes per data kind. Order defines member naming only.
_ARRAY_FIELDS = {
    'TimeData':      ['time_axis', 'time_data'],
    'FreqData':      ['freq_axis', 'freq_data'],
    'CrossSpecData': ['freq_axis', 'Pxy', 'Cxy'],
    'TfData':        ['freq_axis', 'tf_data', 'tf_coherence'],
    'SonoData':      ['time_axis', 'freq_axis', 'sono_data'],
    'ModalData':     ['M'],
    'MetaData':      [],
}

# Scalar/metadata attributes per data kind.
_META_FIELDS = {
    'TimeData':      ['units', 'channel_cal_factors', 'test_name',
                      'timestamp', 'timestring', 'unique_id', 'id_link'],
    'FreqData':      ['units', 'channel_cal_factors', 'test_name',
                      'timestamp', 'timestring', 'id_link'],
    'CrossSpecData': ['units', 'channel_cal_factors', 'test_name',
                      'timestamp', 'timestring', 'id_link'],
    'TfData':        ['units', 'channel_cal_factors', 'test_name',
                      'timestamp', 'timestring', 'id_link', 'flag_modal_TF'],
    'SonoData':      ['units', 'channel_cal_factors', 'test_name',
                      'timestamp', 'timestring', 'id_link'],
    'ModalData':     ['units', 'test_name', 'timestamp', 'timestring',
                      'id_link', 'channels'],
    'MetaData':      ['units', 'channel_cal_factors', 'tf_cal_factors',
                      'timestamp', 'timestring'],
}

_KIND_CLASSES = {
    'TimeData': datastructure.TimeData,
    'FreqData': datastructure.FreqData,
    'CrossSpecData': datastructure.CrossSpecData,
    'TfData': datastructure.TfData,
    'SonoData': datastructure.SonoData,
    'ModalData': datastructure.ModalData,
    'MetaData': datastructure.MetaData,
}


def _encode_value(value):
    """JSON-encode one metadata value with type tags for uuid /
    datetime / ndarray so decoding is lossless."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return {'__uuid__': str(value)}
    if isinstance(value, datetime.datetime):
        return {'__datetime__': value.isoformat()}
    if isinstance(value, np.ndarray):
        return {'__array__': value.tolist()}
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [_encode_value(v) for v in value]
    return value  # str, int, float, bool


def _decode_value(value):
    if isinstance(value, dict):
        if '__uuid__' in value:
            return uuid.UUID(value['__uuid__'])
        if '__datetime__' in value:
            return datetime.datetime.fromisoformat(value['__datetime__'])
        if '__array__' in value:
            return np.array(value['__array__'])
    if isinstance(value, list):
        return [_decode_value(v) for v in value]
    return value


def _settings_to_dict(settings):
    if settings is None:
        return None
    return {k: _encode_value(v) for k, v in vars(settings).items()}


def _settings_from_dict(d):
    """Rebuild MySettings without re-running __init__ — the stored
    dict is the exact post-validation state, so re-validating could
    change it (and __init__ probes sound devices)."""
    if d is None:
        return None
    settings = options.MySettings.__new__(options.MySettings)
    for k, v in d.items():
        setattr(settings, k, _decode_value(v))
    return settings


def _write_array(zf, member, arr):
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr), allow_pickle=False)
    zf.writestr(member, buf.getvalue())


def _read_array(zf, member):
    return np.load(io.BytesIO(zf.read(member)), allow_pickle=False)


def save(dataset, filename):
    """Save a DataSet to `filename` in .dvma container format (v2).

    Writes a zip archive with a JSON manifest and pickle-free .npy
    members (see module docstring for the schema). Unlike the legacy
    format this is safe to share and open: loading executes no code.
    """
    manifest = {
        'format': FORMAT_NAME,
        'format_version': FORMAT_VERSION,
        'pydvma_version': getattr(dataset, 'pydvma_version',
                                  datastructure.VERSION),
        'storage': 'npy',
        'items': [],
    }
    data_lists = [dataset.time_data_list, dataset.freq_data_list,
                  dataset.cross_spec_data_list, dataset.tf_data_list,
                  dataset.modal_data_list, dataset.sono_data_list,
                  dataset.meta_data_list]
    with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        index = 0
        for data_list in data_lists:
            for item in data_list:
                kind = item.__class__.__name__
                entry = {'kind': kind, 'arrays': {}, 'meta': {}}
                for field in _ARRAY_FIELDS[kind]:
                    arr = getattr(item, field)
                    if arr is None:          # e.g. TfData.tf_coherence
                        continue
                    if kind == 'ModalData' and len(arr) == 0:
                        continue             # fresh ModalData has M == []
                    member = 'arrays/{:04d}_{}.npy'.format(index, field)
                    _write_array(zf, member, arr)
                    entry['arrays'][field] = member
                for field in _META_FIELDS[kind]:
                    entry['meta'][field] = _encode_value(
                        getattr(item, field, None))
                entry['settings'] = _settings_to_dict(
                    getattr(item, 'settings', None))
                manifest['items'].append(entry)
                index += 1
        zf.writestr('manifest.json', json.dumps(manifest, indent=1))
    return filename


def load(filename):
    """Load a .dvma container file and return the DataSet.

    Objects are rebuilt attribute-by-attribute (no constructors run),
    so timestamps, unique ids and settings come back exactly as
    saved. Only manifest-known fields are restored — the schema, not
    the class layout, defines the file.
    """
    with zipfile.ZipFile(filename, 'r') as zf:
        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
        if manifest.get('format') != FORMAT_NAME:
            raise ValueError(
                '{!r} is a zip file but not a dvma-dataset '
                '(manifest format={!r})'.format(filename,
                                                manifest.get('format')))
        dataset = datastructure.DataSet()
        for entry in manifest['items']:
            kind = entry['kind']
            cls = _KIND_CLASSES[kind]
            item = cls.__new__(cls)
            for field in _ARRAY_FIELDS[kind]:
                member = entry['arrays'].get(field)
                setattr(item, field, _read_array(zf, member)
                        if member is not None else None)
            if kind == 'ModalData' and 'M' not in entry['arrays']:
                item.M = []                  # matches fresh ModalData
            for field in _META_FIELDS[kind]:
                setattr(item, field, _decode_value(entry['meta'].get(field)))
            item.settings = _settings_from_dict(entry.get('settings'))
            if kind == 'ModalData' and 'M' in entry['arrays']:
                # rebuild the derived per-mode summary arrays
                from . import modal
                fn, zn, an, pn, rk, rm = modal.unpack_matrix(item.M)
                item.fn, item.zn, item.an, item.pn = fn, zn, an, pn
            dataset.add_to_dataset(item)
        dataset.pydvma_version = manifest.get('pydvma_version',
                                              dataset.pydvma_version)
    return dataset
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_container.py -v`
Expected: all PASS. If `test_v2_roundtrip_all_kinds` fails on ModalData, check `modal.unpack_matrix`'s exact return signature first (`python -c "import inspect, pydvma.modal as m; print(inspect.signature(m.unpack_matrix))"`).

- [ ] **Step 5: Full suite + commit**

Run: `python -m pytest tests/ -q`
Expected: green.

```bash
git add pydvma/container.py tests/test_container.py
git commit -m "feat: .dvma container format v2 (manifest + pickle-free npy)"
```

### Task 6: Wire the container into save_data / load_data

**Files:** Modify `pydvma/file.py:19-87`; modify `tests/test_container.py`

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_container.py`:

```python
def test_save_data_defaults_to_dvma(tmp_path):
    data = _make_full_dataset()
    # no extension -> .dvma appended, container format written
    out = dvma.save_data(data, filename=str(tmp_path / 'mytest'))
    assert out.endswith('.dvma')
    import zipfile
    assert zipfile.is_zipfile(out)
    loaded = dvma.load_data(filename=out)
    np.testing.assert_array_equal(loaded.time_data_list[0].time_data,
                                  data.time_data_list[0].time_data)


def test_save_data_explicit_npy_writes_legacy(tmp_path):
    # escape hatch: an explicit .npy filename keeps the old pickle
    data = _make_full_dataset()
    out = dvma.save_data(data, filename=str(tmp_path / 'legacy.npy'),
                         overwrite_without_prompt=True)
    assert out.endswith('.npy')
    import zipfile
    assert not zipfile.is_zipfile(out)
    loaded = dvma.load_data(filename=out)
    assert len(loaded.time_data_list) == 1


def test_load_data_sniffs_by_content_not_extension(tmp_path):
    # a .dvma file renamed to .npy must still load as v2 (content sniff)
    data = _make_full_dataset()
    from pydvma import container
    odd = tmp_path / 'renamed.npy'
    container.save(data, str(odd))
    loaded = dvma.load_data(filename=str(odd))
    assert len(loaded.tf_data_list) == 1


def test_dataset_save_data_method_roundtrip(tmp_path):
    # the labsheet idiom: dataset.save_data(...) then dvma.load_data(...)
    data = _make_full_dataset()
    out = data.save_data(filename=str(tmp_path / 'method_path'))
    loaded = dvma.load_data(filename=out)
    assert loaded.pydvma_version == data.pydvma_version
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest tests/test_container.py -v`
Expected: the four new tests FAIL (`save_data` still writes pickle / appends `.npy`).

- [ ] **Step 3: Rewrite `load_data` and `save_data` in `pydvma/file.py`**

Add `import zipfile` next to the existing imports, and `from . import container`. Replace the two functions:

```python
def load_data(parent=None, filename=None):
    '''
    Loads a dataset from `filename`, or displays a file dialog if no
    filename is given (the dialog needs the GUI extras installed).

    The format is sniffed from the file content, not the extension:

    - ``.dvma`` container files (zip magic bytes) — the default
      format since 1.5.0; safe, pickle-free (see `container`).
    - legacy ``.npy`` pickle saves from pydvma <= 1.4.0 — supported
      forever. **Trust model:** the legacy path uses
      ``np.load(allow_pickle=True)``, and unpickling can execute
      arbitrary code, so only open legacy .npy files you or your lab
      created. `.dvma` files do not have this caveat.
    - ``.mat`` (by extension) — JW-logger imports.
    '''
    if filename is None:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getOpenFileName(
            parent, 'Open data file', '', '*.dvma *.npy *.mat')
        if not filename:
            return None

    if zipfile.is_zipfile(filename):
        dataset = container.load(filename)
    elif filename.endswith('.mat'):
        dataset = import_from_matlab_jwlogger(filename=filename)
    elif filename.endswith('.npy'):
        d = np.load(filename, allow_pickle=True, fix_imports=True)
        dataset = d[0]
    else:
        print('Expecting file to be .dvma, .npy or .mat')
        return None

    return dataset


def save_data(dataset, parent=None, filename=None, overwrite_without_prompt=False):
    '''
    Saves a DataSet to 'filename.dvma' (container format v2 — a zip
    of manifest.json + pickle-free .npy arrays; see `container`), or
    provides a dialog if no filename is given.

    Legacy escape hatch: an explicit filename ending in ``.npy``
    writes the pre-1.5.0 pickle format instead, for workflows that
    still need it. New saves should prefer .dvma — it is safe to
    share (loading executes no code) and readable outside Python.

    Args:
       dataset (DataSet): An object of the class DataSet
       parent (optional): Parent widget for file dialog
       filename (str, optional): Output filename, dialog shown if not provided
       overwrite_without_prompt (bool, optional): If True, overwrite without asking
    '''
    # If filename not specified, provide dialog
    if filename is None:
        from qtpy.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(
            parent, 'Save dataset', '', '*.dvma')
        if not filename:
            print('Save cancelled')
            return None

    # If it exists, check if we should overwrite it (unless
    # overwrite_without_prompt is True)
    elif os.path.isfile(filename) and not overwrite_without_prompt:
        answer = input('File %r already exists. Overwrite? [y/n]: ' % filename)
        if answer != 'y':
            print('Save cancelled')
            return None
        print('Will overwrite existing file')

    if filename.endswith('.npy'):
        # legacy pickle format, kept for explicit opt-in only
        d = np.array([dataset])
        np.save(filename, d)
        print("Data saved (legacy pickle format) as %s" % filename)
        return filename

    if not filename.endswith('.dvma'):
        filename += '.dvma'
    container.save(dataset, filename)
    print("Data saved as %s" % filename)
    return filename
```

- [ ] **Step 4: Check nothing else in the repo hard-codes the old behaviour**

Run: `grep -rn "'\*\.npy" pydvma/ tests/ | grep -v test_container`
Expected: any remaining `*.npy` dialog filters are in `gui.py` — if hits appear there, change those filter strings to `'*.dvma *.npy *.mat'` (load) / `'*.dvma'` (save) to match. If no hits, nothing to do.

- [ ] **Step 5: Prove headless file I/O on a base install**

The spec requires `load_data(path)` to work with no GUI present.
Append to `tests/test_packaging.py`:

```python
def test_save_and_load_dvma_without_qt(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp('dvma_core')
    result = _run_core_python("""
import pydvma as dvma
td = dvma.create_test_impulse_data(noise_level=0)
data = dvma.DataSet(td)
out = dvma.save_data(data, filename={out!r})
loaded = dvma.load_data(filename=out)
assert loaded.time_data_list[0].time_data.shape == td.time_data.shape
print('FILEIO-OK')
""".format(out=str(out_dir / 'core_roundtrip')))
    assert result.returncode == 0, result.stderr
    assert 'FILEIO-OK' in result.stdout
```

Run: `python -m pytest tests/test_packaging.py::test_save_and_load_dvma_without_qt -v`
Expected: PASS (the QFileDialog import only fires when `filename is None`).

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: green — `tests/test_file.py` exercises the JW-logger export paths, which are untouched. If a test fails because it saved via `save_data` and expected `.npy`, update that test to the new `.dvma` expectation (the format change is the intended behaviour).

- [ ] **Step 7: Commit**

```bash
git add pydvma/file.py tests/test_container.py tests/test_packaging.py
git commit -m "feat: save_data writes .dvma by default; load_data sniffs format

Legacy pickle .npy files load forever (content sniffing, not
extension). Explicit .npy filename still writes legacy format as an
escape hatch. Documents the pickle trust model in load_data."
```

---

## Stage 1 — JupyterLite analysis site

### Task 7: Make `pydvma.plotting` importable without Qt

**Files:** Modify `pydvma/plotting.py:19-25`; modify `tests/test_packaging.py`

The qtpy and Qt5Agg imports at the top of plotting.py are referenced ONLY by the commented-out block in `PlotData.__init__` (lines 56-98) — verified 2026-07-02. Live code uses `plt.subplots` (standalone) or a caller-supplied canvas (GUI).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
def test_core_plotting_without_qt():
    # DataSet.plot_*_data must work on a base install (Agg backend) —
    # this is what pyodide/JupyterLite exercises.
    result = _run_core_python("""
import pydvma as dvma
td = dvma.create_test_impulse_data(noise_level=0)
data = dvma.DataSet(td)
data.calculate_tf_set()
p = data.plot_tf_data()
assert p.fig is not None
print('PLOT-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'PLOT-OK' in result.stdout
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_packaging.py::test_core_plotting_without_qt -v`
Expected: FAIL — stderr shows `ImportError: qtpy is blocked...` raised from `pydvma/plotting.py`.

- [ ] **Step 3: Delete the dead imports**

In `pydvma/plotting.py` delete lines 19-25:

```python
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from qtpy.QtWidgets import QWidget, QLabel, QVBoxLayout
from qtpy.QtCore import Qt
from qtpy import QtGui
```

Also delete the commented-out block in `PlotData.__init__` that referenced them (lines 56-98 region, the `# self.plot_window = QWidget()` block) — it is the only reason those imports existed.

- [ ] **Step 4: Run the plotting + GUI tests**

Run: `python -m pytest tests/test_packaging.py tests/test_plotting.py tests/test_gui_logic.py -v`
Expected: all PASS (the GUI passes its own canvas into PlotData; nothing in the live path used those imports).

- [ ] **Step 5: Commit**

```bash
git add pydvma/plotting.py tests/test_packaging.py
git commit -m "fix: drop dead Qt imports from plotting.py (pyodide-compatible)"
```

### Task 8: seaborn fallback in `set_plot_colours`

**Files:** Modify `pydvma/options.py:528-553`; modify `tests/test_packaging.py`

`PlotData.update` calls `options.set_plot_colours`, which imports seaborn for >1 channel. seaborn is a `[qt]` extra, so the base install needs a fallback.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_packaging.py`:

```python
def test_set_plot_colours_without_seaborn():
    result = _run_core_python("""
import numpy as np
from pydvma import options
c1 = options.set_plot_colours(1)
c4 = options.set_plot_colours(4)
assert c4.shape[0] == 4 and c4.shape[1] in (3, 4)
assert (c4 >= 0).all() and (c4 <= 255).all()
# distinct hues, not all the same colour
assert len({tuple(row[:3]) for row in c4}) == 4
print('COLOURS-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'COLOURS-OK' in result.stdout
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest tests/test_packaging.py::test_set_plot_colours_without_seaborn -v`
Expected: FAIL with blocked `seaborn` import (the >1-channel branch).

- [ ] **Step 3: Add the fallback**

In `pydvma/options.py`, replace the `else:` branch of `set_plot_colours` (the seaborn call):

```python
    else:
        try:
            import seaborn as sns
            cmap = sns.hls_palette(channels, l=.3, s=1)
        except ImportError:
            # base install (no seaborn, e.g. pyodide): reproduce
            # sns.hls_palette(n, l=.3, s=1) with the stdlib — evenly
            # spaced hues (seaborn offsets them by 0.01) at fixed
            # lightness/saturation.
            import colorsys
            hues = (np.linspace(0, 1, channels, endpoint=False) + 0.01) % 1
            cmap = [colorsys.hls_to_rgb(h, 0.3, 1.0) for h in hues]
        c_list = np.array(np.array(cmap) * 255,dtype=int)
```

(Keep the existing `channels <= 1` branch — matplotlib-only — unchanged, and update the module top-of-file comment that says seaborn is needed here.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_packaging.py tests/test_plotting.py -q`
Expected: PASS. Visually confirm parity (optional): with seaborn installed the palette is unchanged, so GUI colours don't shift.

- [ ] **Step 5: Commit**

```bash
git add pydvma/options.py tests/test_packaging.py
git commit -m "feat: stdlib colour fallback so plotting works without seaborn"
```

### Task 9: JupyterLite scaffold and local build

**Files:** Create `lite/jupyter_lite_config.json`; modify `.gitignore`, `requirements-docs.txt`

- [ ] **Step 1: Create the config**

Create `lite/jupyter_lite_config.json`:

```json
{
  "LiteBuildConfig": {
    "contents": ["content"]
  }
}
```

Create the content dir with a placeholder so the tree exists before Task 10: `mkdir -p lite/content lite/pypi`.

- [ ] **Step 2: gitignore the build artefacts**

Append to `.gitignore`:

```
# JupyterLite build artefacts (wheels dropped in by CI / local builds)
lite/pypi/
lite/.jupyterlite.doit.db
_lite_build/
```

- [ ] **Step 3: Add build deps**

Append to `requirements-docs.txt`:

```
jupyterlite-core
jupyterlite-pyodide-kernel
```

Install locally: `python -m pip install jupyterlite-core jupyterlite-pyodide-kernel`

- [ ] **Step 4: Build locally and verify it serves**

```bash
python -m pip wheel . peakutils --no-deps -w lite/pypi/
cd lite && jupyter lite build --output-dir ../_lite_build && cd ..
ls _lite_build/lab/index.html _lite_build/pypi/
```
Expected: `index.html` exists; `_lite_build/pypi/` contains the pydvma and peakutils wheels plus `all.json` (the piplite index — jupyterlite picks up wheels from `lite/pypi/` automatically).

Then serve and eyeball: `python -m http.server -d _lite_build 8899` → open `http://localhost:8899/lab/index.html`, open a Python (Pyodide) console, run `%pip install -q pydvma` then `import pydvma; print(pydvma.datastructure.VERSION)`. Expected: version prints with no error. Stop the server after.

- [ ] **Step 5: Commit**

```bash
git add lite/jupyter_lite_config.json .gitignore requirements-docs.txt
git commit -m "feat: JupyterLite scaffold (lite/) with bundled pydvma wheel"
```

### Task 10: Starter analysis notebook

**Files:** Create `lite/content/pydvma_analysis.ipynb` (via a small nbformat script — do not hand-write ipynb JSON)

- [ ] **Step 1: Generate the notebook**

Run this script (inline via `python - <<'EOF' ... EOF` or as a scratch file):

```python
import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.metadata.kernelspec = {'name': 'python', 'display_name': 'Python (Pyodide)',
                          'language': 'python'}
cells = []
cells.append(nbf.v4.new_markdown_cell(
"""# pydvma — analyse your lab data in the browser

Nothing to install: this page runs Python (via Pyodide) inside your
browser. Your files stay on your machine — nothing is uploaded.

**To analyse data you saved in the lab:**

1. Drag your saved file (`.dvma` or `.npy`) from your computer into
   the file browser on the left.
2. Run the cells below (`shift+enter`), editing the filename where
   marked.

The commands are the same ones used in the lab labsheets."""))
cells.append(nbf.v4.new_code_cell(
"""%pip install -q pydvma ipympl seaborn"""))
cells.append(nbf.v4.new_code_cell(
"""%matplotlib widget
import numpy as np
import pydvma as dvma"""))
cells.append(nbf.v4.new_markdown_cell(
"""## Load your data

Edit the filename to match the file you dragged in."""))
cells.append(nbf.v4.new_code_cell(
"""data = dvma.load_data(filename='my_data.dvma')   # <-- EDIT filename
data"""))
cells.append(nbf.v4.new_markdown_cell(
"""## Plot what you measured"""))
cells.append(nbf.v4.new_code_cell(
"""p = data.plot_time_data()"""))
cells.append(nbf.v4.new_markdown_cell(
"""## Calculate and plot FFT / transfer functions

Same options as the lab logger: `window=None` for hammer tests,
`window='hann'` for noise tests; use `data.calculate_tf_averaged()`
for ensemble averaging across sets."""))
cells.append(nbf.v4.new_code_cell(
"""data.calculate_fft_set(window=None)
p = data.plot_freq_data()"""))
cells.append(nbf.v4.new_code_cell(
"""data.calculate_tf_set(ch_in=0, window=None)
p = data.plot_tf_data()"""))
cells.append(nbf.v4.new_markdown_cell(
"""## Save your results

Files write to this in-browser filesystem; right-click the file in
the left panel and choose Download to keep it."""))
cells.append(nbf.v4.new_code_cell(
"""data.save_data(filename='analysis_results.dvma')"""))
nb.cells = cells
nbf.write(nb, 'lite/content/pydvma_analysis.ipynb')
print('written')
```

- [ ] **Step 2: Rebuild and test in the browser**

```bash
cd lite && jupyter lite build --output-dir ../_lite_build && cd ..
python -m http.server -d _lite_build 8899
```

In the browser at `http://localhost:8899/lab/index.html`: open `pydvma_analysis.ipynb`, drag in a test `.dvma` file (make one first: `python -c "import pydvma as dvma; d=dvma.DataSet(dvma.create_test_impulse_data()); d.calculate_tf_set(); d.save_data(filename='/tmp/my_data.dvma')"`), edit the filename cell, run all cells.
Expected: plots render (ipympl widgets), TF plot shows the impulse test data, save cell writes `analysis_results.dvma`. Also drag in `tests/data/reference_dataset_v140.npy` and confirm `dvma.load_data(filename='reference_dataset_v140.npy')` loads it (the legacy path under pyodide).

- [ ] **Step 3: Commit**

```bash
git add lite/content/pydvma_analysis.ipynb
git commit -m "docs: JupyterLite starter notebook mirroring labsheet analysis"
```

### Task 11: CI — build and deploy lite/ next to the docs

**Files:** Modify `.github/workflows/docs.yml:50-58`

- [ ] **Step 1: Replace the deploy step**

`mkdocs gh-deploy` can't carry extra directories, so build the site
explicitly, add the lite build, and publish with ghp-import (already
installed — it's a mkdocs dependency). Replace the two build/deploy
steps at the bottom of docs.yml with:

```yaml
      - name: Deploy documentation + JupyterLite
        if: (github.event_name == 'push' || github.event_name == 'workflow_dispatch') && (github.ref == 'refs/heads/master' || github.ref == 'refs/heads/main')
        run: |
          mkdocs build --strict
          pip wheel . peakutils --no-deps -w lite/pypi/
          (cd lite && jupyter lite build --output-dir ../site/lite)
          ghp-import --no-jekyll --push --force site

      - name: Build documentation (PR preview)
        if: github.event_name == 'pull_request'
        run: |
          mkdocs build --strict
```

Note the docs build already does `pip install -e .` plus `requirements-docs.txt`; check that requirements-docs.txt (or the mkdocstrings config) provides the Qt deps if the API docs import `gui.py` — run `grep -iE "pyqt|qtpy" requirements-docs.txt`. If absent AND the current docs build passes today, it means mkdocstrings doesn't import gui, so nothing to add. If it errors in CI later, change the install line to `pip install -e ".[qt,soundcard]"`.

- [ ] **Step 2: Validate the workflow locally as far as possible**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/docs.yml')); print('yaml OK')"
mkdocs build --strict
pip wheel . peakutils --no-deps -w lite/pypi/
(cd lite && jupyter lite build --output-dir ../site/lite)
ls site/index.html site/lite/lab/index.html
```
Expected: both index files exist — that's exactly the tree ghp-import will publish.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci: publish JupyterLite analysis site at /lite/ beside the docs"
```

(The Pages URL goes live on the next push to GitHub; pushing is the user's call.)

### Task 12: Link the site from the docs

**Files:** Modify the docs landing page (locate with `ls docs/index.md docs/README.md 2>/dev/null`)

- [ ] **Step 1: Add the link**

In the docs landing page, add a short section (adapt heading style to the page):

```markdown
## Analyse data in your browser — no install

Saved a dataset in the lab? You can load and analyse it right now at
**[the pydvma browser notebook](./lite/lab/index.html)** — Python
runs inside your browser (nothing to install, files never leave your
machine). Drag your `.dvma` or `.npy` file into its file browser and
follow the notebook.
```

- [ ] **Step 2: Build check + commit**

Run: `mkdocs build --strict`
Expected: clean build (`--strict` fails on broken internal links; the `./lite/` link is outside mkdocs' checked tree so it passes).

```bash
git add docs/
git commit -m "docs: link the browser analysis notebook from the docs home"
```

### Task 13: Version bump + TODO bookkeeping (confirm with user first)

**Files:** Modify `pyproject.toml`, `pydvma/datastructure.py:23`, `TODO.md`

- [ ] **Step 1: Ask the user** whether to bump 1.4.0 → 1.5.0 now (new file format + packaging change justify a minor bump; `.dvma` manifests will then record the correct writing version).

- [ ] **Step 2: If yes** — set `version = "1.5.0"` in `pyproject.toml` and `VERSION = '1.5.0'` in `datastructure.py` (update its comment to point at pyproject.toml). Run `python -m pytest tests/test_packaging.py -q` — the sync test proves they match.

- [ ] **Step 3: Update TODO.md**

Mark as done / annotate:
- "Packaging: fix `setup.py` dependencies" → done (Task 1; version sync now test-enforced).
- "`load_data`: document the pickle trust model" → done (Task 6 docstring).
- Housekeeping "Import-structure cleanup" → add note: plotting.py dead Qt imports removed (Task 7).
- Add under I/O or Housekeeping: "GUI file-dialog filters updated for .dvma (Task 6); labsheet text still says 'you should have a *.npy file' — update teaching notebooks for the .dvma era before October."

- [ ] **Step 4: Full suite, commit**

```bash
python -m pytest tests/ -q
git add pyproject.toml pydvma/datastructure.py TODO.md
git commit -m "chore: bump version to 1.5.0; TODO bookkeeping for stages 0-1"
```

---

## Out of scope for this plan

- **Stage 2 scope prototype** (Web Audio → canvas oscilloscope) is a separate subsystem with its own toolchain (Vite/TS); it gets its own plan once Stages 0–1 land. The gate criterion from the spec: smooth ≥30 fps scrolling trace of live mic input in Chrome/Safari before committing to the full web app.
- **Automated pyodide smoke test in CI** (spec: "under pyodide, load a checked-in reference `.npy` and run the analysis golden path"). Deliberately deferred: it needs node + pyodide or Playwright in the docs workflow. Stage 1 covers it manually (Task 10 Step 2 exercises exactly that path in a real browser, including the legacy reference file). Automate it alongside the Stage 2 Playwright setup, which brings the tooling anyway — note this in TODO.md during Task 13.
