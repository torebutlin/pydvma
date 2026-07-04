#!/usr/bin/env bash
# Vendor the pyodide runtime into public/pyodide/ from the npm package.
#
# We deliberately copy from node_modules/pyodide rather than downloading a
# GitHub release tarball: `npm install pyodide@<ver>` pins one real, verified
# version, ships the ESM `loadPyodide` entry, and is reproducible in CI
# (Task 15). This script just stages the runtime assets loadPyodide() fetches
# at boot into the served static dir. public/pyodide/ is gitignored — it is a
# build artefact, regenerated from the pinned devDependency.
#
# loadPyodide({ indexURL: '<base>/pyodide/' }) fetches these files by name:
#   pyodide.asm.js, pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json
# We copy the whole package payload (also the .mjs ESM entry) so nothing the
# runtime may request at boot is missing.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # webui/
src="$here/node_modules/pyodide"
dst="$here/public/pyodide"

if [ ! -d "$src" ]; then
  echo "error: $src not found — run 'npm install' first (pyodide is a devDependency)." >&2
  exit 1
fi

mkdir -p "$dst"
# Runtime assets fetched by loadPyodide at boot, plus the ESM entry & maps.
for f in \
  pyodide.asm.js \
  pyodide.asm.wasm \
  python_stdlib.zip \
  pyodide-lock.json \
  pyodide.mjs \
  pyodide.js \
  package.json; do
  cp "$src/$f" "$dst/$f"
done

ver="$(node -e "process.stdout.write(require('$src/package.json').version)")"
echo "vendored pyodide $ver -> $dst"
ls -1 "$dst"
