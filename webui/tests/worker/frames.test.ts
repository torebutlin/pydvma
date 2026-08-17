// frames.test.ts — the JS mirror of pydvma/engine_host.py's frame codec.
//
// pydvma/engine_host.py's module docstring (plus the protocol block in
// dev/plans/2026-08-17-native-engine-plan.md) is the normative spec for BOTH
// sides; tests/test_engine_host.py pins the exact wire bytes on the Python
// side. This file mirrors those pins here so the two implementations can
// never silently drift: golden fixtures are copied from the REAL Python
// tests (not paraphrased), and the truncation/kind/multiple-of-8 error
// paths are exercised the same way engine_host.decode_frame is.
import { describe, expect, test } from 'vitest';
import { encodeFrame, decodeFrame } from '../../src/lib/worker/frames';

describe('engine frame codec: round-trips', () => {
  test('scalars round-trip, including null', () => {
    const h = { id: 1, op: 'calc_fft', payload: { fs: 8000, window: null } };
    expect(decodeFrame(encodeFrame(h))).toEqual(h);
  });

  test('typed arrays lift recursively (nested in arrays-of-objects), bytes kind, scalars preserved', () => {
    const a = Float64Array.from([1, 2, 3]);
    const h = {
      id: 2,
      op: 'calc_tf_averaged',
      payload: {
        sets: [{ time_data: a, fs: 100 }],
        blob: Uint8Array.from([0, 1, 2]),
      },
    };
    const out = decodeFrame(encodeFrame(h)) as any;
    expect(out.payload.sets[0].time_data).toBeInstanceOf(Float64Array);
    expect([...out.payload.sets[0].time_data]).toEqual([1, 2, 3]);
    expect(out.payload.sets[0].fs).toBe(100);
    expect(out.id).toBe(2);
    expect(out.op).toBe('calc_tf_averaged');
    expect(out.payload.blob).toBeInstanceOf(Uint8Array);
    expect([...out.payload.blob]).toEqual([0, 1, 2]);
  });

  test('empty blobs of both kinds round-trip', () => {
    const h = { a: Float64Array.from([]), b: new Uint8Array(0) };
    const out = decodeFrame(encodeFrame(h)) as any;
    expect(out.a).toBeInstanceOf(Float64Array);
    expect(out.a.length).toBe(0);
    expect(out.b).toBeInstanceOf(Uint8Array);
    expect(out.b.length).toBe(0);
  });
});

describe('engine frame codec: Python-layout golden decode', () => {
  test('hand-built Python-shaped frame decodes (u32 LE + JSON + blob)', () => {
    // {"x": {"__bin__": 0, "kind": "f8", "len": 8}} + one float64 blob (42.5).
    // Built with DataView, not via our own encoder -- this pins endianness
    // and layout against a hand-written fixture, mirroring engine_host.py's
    // wire format directly rather than testing encodeFrame against itself.
    const head = new TextEncoder().encode(
      JSON.stringify({ x: { __bin__: 0, kind: 'f8', len: 8 } }),
    );
    const buf = new Uint8Array(4 + head.length + 8);
    new DataView(buf.buffer).setUint32(0, head.length, true);
    buf.set(head, 4);
    new DataView(buf.buffer).setFloat64(4 + head.length, 42.5, true);

    const out = decodeFrame(buf.buffer) as any;
    expect(out.x).toBeInstanceOf(Float64Array);
    expect(out.x[0]).toBe(42.5);
  });
});

