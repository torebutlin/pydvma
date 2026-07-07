"""In-tree PEP 517 build backend: setuptools plus the lean/fat webui split.

pydvma ships the built browser UI (``webui/dist``) *inside* the wheel as
``pydvma/_webui/`` so that ``pip install pydvma[serve]`` + ``pydvma-serve``
serves the app with no repo checkout (see the packaging notes in
``pyproject.toml`` and ``docs/getting-started/installation.md``).

That staged UI directory is large (it embeds a full pyodide runtime) and
must **not** end up in two places where it would be dead weight or an
infinite regress:

* The **pyodide engine wheel** built by ``webui/scripts/build-wheels.sh``
  vendors *this same pydvma package* into the browser so pyodide can
  ``micropip``-install it.  If that wheel carried ``_webui`` it would
  bundle a copy of pyodide *inside* the wheel that pyodide itself loads —
  tens of MB of pointless recursion.  ``build-wheels.sh`` therefore sets
  ``PYDVMA_LEAN_WHEEL=1`` and this backend drops ``_webui`` from the wheel.
* The **source distribution** never carries ``_webui`` either: it is a
  gitignored build artefact, so shipping it would make the sdist
  unreproducible from VCS.  ``build_sdist`` here always excludes it.

Mechanism
=========

The static ``package-data`` glob in ``pyproject.toml`` includes
``_webui/**/*``, so an ordinary ``pip wheel .`` / ``python -m build
--wheel`` picks up a staged ``pydvma/_webui`` and produces the **fat**
wheel.  To produce a **lean** wheel (or any sdist) this backend makes the
directory *invisible to setuptools for the duration of the build* by
renaming it aside and restoring it in a ``finally``.  Excluding files that
are not present is version-independent and needs no knowledge of
setuptools internals — setuptools cannot package what it cannot see.

**Stale ``build/`` guard.**  ``bdist_wheel`` reuses the ``build/lib`` copy
of the package without re-running ``build_py``, so a ``build/`` left over
from an earlier build would carry the *wrong* ``_webui`` state into the
wheel — a fat ``build/lib`` keeps the UI in a later *lean* wheel, and a
lean ``build/lib`` drops it from a later *fat* wheel.  This backend
therefore removes ``build/`` before every wheel build, forcing a correct
from-scratch copy.  ``build/`` is a disposable, gitignored artefact.  This
matters for the maintainer's in-place builds (``build-wheels.sh``, and an
editable checkout that always has a live ``build/`` + ``pydvma.egg-info``).

pip/``build`` run the backend in (or against a copy of) the source tree;
the restore-on-exit plus a self-healing sweep of any stale
``.__lean_hidden__`` marker keeps even ``--no-build-isolation`` safe.

Everything else (metadata, requires, editable installs) is delegated to
``setuptools.build_meta`` unchanged.
"""
from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from setuptools import build_meta as _bm
# Re-export the hooks we do not override so this module is a complete
# PEP 517 backend (get_requires_for_*, prepare_metadata_for_*).
from setuptools.build_meta import *  # noqa: F401,F403

#: Environment variable that forces a lean wheel (``_webui`` excluded).
LEAN_ENV = 'PYDVMA_LEAN_WHEEL'

#: Repo / source-tree root (this backend lives next to ``pyproject.toml``).
_ROOT = Path(__file__).resolve().parent
#: The staged UI directory.
_WEBUI_DIR = _ROOT / 'pydvma' / '_webui'
#: Name used while the directory is hidden from setuptools mid-build.
_HIDDEN = _WEBUI_DIR.with_name('_webui.__lean_hidden__')
#: setuptools' scratch build tree (``build/lib`` is what bdist_wheel zips).
_BUILD_DIR = _ROOT / 'build'


def _lean_requested() -> bool:
    """True when ``PYDVMA_LEAN_WHEEL`` asks for a UI-free wheel."""
    return os.environ.get(LEAN_ENV, '') not in ('', '0', 'false', 'False')


def _clean_build_dir() -> None:
    """Remove a stale ``build/`` so ``build_py`` re-copies package data.

    Without this, ``bdist_wheel`` reuses whatever is already in
    ``build/lib`` and the wheel's ``_webui`` state reflects the *previous*
    build rather than this one.  ``build/`` is a regenerated, gitignored
    artefact, so removing it is always safe.
    """
    shutil.rmtree(_BUILD_DIR, ignore_errors=True)


@contextlib.contextmanager
def _webui_excluded():
    """Hide ``pydvma/_webui`` for the duration of a build, then restore it.

    A no-op when the directory does not exist (e.g. an unstaged checkout,
    which is exactly the state that produced a lean wheel before this
    packaging existed).  Self-heals a stale hidden directory left behind
    by an interrupted earlier build before hiding afresh.
    """
    # Recover from an interrupted prior build first.
    if _HIDDEN.exists() and not _WEBUI_DIR.exists():
        _HIDDEN.rename(_WEBUI_DIR)

    if not _WEBUI_DIR.exists():
        yield
        return

    _WEBUI_DIR.rename(_HIDDEN)
    try:
        yield
    finally:
        # Restore even if setuptools raised; prefer whichever exists.
        if _HIDDEN.exists() and not _WEBUI_DIR.exists():
            _HIDDEN.rename(_WEBUI_DIR)


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    """Build a wheel; drop ``_webui`` when ``PYDVMA_LEAN_WHEEL`` is set.

    The default (env unset) produces the *fat* wheel used for local
    installs — the browser UI is bundled so ``pydvma-serve`` needs no repo
    checkout.  ``build-wheels.sh`` sets the env to get the *lean* engine
    wheel vendored into pyodide.  ``build/`` is cleaned first either way so
    the wheel reflects the current tree, not a leftover ``build/lib``.
    """
    _clean_build_dir()
    if _lean_requested():
        with _webui_excluded():
            return _bm.build_wheel(wheel_directory, config_settings,
                                   metadata_directory)
    return _bm.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    """Build a source distribution, always excluding the staged UI.

    ``_webui`` is a gitignored build artefact; keeping it out of the sdist
    keeps the sdist reproducible from version control.  Build the fat
    wheel directly from the (staged) source tree, not from this sdist.
    """
    with _webui_excluded():
        return _bm.build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    """Editable install passthrough.

    Editable installs point at the live source tree rather than copying
    files, so the staged UI is served straight from ``pydvma/_webui`` when
    present; the lean guard is honoured for symmetry but rarely relevant.
    """
    if _lean_requested():
        with _webui_excluded():
            return _bm.build_editable(wheel_directory, config_settings,
                                      metadata_directory)
    return _bm.build_editable(wheel_directory, config_settings,
                              metadata_directory)
