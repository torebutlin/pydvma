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