describe('engine frame codec: cross-language golden encode pins', () => {
  // These three fixtures are copied VERBATIM (not paraphrased) from
  // tests/test_engine_host.py's test_encode_frame_exact_bytes_single_array,
  // test_encode_frame_exact_bytes_bytes_kind, and
  // test_encode_frame_lays_blobs_in_ascending_index_order. Header JSON text
  // need not match byte-for-byte between Python and JS (different
  // json-encoder escaping/whitespace conventions are both legal per the
  // module docstring) -- so each pin re-parses the DECODED header tree +
  // raw blob tail rather than diffing whole-frame bytes.

  test('single f8 array: header tree + blob bytes match the Python fixture', () => {
    // Python: arr = np.array([1.0, 2.0], dtype='<f8'); encode_frame({'x': arr})
    // -> header {'x': {'__bin__': 0, 'kind': 'f8', 'len': 16}} + arr.tobytes().
    const arr = Float64Array.from([1.0, 2.0]);
    const frame = encodeFrame({ x: arr });

    const view = new DataView(frame);
    const n = view.getUint32(0, true);
    const header = JSON.parse(new TextDecoder().decode(new Uint8Array(frame, 4, n)));
    expect(header).toEqual({ x: { __bin__: 0, kind: 'f8', len: 16 } });

    const tail = new Uint8Array(frame, 4 + n);
    // IEEE-754 little-endian float64 bytes are platform-independent, so a
    // JS-side Float64Array's own bytes are bit-identical to numpy's
    // arr.astype('<f8').tobytes() -- this is a real cross-language pin, not
    // a JS-encodes-itself tautology.
    const expectedBlob = new Uint8Array(Float64Array.from([1.0, 2.0]).buffer);
    expect(tail).toEqual(expectedBlob);
  });

  test("bytes kind literal: header tree + blob bytes match the Python fixture", () => {
    // Python: encode_frame({'b': b'ab'}) -> header
    // {'b': {'__bin__': 0, 'kind': 'bytes', 'len': 2}} + b'ab'.
    const frame = encodeFrame({ b: Uint8Array.from([0x61, 0x62]) }); // 'ab'

    const view = new DataView(frame);
    const n = view.getUint32(0, true);
    const header = JSON.parse(new TextDecoder().decode(new Uint8Array(frame, 4, n)));
    expect(header).toEqual({ b: { __bin__: 0, kind: 'bytes', len: 2 } });

    const tail = new Uint8Array(frame, 4 + n);
    expect([...tail]).toEqual([0x61, 0x62]);
  });

  test('blobs lay out end-to-end in ascending __bin__ index order', () => {
    // Python: encode_frame({'a': [1.0], 'b': [2.0, 2.0], 'c': [3.0, 3.0, 3.0]})
    // -> tail == a.tobytes() + b.tobytes() + c.tobytes().
    const a = Float64Array.from([1.0]);
    const b = Float64Array.from([2.0, 2.0]);
    const c = Float64Array.from([3.0, 3.0, 3.0]);
    const frame = encodeFrame({ a, b, c });

    const view = new DataView(frame);
    const n = view.getUint32(0, true);
    const tail = new Uint8Array(frame, 4 + n);
    const expected = new Uint8Array(6 * 8); // 1 + 2 + 3 elements * 8 bytes
    expected.set(new Uint8Array(a.buffer), 0);
    expected.set(new Uint8Array(b.buffer), 8);
    expected.set(new Uint8Array(c.buffer), 24);
    expect(tail).toEqual(expected);
  });
});

describe('engine frame codec: exact-fit validation', () => {
  function buildTwoArrayFrame() {
    // Mirrors tests/test_engine_host.py's
    // test_decode_frame_raises_on_truncated_frame fixture shape.
    const a = Float64Array.from([0, 1, 2, 3]);
    const b = Float64Array.from([0, 1, 2, 3]);
    return encodeFrame({ sets: [{ a, b }] });
  }

  test('truncated frame (8-aligned chop) throws', () => {
    const frame = buildTwoArrayFrame();
    // Chop exactly one f8 element off the tail -- still 8-aligned, so a
    // naive slice-and-decode would silently hand back a short array
    // instead of raising.
    const truncated = frame.slice(0, frame.byteLength - 8);
    expect(() => decodeFrame(truncated)).toThrow(/truncat/i);
  });

  test('trailing extra bytes past the declared blob region throws', () => {
    const frame = buildTwoArrayFrame();
    const padded = new Uint8Array(frame.byteLength + 8);
    padded.set(new Uint8Array(frame), 0);
    expect(() => decodeFrame(padded.buffer)).toThrow(/truncat/i);
  });
});

describe('engine frame codec: kind and length validation', () => {
  test('f8 blob len not a multiple of 8 throws', () => {
    // Mirrors test_decode_frame_raises_when_f8_blob_len_not_multiple_of_8:
    // the blob region itself fits exactly (7 bytes present, 7 declared) so
    // the exact-fit check passes, but 7 isn't a whole number of f8
    // elements -- must be rejected before any typed-array construction.
    const head = new TextEncoder().encode(
      JSON.stringify({ x: { __bin__: 0, kind: 'f8', len: 7 } }),
    );
    const buf = new Uint8Array(4 + head.length + 7);
    new DataView(buf.buffer).setUint32(0, head.length, true);
    buf.set(head, 4);
    buf.set(new TextEncoder().encode('1234567'), 4 + head.length);
    expect(() => decodeFrame(buf.buffer)).toThrow(/multiple of 8/);
  });

  test('unknown blob kind throws', () => {
    // Mirrors test_decode_frame_raises_on_unknown_blob_kind.
    const head = new TextEncoder().encode(
      JSON.stringify({ x: { __bin__: 0, kind: 'weird', len: 3 } }),
    );
    const buf = new Uint8Array(4 + head.length + 3);
    new DataView(buf.buffer).setUint32(0, head.length, true);
    buf.set(head, 4);
    buf.set(new TextEncoder().encode('abc'), 4 + head.length);
    expect(() => decodeFrame(buf.buffer)).toThrow(/unknown blob kind/i);
  });
});

