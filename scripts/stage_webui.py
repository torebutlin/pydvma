#!/usr/bin/env python3
"""Stage the built browser UI into the pydvma package tree for wheeling.

``pydvma-serve`` can serve the no-install browser app (``webui/``)
directly from a ``pip`` install — but only if the built UI travels inside
the wheel.  This script mirrors ``webui/dist`` into ``pydvma/_webui`` so
the packaging glob (``_webui/**/*`` in ``pyproject.toml``) picks it up.

Flow
====

Typical release build (from the repo root)::

    cd webui && npm ci && npm run vendor   # fetch pyodide + build lean wheels
    python scripts/stage_webui.py          # runs `npm run build`, mirrors dist
    python -m build --wheel                # -> the fat wheel with _webui

``npm run vendor`` populates ``webui/public/{pyodide,pypi}`` (both
gitignored); ``npm run build`` copies them into ``webui/dist`` alongside
the bundled app.  This script then makes ``pydvma/_webui`` an exact copy
of ``webui/dist`` — old files removed, so a re-stage never leaves stale
assets behind.

Use ``--skip-build`` to mirror an already-built ``webui/dist`` without
re-running Vite (handy in CI once ``npm run build`` has run, or when
iterating on packaging).  ``npm`` is only required without
``--skip-build``.

The staged directory is a build artefact (gitignored); it is safe to
delete and re-create at any time.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEBUI = REPO_ROOT / 'webui'
DEFAULT_DEST = REPO_ROOT / 'pydvma' / '_webui'


def run_npm_build(webui_dir: Path) -> None:
    """Run ``npm run build`` in ``webui_dir`` (raises on failure).

    Uses ``npm.cmd`` on Windows where the bare ``npm`` shim is not
    directly executable via ``subprocess`` without a shell.
    """
    npm = 'npm.cmd' if sys.platform == 'win32' else 'npm'
    print('[stage_webui] running `%s run build` in %s' % (npm, webui_dir))
    try:
        subprocess.run([npm, 'run', 'build'], cwd=str(webui_dir), check=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            '[stage_webui] `%s` not found. Install Node.js/npm, or pass '
            '--skip-build to mirror an existing webui/dist.' % npm
        ) from exc


def mirror(dist_dir: Path, dest_dir: Path) -> int:
    """Mirror ``dist_dir`` onto ``dest_dir``, removing stale files.

    Implemented as remove-then-copy (the simplest correct "rsync
    --delete": no chance of orphaned old assets).  Returns the number of
    files staged.  Raises ``SystemExit`` if ``dist_dir`` is missing or
    obviously not a built UI (no ``index.html``).
    """
    if not dist_dir.is_dir():
        raise SystemExit(
            '[stage_webui] no built UI at %s. Run `npm run build` in webui/ '
            '(and `npm run vendor` first for the pyodide runtime), or drop '
            '--skip-build.' % dist_dir)
    if not (dist_dir / 'index.html').is_file():
        raise SystemExit(
            '[stage_webui] %s has no index.html — is it really a Vite build '
            'output?' % dist_dir)

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dist_dir, dest_dir)

    files = [p for p in dest_dir.rglob('*') if p.is_file()]
    return len(files)


def main(argv=None) -> int:
    """CLI: build (optional) then mirror ``webui/dist`` into ``pydvma/_webui``."""
    parser = argparse.ArgumentParser(
        prog='stage_webui.py',
        description='Stage the built browser UI into pydvma/_webui for the wheel.')
    parser.add_argument(
        '--skip-build', action='store_true',
        help='mirror an existing webui/dist without running `npm run build`.')
    parser.add_argument(
        '--webui-dir', type=Path, default=DEFAULT_WEBUI,
        help='the webui/ project directory (default: <repo>/webui).')
    parser.add_argument(
        '--dest', type=Path, default=DEFAULT_DEST,
        help='destination package dir (default: <repo>/pydvma/_webui).')
    args = parser.parse_args(argv)

    webui_dir = args.webui_dir.resolve()
    dist_dir = webui_dir / 'dist'
    dest_dir = args.dest.resolve()

    if not args.skip_build:
        run_npm_build(webui_dir)

    n = mirror(dist_dir, dest_dir)

    has_pyodide = (dest_dir / 'pyodide').is_dir()
    has_pypi = (dest_dir / 'pypi').is_dir()
    print('[stage_webui] staged %d files -> %s' % (n, dest_dir))
    if not (has_pyodide and has_pypi):
        missing = ', '.join(
            name for name, ok in (('pyodide', has_pyodide), ('pypi', has_pypi))
            if not ok)
        print('[stage_webui] WARNING: staged UI is missing %s — the served '
              'app will 404 on the in-browser engine. Run `npm run vendor` in '
              'webui/ before building, then re-stage.' % missing,
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
