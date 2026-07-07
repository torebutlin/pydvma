#!/usr/bin/env bash
# Build the pure-python wheels the engine worker installs via micropip at boot:
#   - pydvma   (this repo; the compute library)
#   - peakutils (pydvma runtime dep; NOT prebuilt in the pyodide lock)
#
# numpy / scipy / matplotlib ARE prebuilt in pyodide-lock.json and are loaded
# with pyodide.loadPackage — they are NOT built here. Both wheels below are
# `py3-none-any` (pure python), so they install unchanged under pyodide's
# CPython 3.13. Output goes to public/pypi/ (gitignored build artefact); the
# worker fetches them from `<base>/pypi/<name>.whl` and micropip-installs each.
#
# Requires: python with `pip wheel` (the maintainer machine has pydvma editable
# installed, so `.` builds cleanly). Run from anywhere.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # webui/
repo="$(cd "$here/.." && pwd)"                            # pydvma repo root
out="$here/public/pypi"

py="${PYTHON:-python}"

# Build into a temp dir first and only replace public/pypi once BOTH wheels
# succeed. Building straight into public/pypi (after an up-front rm) would, if
# the second build failed (e.g. offline), leave a half-populated or empty dir
# with the previous good wheels already deleted — the next boot would then
# fail. The temp dir is cleaned up on any exit.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# pydvma itself (built from the repo root's pyproject.toml).
#
# PYDVMA_LEAN_WHEEL=1 tells the in-tree build backend (_pydvma_build.py) to
# EXCLUDE the staged browser UI (pydvma/_webui) from this wheel. That
# directory embeds a full pyodide runtime + the bundled app; without the
# guard, a repo that has been staged for the fat local-install wheel (via
# scripts/stage_webui.py) would bundle tens of MB of pyodide *inside* the
# very wheel pyodide then micropip-installs — pointless recursion. The
# guard keeps this engine wheel lean regardless of local staging state.
PYDVMA_LEAN_WHEEL=1 "$py" -m pip wheel --no-deps -w "$tmp" "$repo"
# peakutils — pydvma imports it in analysis.py; absent from the pyodide lock.
"$py" -m pip wheel --no-deps -w "$tmp" peakutils

# Both builds succeeded — swap the wheels into place atomically-ish.
mkdir -p "$out"
rm -f "$out"/*.whl
mv "$tmp"/*.whl "$out"/

echo "built wheels -> $out"
ls -1 "$out"
