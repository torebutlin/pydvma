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

// The Vibration Apps' Transfer function app saves a CSV whose FIRST LINE names
// its format (vibration-apps-tf-csv); the file lives in the python suite's data.
test('detects a Vibration Apps TF csv by its first line, whatever the name', () => {
  const va = new Uint8Array(readFileSync('../tests/data/vibration_apps_example.csv'));
  expect(sniffFormat(va, 'measurements.csv')).toBe('vacsv');
  expect(sniffFormat(va, 'renamed.txt')).toBe('vacsv'); // content wins over extension
  // A later version is still routed to the importer, which refuses it by name.
  const v2 = new TextEncoder().encode('# Vibration Apps transfer functions (vibration-apps-tf-csv 2)\n');
  expect(sniffFormat(v2, 'x.csv')).toBe('vacsv');
  // Saved again by Excel on Windows: a UTF-8 byte-order mark in front.
  const bom = new Uint8Array([0xef, 0xbb, 0xbf, ...va.subarray(0, 200)]);
  expect(sniffFormat(bom, 'x.csv')).toBe('vacsv');
});

test('any other .csv is its own route, so the refusal can say why', () => {
  const own = new TextEncoder().encode('# pydvma export: RAW data, calibration NOT applied.\n1,2\n');
  expect(sniffFormat(own, 'own.csv')).toBe('csv');
  expect(sniffFormat(own, 'OWN.CSV')).toBe('csv');
  expect(sniffFormat(own, 'own.txt')).toBe('unknown');
});
