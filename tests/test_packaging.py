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
