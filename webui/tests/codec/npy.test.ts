import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { parseNpy, serializeNpy } from '../../src/lib/codec/npy';

const fix = (n: string) => new Uint8Array(readFileSync(`tests/fixtures/${n}`));

test('parses float64 2x3', () => {
  const a = parseNpy(fix('f8_2x3.npy'));
  expect(a.shape).toEqual([2, 3]);
  expect(a.isComplex).toBe(false);
  expect(Array.from(a.data as Float64Array)).toEqual([0, 1.5, 3, 4.5, 6, 7.5]);
});

test('parses complex128 interleaved', () => {
  const a = parseNpy(fix('c16_4.npy'));
  expect(a.shape).toEqual([4]);
  expect(a.isComplex).toBe(true);
  const d = a.data as Float64Array;           // [re0, im0, re1, im1, ...]
  expect(d[0]).toBe(1); expect(d[1]).toBe(2);
  expect(d[2]).toBe(-0.5); expect(d[3]).toBe(0);
  expect(d[4]).toBe(3.25); expect(d[5]).toBe(-4);
  expect(d[6]).toBe(0); expect(d[7]).toBe(1);
});

test('parses int64 losslessly up to 2^53', () => {
  const a = parseNpy(fix('i8_3.npy'));
  expect(Array.from(a.data as Float64Array)).toEqual([1, -7, 2 ** 40]);
});

test('round-trips float64 and complex128', () => {
  for (const name of ['f8_2x3.npy', 'c16_4.npy']) {
    const a = parseNpy(fix(name));
    const b = parseNpy(serializeNpy(a));
    expect(b.shape).toEqual(a.shape);
    expect(Array.from(b.data as Float64Array)).toEqual(Array.from(a.data as Float64Array));
  }
});

test('rejects fortran order', () => {
  const a = parseNpy(fix('f8_2x3.npy'));
  const forged = new Uint8Array(serializeNpy(a));
  // Overwrite 'False' -> 'True ' in place at its byte offset. (Decoding the
  // whole prefix as UTF-8 and re-encoding would mangle the 0x93 magic byte.)
  const at = new TextDecoder('latin1').decode(forged.subarray(0, 128)).indexOf('False');
  forged.set(new TextEncoder().encode('True '), at);
  expect(() => parseNpy(forged)).toThrow(/fortran/i);
});
