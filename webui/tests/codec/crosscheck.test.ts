// Generator half of the python cross-check (see scripts/crosscheck-python.mjs).
// Skipped in normal test runs; when DVMA_CROSSCHECK=1 it writes
// tests/fixtures/roundtrip.dvma = readDvma(impulse.dvma) -> writeDvma, i.e.
// a container produced entirely by the JS codec, for pydvma to re-read.
// (It lives inside vitest so the TS sources need no separate build step.)
import { readFileSync, writeFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';

test.runIf(process.env.DVMA_CROSSCHECK === '1')(
  'writes roundtrip.dvma for the python cross-check', () => {
    const bytes = new Uint8Array(readFileSync('tests/fixtures/impulse.dvma'));
    const out = writeDvma(readDvma(bytes));
    expect(out.length).toBeGreaterThan(0);
    writeFileSync('tests/fixtures/roundtrip.dvma', out);
  });
