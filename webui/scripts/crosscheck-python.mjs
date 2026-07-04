#!/usr/bin/env node
// Cross-check that pydvma (python) can read a .dvma container written by
// the JS codec. Repeatable — run from webui/ (or anywhere):
//
//     node scripts/crosscheck-python.mjs
//
// Steps:
//  1. vitest (DVMA_CROSSCHECK=1) runs tests/codec/crosscheck.test.ts, which
//     writes tests/fixtures/roundtrip.dvma via readDvma -> writeDvma.
//  2. python re-reads it with pydvma.load_data and asserts item counts AND
//     meta fidelity (timestamp -> datetime, unique_id -> UUID,
//     channel_cal_factors -> ndarray, settings restored) — this is what
//     proves the metaRaw verbatim-tag round-trip works.
//  3. the roundtrip file is deleted on success (kept on failure for
//     inspection).
//
// Equivalent manual python check (from the repo root):
//   python -c "import pydvma as dvma; d = dvma.load_data(filename='webui/tests/fixtures/roundtrip.dvma'); assert len(d.time_data_list) == 1 and len(d.tf_data_list) == 1; print('python reads JS-written dvma OK')"
//
// Override the interpreter with PYTHON=/path/to/python if needed.
import { spawnSync } from 'node:child_process';
import { existsSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const webuiDir = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(webuiDir);
const roundtrip = join(webuiDir, 'tests', 'fixtures', 'roundtrip.dvma');
const python = process.env.PYTHON ?? 'python';

function run(cmd, args, opts) {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...opts });
  if (r.error) throw r.error;
  return r.status ?? 1;
}

// 0. drop any stale roundtrip left by an earlier failed run
rmSync(roundtrip, { force: true });

// 1. JS writes the roundtrip container — invoke vitest's entry point with
// this node binary directly (no npx, no shell) so it works on Windows too
let status = run(process.execPath,
  [join(webuiDir, 'node_modules', 'vitest', 'vitest.mjs'),
   'run', 'tests/codec/crosscheck.test.ts'], {
  cwd: webuiDir, env: { ...process.env, DVMA_CROSSCHECK: '1' },
});
if (status !== 0 || !existsSync(roundtrip)) {
  console.error('crosscheck: vitest failed to produce roundtrip.dvma');
  process.exit(1);
}

// 2. python reads it back
const pyCode = `
import datetime, uuid
import numpy as np
import pydvma as dvma
d = dvma.load_data(filename='webui/tests/fixtures/roundtrip.dvma')
assert len(d.time_data_list) == 1 and len(d.tf_data_list) == 1
td = d.time_data_list[0]
assert td.test_name == 'webui fixture'
assert td.units == ['N', 'm/s']
assert isinstance(td.timestamp, datetime.datetime), type(td.timestamp)
assert isinstance(td.unique_id, uuid.UUID), type(td.unique_id)
fd = d.freq_data_list[0]
assert isinstance(fd.channel_cal_factors, np.ndarray), type(fd.channel_cal_factors)
assert fd.id_link == td.unique_id
assert td.settings is not None and hasattr(td.settings, 'fs')
assert np.iscomplexobj(d.tf_data_list[0].tf_data)
print('python reads JS-written dvma OK')
`;
status = run(python, ['-c', pyCode], { cwd: repoRoot });
if (status !== 0) {
  console.error(`crosscheck: python failed to read ${roundtrip} (file kept for inspection)`);
  process.exit(1);
}

// 3. clean up
rmSync(roundtrip);
console.log('crosscheck passed; removed roundtrip.dvma');
