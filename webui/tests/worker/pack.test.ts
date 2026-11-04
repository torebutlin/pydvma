import { describe, expect, test } from 'vitest';
import { BUF_KEY, NUM_KEY, packPayload } from '../../src/lib/worker/pack';

describe('packPayload', () => {
  test('typed arrays become placeholders and their bytes travel apart', () => {
    const axis = new Float64Array([0, 0.2, 0.4]);
    const data = new Float64Array([246.82, 0.0011, 5, -0.25]);
    const { json, bufs } = packPayload({
      freq_axis: axis, n_tf: 1, fs: 10000, window: null, action: 'fit',
      sets: [{ tf_data: data, ch_in: undefined }],
    });
    const p = JSON.parse(json);
    expect(p.freq_axis).toEqual({ [BUF_KEY]: 0, dtype: '<f8', length: 3 });
    expect(p.sets[0].tf_data).toEqual({ [BUF_KEY]: 1, dtype: '<f8', length: 4 });
    expect(p).toMatchObject({ n_tf: 1, fs: 10000, window: null, action: 'fit' });
    // undefined crosses as null (pyodide gave None), and is not dropped.
    expect(p.sets[0]).toHaveProperty('ch_in', null);
    // The bytes are the arrays' own: little-endian float64.
    expect(bufs).toHaveLength(2);
    expect(Array.from(new Float64Array(bufs[1].slice().buffer))).toEqual([246.82, 0.0011, 5, -0.25]);
  });

  test('a view into a larger buffer sends only its own bytes', () => {
    const whole = new Float64Array([1, 2, 3, 4, 5]);
    const view = whole.subarray(1, 3);
    const { json, bufs } = packPayload({ x: view });
    expect(JSON.parse(json).x.length).toBe(2);
    expect(bufs[0].byteLength).toBe(16);
    expect(Array.from(new Float64Array(bufs[0].slice().buffer))).toEqual([2, 3]);
  });

  test('every typed array type names its numpy dtype', () => {
    const { json } = packPayload({
      a: new Float32Array(1), b: new Uint8Array(2), c: new Int32Array(1), d: new Int16Array(1),
      e: new Uint32Array(1), f: new BigInt64Array(1), g: new ArrayBuffer(3),
    });
    const p = JSON.parse(json);
    expect([p.a.dtype, p.b.dtype, p.c.dtype, p.d.dtype, p.e.dtype, p.f.dtype, p.g.dtype])
      .toEqual(['<f4', '|u1', '<i4', '<i2', '<u4', '<i8', '|u1']);
    expect(p.g.length).toBe(3);
  });

  test('non-finite numbers survive (JSON alone would turn them into null)', () => {
    const p = JSON.parse(packPayload({ a: NaN, b: Infinity, c: -Infinity, d: [1, NaN] }).json);
    expect(p).toEqual({
      a: { [NUM_KEY]: 'nan' }, b: { [NUM_KEY]: 'inf' }, c: { [NUM_KEY]: '-inf' },
      d: [1, { [NUM_KEY]: 'nan' }],
    });
  });

  test('a Map payload is sent as an object, and a function is refused by path', () => {
    expect(JSON.parse(packPayload({ m: new Map([['k', 2]]) }).json)).toEqual({ m: { k: 2 } });
    expect(() => packPayload({ sets: [{ cb: () => 1 }] })).toThrow(/payload\.sets\[0\]\.cb/);
  });
});
