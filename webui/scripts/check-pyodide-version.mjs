#!/usr/bin/env node
// Assert the app's PYODIDE_VERSION constant matches the vendored pyodide
// runtime (the `pyodide` devDependency in node_modules). Run from webui/ (or
// anywhere):
//
//     node scripts/check-pyodide-version.mjs
//
// Why this exists (Stage 2 plan amendment A8b): the worker loads the vendored
// pyodide runtime from public/pyodide/ (staged by fetch-pyodide.sh from
// node_modules/pyodide) but fetches the prebuilt numpy/scipy/micropip wheels
// from the jsdelivr CDN at `.../pyodide/v${PYODIDE_VERSION}/full/` (see
// stores/engine.ts + worker/engine.worker.ts). If PYODIDE_VERSION drifts from
// the installed runtime, the CDN wheels are built against a DIFFERENT pyodide
// ABI than the runtime instantiating them — a numpy/scipy ABI mismatch that
// only surfaces at boot. This check fails CI at build time instead.
//
// Ground truth = node_modules/pyodide/package.json .version (the pinned
// devDependency). We grep PYODIDE_VERSION out of engine.ts rather than import
// the TS module (no transpile step needed in the CI check).
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const webuiDir = dirname(dirname(fileURLToPath(import.meta.url)));
const engineTs = join(webuiDir, 'src', 'lib', 'stores', 'engine.ts');
const pyodidePkg = join(webuiDir, 'node_modules', 'pyodide', 'package.json');

// 1. The declared version in engine.ts:  export const PYODIDE_VERSION = '0.28.3';
const src = readFileSync(engineTs, 'utf8');
const m = src.match(/PYODIDE_VERSION\s*=\s*['"]([^'"]+)['"]/);
if (!m) {
  console.error(`check-pyodide-version: could not find PYODIDE_VERSION in ${engineTs}`);
  process.exit(1);
}
const declared = m[1];

// 2. The vendored runtime version (the pinned devDependency).
let installed;
try {
  installed = JSON.parse(readFileSync(pyodidePkg, 'utf8')).version;
} catch (e) {
  console.error(`check-pyodide-version: could not read ${pyodidePkg} — run 'npm ci' first.`);
  console.error(String(e));
  process.exit(1);
}

if (declared !== installed) {
  console.error(
    `check-pyodide-version: MISMATCH — PYODIDE_VERSION in engine.ts is '${declared}' ` +
    `but the vendored pyodide runtime (node_modules/pyodide) is '${installed}'.\n` +
    `These MUST match: the jsdelivr CDN serves numpy/scipy/micropip wheels built ` +
    `against v${declared}, which would then be loaded into the v${installed} runtime ` +
    `(ABI mismatch). Update PYODIDE_VERSION or the pyodide devDependency so they agree.`,
  );
  process.exit(1);
}

console.log(`check-pyodide-version: OK — PYODIDE_VERSION and vendored pyodide both '${installed}'.`);
