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
# create_test_impulse_data already returns a populated DataSet.
data = dvma.create_test_impulse_data(noise_level=0)
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
                           device_driver='mock')
data = dvma.log_data(settings)
assert data.time_data_list[0].time_data.shape[1] == 2
print('MOCK-OK')
""")
    assert result.returncode == 0, result.stderr
    assert 'MOCK-OK' in result.stdout
