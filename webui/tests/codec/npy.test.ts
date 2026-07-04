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

test('reads fortran order, transposed to C-order (legacy sono/coherence)', () => {
  // Legacy pydvma stores some multi-D arrays (sonogram, coherence) as
  // fortran_order=True. Build a fortran-ordered 2x3 whose LOGICAL values are
  // [[0,1,2],[3,4,5]]: C-order storage is 0,1,2,3,4,5; F-order (column-major)
  // is 0,3,1,4,2,5. parseNpy must transpose it back to row-major on read.
  const forged = new Uint8Array(
    serializeNpy({ shape: [2, 3], isComplex: false, data: Float64Array.from([0, 3, 1, 4, 2, 5]) }),
  );
  const at = new TextDecoder('latin1').decode(forged.subarray(0, 128)).indexOf('False');
  forged.set(new TextEncoder().encode('True '), at); // flip the flag; keep the F-order bytes
  const a = parseNpy(forged);
  expect(a.shape).toEqual([2, 3]);
  expect(Array.from(a.data as Float64Array)).toEqual([0, 1, 2, 3, 4, 5]); // C-order
});

test('reads fortran-order complex, interleaved and transposed', () => {
  // Logical 2x2 complex [[1+2i, 3+4i],[5+6i, 7+8i]]. Interleaved C-order is
  // 1,2,3,4,5,6,7,8. F-order (column-major over elements) is 1,2,5,6,3,4,7,8.
  const forged = new Uint8Array(
    serializeNpy({ shape: [2, 2], isComplex: true, data: Float64Array.from([1, 2, 5, 6, 3, 4, 7, 8]) }),
  );
  const at = new TextDecoder('latin1').decode(forged.subarray(0, 128)).indexOf('False');
  forged.set(new TextEncoder().encode('True '), at);
  const a = parseNpy(forged);
  expect(a.isComplex).toBe(true);
  expect(Array.from(a.data as Float64Array)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]); // C-order [re,im,...]
});

test('rejects truncated data', () => {
  const whole = fix('f8_2x3.npy');
  expect(() => parseNpy(whole.subarray(0, whole.length - 8))).toThrow(/truncated/);
});

test('rejects non-npy bytes', () => {
  expect(() => parseNpy(new Uint8Array([1, 2, 3]))).toThrow(/not a .npy/);
});

test('rejects unsupported dtype', () => {
  const forged = new Uint8Array(serializeNpy(parseNpy(fix('f8_2x3.npy'))));
  const at = new TextDecoder('latin1').decode(forged.subarray(0, 128)).indexOf('<f8');
  forged.set(new TextEncoder().encode('<u2'), at);
  expect(() => parseNpy(forged)).toThrow(/unsupported dtype/);
});

test('round-trips zero-length (0,) and 0-d () arrays', () => {
  const empty = parseNpy(serializeNpy({ shape: [0], isComplex: false, data: new Float64Array(0) }));
  expect(empty.shape).toEqual([0]);
  expect((empty.data as Float64Array).length).toBe(0);

  const scalar = parseNpy(serializeNpy({ shape: [], isComplex: false, data: Float64Array.from([42]) }));
  expect(scalar.shape).toEqual([]);
  expect(Array.from(scalar.data as Float64Array)).toEqual([42]);
});

test('round-trips float32 and bool', () => {
  const f4 = parseNpy(serializeNpy({ shape: [3], isComplex: false, data: new Float32Array([1.5, -2, 3]) }));
  expect(f4.data).toBeInstanceOf(Float32Array);
  expect(f4.shape).toEqual([3]);
  expect(Array.from(f4.data as Float32Array)).toEqual([1.5, -2, 3]);

  const b1 = parseNpy(serializeNpy({ shape: [4], isComplex: false, data: new Uint8Array([0, 1, 1, 0]) }));
  expect(b1.data).toBeInstanceOf(Uint8Array);
  expect(b1.shape).toEqual([4]);
  expect(Array.from(b1.data as Uint8Array)).toEqual([0, 1, 1, 0]);
});

test('parses int32 to float64', () => {
  // Hand-built v1 .npy: magic, version, uint16 header length, 64-byte-aligned header.
  let header = "{'descr': '<i4', 'fortran_order': False, 'shape': (3,), }";
  const unpadded = 10 + header.length + 1;
  header = header + ' '.repeat((64 - (unpadded % 64)) % 64) + '\n';
  const body = new Uint8Array(new Int32Array([7, -8, 123456]).buffer);
  const out = new Uint8Array(10 + header.length + body.byteLength);
  out.set([0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59], 0); out[6] = 1; out[7] = 0;
  new DataView(out.buffer).setUint16(8, header.length, true);
  out.set(new TextEncoder().encode(header), 10);
  out.set(body, 10 + header.length);

  const a = parseNpy(out);
  expect(a.shape).toEqual([3]);
  expect(a.data).toBeInstanceOf(Float64Array);
  expect(Array.from(a.data as Float64Array)).toEqual([7, -8, 123456]);
});
