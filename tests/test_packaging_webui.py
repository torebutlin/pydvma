# -*- coding: utf-8 -*-
"""Packaging guarantees for the browser UI shipped inside the wheel.

``pydvma-serve`` serves the no-install browser app from a pip install by
carrying the built UI as ``pydvma/_webui`` in the wheel.  These tests pin
the two behaviours that make that safe and predictable without needing a
real wheel build:

* :func:`pydvma.serve._resolve_ui_dir` follows the decided priority
  (explicit ``--ui-dir`` > dev-checkout ``webui/dist`` > packaged
  ``pydvma/_webui`` > no UI);
* :func:`pydvma.serve._packaged_ui_dir` locates the packaged UI through
  :mod:`importlib.resources` (so it works from a relocated/zipped
  install), returning the directory when present and ``None`` when not.

The end-to-end "the fat wheel actually serves the UI" check is a manual
scratch-venv smoke test documented in the installation docs; here we
keep it hermetic and fast with a marker file.
"""
import tomllib
from pathlib import Path

import pydvma.serve as serve


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---- resolution order ----------------------------------------------------

def test_resolve_ui_dir_prefers_explicit(tmp_path, monkeypatch):
    explicit = tmp_path / 'explicit'
    explicit.mkdir()
    repo = tmp_path / 'repo'
    repo.mkdir()
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    monkeypatch.setattr(serve, '_repo_default_ui_dir', lambda: repo)
    monkeypatch.setattr(serve, '_packaged_ui_dir', lambda: pkg)

    got = serve._resolve_ui_dir(str(explicit))
    assert got == explicit.resolve()


def test_resolve_ui_dir_explicit_returned_even_if_missing(tmp_path, monkeypatch):
    # A bad explicit path is returned as-is so the server's no-UI page
    # surfaces the mistake rather than silently falling back.
    monkeypatch.setattr(serve, '_repo_default_ui_dir', lambda: tmp_path / 'repo')
    monkeypatch.setattr(serve, '_packaged_ui_dir', lambda: tmp_path / 'pkg')
    missing = tmp_path / 'does-not-exist'
    assert serve._resolve_ui_dir(str(missing)) == missing.resolve()


def test_resolve_ui_dir_uses_repo_checkout_when_present(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    monkeypatch.setattr(serve, '_repo_default_ui_dir', lambda: repo)
    monkeypatch.setattr(serve, '_packaged_ui_dir', lambda: pkg)

    assert serve._resolve_ui_dir(None) == repo


def test_resolve_ui_dir_falls_back_to_packaged(tmp_path, monkeypatch):
    pkg = tmp_path / 'pkg'
    pkg.mkdir()
    # Repo checkout dir does not exist (installed-wheel situation).
    monkeypatch.setattr(serve, '_repo_default_ui_dir', lambda: tmp_path / 'nope')
    monkeypatch.setattr(serve, '_packaged_ui_dir', lambda: pkg)

    assert serve._resolve_ui_dir(None) == pkg


def test_resolve_ui_dir_none_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.setattr(serve, '_repo_default_ui_dir', lambda: tmp_path / 'nope')
    monkeypatch.setattr(serve, '_packaged_ui_dir', lambda: None)

    assert serve._resolve_ui_dir(None) is None


# ---- packaged UI via importlib.resources (marker file) -------------------

def test_packaged_ui_dir_finds_marker(tmp_path, monkeypatch):
    """When ``pydvma/_webui`` exists, it is located and returned.

    Exercises the real importlib.resources path by pointing
    ``files('pydvma')`` at a temp package root that contains a marker
    ``_webui/index.html``.
    """
    webui = tmp_path / '_webui'
    webui.mkdir()
    (webui / 'index.html').write_text('<!doctype html><title>marker</title>')

    monkeypatch.setattr(serve.importlib.resources, 'files',
                        lambda package: tmp_path)

    got = serve._packaged_ui_dir()
    assert got is not None
    assert got == tmp_path / '_webui'
    assert (got / 'index.html').read_text().endswith('</title>')


def test_packaged_ui_dir_none_when_absent(tmp_path, monkeypatch):
    # Package root with no _webui subdir -> None (lean wheel case).
    monkeypatch.setattr(serve.importlib.resources, 'files',
                        lambda package: tmp_path)
    assert serve._packaged_ui_dir() is None


# ---- pyproject declares the packaging glob -------------------------------

def test_pyproject_ships_webui_glob():
    """The wheel must include ``_webui/**/*`` as package data, or a staged
    UI would silently not travel in the wheel."""
    with open(REPO_ROOT / 'pyproject.toml', 'rb') as f:
        pyproject = tomllib.load(f)
    globs = pyproject['tool']['setuptools']['package-data']['pydvma']
    assert '_webui/**/*' in globs


def test_pyproject_uses_intree_backend():
    """The lean/fat split relies on the in-tree build backend."""
    with open(REPO_ROOT / 'pyproject.toml', 'rb') as f:
        pyproject = tomllib.load(f)
    bs = pyproject['build-system']
    assert bs['build-backend'] == '_pydvma_build'
    assert '.' in bs['backend-path']
