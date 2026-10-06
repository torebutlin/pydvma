import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { sniffFormat } from '../../src/lib/files/sniff';

test('detects dvma (zip), legacy npy, mat, unknown', () => {
  const dvma = new Uint8Array(readFileSync('tests/fixtures/impulse.dvma'));
  expect(sniffFormat(dvma, 'x.dvma')).toBe('dvma');
  expect(sniffFormat(dvma, 'renamed.npy')).toBe('dvma'); // content wins over extension
  const npy = new Uint8Array(readFileSync('tests/fixtures/f8_2x3.npy'));
  expect(sniffFormat(npy, 'x.npy')).toBe('npy');
  expect(sniffFormat(new Uint8Array([0, 1, 2, 3]), 'x.mat')).toBe('mat');
  expect(sniffFormat(new Uint8Array([0, 1, 2, 3]), 'x.bin')).toBe('unknown');
});

// A CSV goes to the engine's file_to_dvma, which runs python's load_data: it
// reads pydvma's own CSV export and the Vibration Apps' Transfer function CSV,
// and refuses anything else with the reason. Those two are recognised by the
// format their FIRST LINE names, whatever the file is called.
test('a CSV is recognised by its first line, whatever the name', () => {
  const va = new Uint8Array(readFileSync('../tests/data/vibration_apps_example.csv'));
  expect(sniffFormat(va, 'measurements.csv')).toBe('csv');
  expect(sniffFormat(va, 'renamed.txt')).toBe('csv');           // content wins over extension
  const own = new TextEncoder().encode('# pydvma dataset (pydvma-csv 1)\n# manifest: {}\n');
  expect(sniffFormat(own, 'renamed.txt')).toBe('csv');
  // A later version still goes to the engine, which refuses it by name.
  const v3 = new TextEncoder().encode('# Vibration Apps transfer functions (vibration-apps-tf-csv 3)\n');
  expect(sniffFormat(v3, 'x.dat')).toBe('csv');
  // Saved again by Excel on Windows: a UTF-8 byte-order mark in front.
  const bom = new Uint8Array([0xef, 0xbb, 0xbf, ...va.subarray(0, 200)]);
  expect(sniffFormat(bom, 'x.dat')).toBe('csv');
});

test('any other .csv goes to the engine too, so the refusal can say why', () => {
  const other = new TextEncoder().encode('a,b\n1,2\n');
  expect(sniffFormat(other, 'other.csv')).toBe('csv');
  expect(sniffFormat(other, 'OTHER.CSV')).toBe('csv');
  expect(sniffFormat(other, 'other.txt')).toBe('unknown');
});