describe('engine frame codec: non-finite scalars', () => {
  test('NaN / Infinity / -Infinity cross as null, nested too', () => {
    // Pins JSON.stringify's native behaviour (JSON.stringify(NaN) === 'null')
    // as the CORRECT wire behaviour -- it already matches engine_host.py's
    // sanitiser, so no extra encoder code is needed, but the behaviour must
    // stay pinned so a future refactor can't accidentally change it.
    const h = { x: NaN, y: Infinity, nested: [{ q: -Infinity }] };
    const out = decodeFrame(encodeFrame(h)) as any;
    expect(out.x).toBeNull();
    expect(out.y).toBeNull();
    expect(out.nested[0].q).toBeNull();
  });

  test('finite numbers and array VALUES are unaffected by the sanitiser', () => {
    const h = { finite: 1.5, arr: Float64Array.from([NaN, 1.0]) };
    const out = decodeFrame(encodeFrame(h)) as any;
    expect(out.finite).toBe(1.5);
    expect(out.arr).toBeInstanceOf(Float64Array);
    expect(Number.isNaN(out.arr[0])).toBe(true);
    expect(out.arr[1]).toBe(1.0);
  });
});

describe('engine frame codec: utf-8 header length', () => {
  test('header_len counts utf-8 BYTES, not characters, and round-trips', () => {
    const h = { op: 'µ-test', payload: {} };
    const frame = encodeFrame(h);
    const out = decodeFrame(frame);
    expect(out).toEqual(h);

    const n = new DataView(frame).getUint32(0, true);
    const headerText = JSON.stringify(h);
    const byteLen = new TextEncoder().encode(headerText).length;
    expect(n).toBe(byteLen);
    // 'µ' is one UTF-16 code unit (String.length) but two UTF-8 bytes --
    // the "bytes never characters" pin.
    expect(byteLen).toBeGreaterThan(headerText.length);
  });
});

describe('engine frame codec: rejects non-f8/bytes typed array views', () => {
  // Without this guard, lift() falls through to the plain-object branch and
  // silently mis-encodes e.g. Int32Array.from([1,2,3]) as
  // {"0":1,"1":2,"2":3} with no error -- Python's encode_frame raises
  // TypeError for any non-<f8> ndarray dtype instead of silently
  // converting, and the JS side must match. Float32Array is pervasive in
  // this codebase's audio paths, so this trap is realistic, not academic.
  test('Int32Array throws instead of silently mis-encoding', () => {
    expect(() => encodeFrame({ x: Int32Array.from([1, 2, 3]) })).toThrow(/float64array/i);
  });

  test('Float32Array throws instead of silently mis-encoding', () => {
    let caught: unknown;
    try {
      encodeFrame({ x: Float32Array.from([1, 2, 3]) });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(TypeError);
    expect(String((caught as Error).message)).toMatch(/float64array/i);
    expect(String((caught as Error).message)).toMatch(/Float32Array/);
  });

  test('DataView (an ArrayBufferView that is neither typed array kind) also throws', () => {
    const dv = new DataView(new ArrayBuffer(8));
    expect(() => encodeFrame({ x: dv })).toThrow(/float64array/i);
  });
});

describe('engine frame codec: byteOffset view handling', () => {
  test('a subarray view (non-zero byteOffset) round-trips only its own elements, isolated from later buffer mutation', () => {
    const backing = Float64Array.from([10, 20, 30, 40]);
    const view = backing.subarray(1, 3); // [20, 30] -- byteOffset = 8, not 0
    expect(view.byteOffset).toBe(8);
    expect(view.length).toBe(2);

    const frame = encodeFrame({ x: view });

    // Mutate the backing buffer AFTER encoding -- pins that encodeFrame
    // copied out the view's own bytes (buffer.slice) rather than keeping a
    // reference into the live, mutable backing buffer.
    backing[1] = 999;
    backing[2] = 999;

    const out = decodeFrame(frame) as any;
    expect(out.x).toBeInstanceOf(Float64Array);
    expect([...out.x]).toEqual([20, 30]);
  });
});
