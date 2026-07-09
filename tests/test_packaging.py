# -*- coding: utf-8 -*-
"""Packaging guarantees: version sync and the core import surface.

The core import-surface tests enforce the *logical* core/GUI split
from dev/2026-07-01-web-ui-design.md: `import pydvma` must succeed
with no Qt binding, no sounddevice, no nidaqmx and no seaborn
present. They simulate missing packages with a meta-path blocker in
a subprocess rather than a separate venv, so they run in the normal
suite.
"""
import os
import pathlib
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
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
    )


def test_core_import_without_qt_or_hardware():
    result = _run_core_python("""
import pydvma as dvma
# public core names all resolve
settings = dvma.MySettings(channels=2, fs=1000, device_driver='mock')
# create_test_impulse_data already returns a populated DataSet.
data = dvma.create_test_impulse_data(noise_level=0)
data.calculate_fft_set()
data.calculate_tf_set()
assert len(data.tf_data_list) == 1
print('CORE-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'CORE-OK' in result.stdout, (result.stdout, result.stderr)


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
    assert 'MOCK-OK' in result.stdout, (result.stdout, result.stderr)


# The public core names that must resolve on a base (no-extras) install.
# `PlotData` is lazy (matplotlib, a core dep) and must resolve too; the
# retired Qt names (Logger / Oscilloscope) must NOT be here.
_PUBLIC_SURFACE = [
    'MySettings', 'Output_Signal_Settings', 'set_plot_colours',
    'load_data', 'save_data', 'save_fig', 'export_to_matlab_jwlogger',
    'export_to_matlab', 'export_to_csv', 'import_from_matlab_jwlogger',
    'log_data', 'output_signal', 'signal_generator', 'stream_snapshot',
    'DataSet', 'TimeData', 'TimeDataList', 'FreqData', 'FreqDataList',
    'CrossSpecData', 'CrossSpecDataList', 'TfData', 'TfDataList',
    'SonoData', 'SonoDataList', 'MetaData', 'MetaDataList', 'ModalData',
    'ModalDataList', 'update_dataset', 'create_test_impulse_data',
    'create_test_impulse_ensemble', 'create_test_noise_data',
    'calculate_fft', 'calculate_cross_spectrum_matrix',
    'calculate_cross_spectra_averaged', 'clean_impulse', 'calculate_tf',
    'calculate_tf_averaged', 'multiply_by_power_of_iw', 'best_match',
    'calculate_sonogram', 'calculate_damping_from_sono', 'calculate_cwt',
    'calculate_damping_from_cwt', 'calculate_damping_by_band', 'Recorder',
    'Recorder_NI', 'start_stream', 'REC', 'setup_output_NI',
    'setup_output_soundcard', 'list_available_devices', 'get_devices_NI',
    'get_devices_soundcard', 'suggest_ni_settings', 'get_device_info',
    'modal_fit_single_channel', 'modal_fit_all_channels', 'PlotData',
]

# Phrases the retired-Qt tombstone must contain (see pydvma/__init__.py
# `_REMOVED_MESSAGE`): what happened, the replacement, and the escape
# hatch back to the last Qt version.
_TOMBSTONE_PHRASES = [
    'was removed',
    'pip install pydvma[serve]',
    'pydvma-serve --open',
    'https://torebutlin.github.io/pydvma/web-logger/',
    'qt-final',
]


def test_removed_qt_names_raise_tombstone_without_qt():
    # Accessing a retired Qt name (Logger / Oscilloscope) must raise a
    # clear, actionable tombstone — even on a base install with no Qt.
    result = _run_core_python("""
import pydvma as dvma
for name in ('Logger', 'Oscilloscope'):
    try:
        getattr(dvma, name)
    except AttributeError as e:
        print('MSG[' + name + ']:', e)
    else:
        raise SystemExit(name + ' did not raise')
# a removed name must not masquerade as present
assert not hasattr(dvma, 'Logger'), 'hasattr(dvma, Logger) should be False'
assert not hasattr(dvma, 'Oscilloscope')
print('TOMBSTONE-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'TOMBSTONE-OK' in result.stdout, (result.stdout, result.stderr)
    for phrase in _TOMBSTONE_PHRASES:
        assert phrase in result.stdout, (phrase, result.stdout)


def test_removed_qt_names_raise_tombstone_even_with_qt_present():
    # The tombstone is a *removal*, not a missing-dependency error: it
    # must fire regardless of whether qtpy happens to be importable in
    # the current environment (this runs in-process, no blocker).
    import pydvma as dvma
    import pytest
    for name in ('Logger', 'Oscilloscope'):
        with pytest.raises(AttributeError) as excinfo:
            getattr(dvma, name)
        msg = str(excinfo.value)
        for phrase in _TOMBSTONE_PHRASES:
            assert phrase in msg, (name, phrase, msg)
    assert not hasattr(dvma, 'Logger')
    # and they are not advertised in the module's dir()
    assert 'Logger' not in dir(dvma)
    assert 'Oscilloscope' not in dir(dvma)


def test_public_api_surface_resolves_without_qt():
    # The whole non-GUI public API surface must resolve on a base
    # (no-extras) install — nothing was collateral-damaged by removing
    # the Qt layer.
    import json
    result = _run_core_python("""
import json
import pydvma as dvma
surface = {surface!r}
missing = [n for n in surface if not hasattr(dvma, n)]
print('MISSING:' + json.dumps(missing))
# resolving each name must not raise
for n in surface:
    getattr(dvma, n)
print('SURFACE-OK')
""".format(surface=_PUBLIC_SURFACE))
    assert result.returncode == 0, result.stderr
    assert 'SURFACE-OK' in result.stdout, (result.stdout, result.stderr)
    missing_line = [l for l in result.stdout.splitlines()
                    if l.startswith('MISSING:')][0]
    missing = json.loads(missing_line[len('MISSING:'):])
    assert missing == [], missing


def test_save_and_load_dvma_without_qt(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp('dvma_core')
    result = _run_core_python("""
import pydvma as dvma
data = dvma.create_test_impulse_data(noise_level=0)
out = dvma.save_data(data, filename={out!r})
loaded = dvma.load_data(filename=out)
assert (loaded.time_data_list[0].time_data.shape
        == data.time_data_list[0].time_data.shape)
print('FILEIO-OK')
""".format(out=str(out_dir / 'core_roundtrip')))
    assert result.returncode == 0, result.stderr
    assert 'FILEIO-OK' in result.stdout, (result.stdout, result.stderr)


def test_core_plotting_without_qt():
    # DataSet.plot_*_data must work on a base install (Agg backend) —
    # this is what pyodide/JupyterLite exercises.
    result = _run_core_python("""
import pydvma as dvma
data = dvma.create_test_impulse_data(noise_level=0)
data.calculate_tf_set()
p = data.plot_tf_data()
assert p.fig is not None
print('PLOT-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'PLOT-OK' in result.stdout, (result.stdout, result.stderr)


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
    assert 'COLOURS-OK' in result.stdout, (result.stdout, result.stderr)


def test_core_import_with_broken_sounddevice(tmp_path):
    # sounddevice installed but PortAudio C library missing raises
    # OSError at import (not ImportError); pydvma must still import
    # (CI runners and student machines without libportaudio).
    fake = tmp_path / 'sounddevice.py'
    fake.write_text("raise OSError('PortAudio library not found')\n")
    result = subprocess.run(
        [sys.executable, '-c',
         "import matplotlib; matplotlib.use('Agg')\n"
         "import pydvma as dvma\n"
         "assert dvma.MySettings(channels=2, device_driver='mock') is not None\n"
         "print('BROKEN-SD-OK')"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env=dict(os.environ, PYTHONPATH=str(tmp_path)),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert 'BROKEN-SD-OK' in result.stdout, (result.stdout, result.stderr)
