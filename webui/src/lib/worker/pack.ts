// pack.ts — hand an engine call's payload to Python as JSON text plus raw
// byte buffers, so that no JavaScript number crosses into Python one by one.
//
// WHY. pyodide converts each JS number to Python in one JS function
// (`js2python_convertImmutable`: `isSafeInteger ? PyLong : PyFloat`), and a
// numpy `np.asarray(jsproxy)` on a typed array calls it once per element —
// JsProxy has no buffer interface. Safari 27.2's JIT miscompiles that
// function once it is hot (about 11 600 calls in; measured with a probe on
// 2026-11-04): from then on a double crosses as the low 32 bits of its bit
// pattern, as if it were a boxed int32, so 246.82 arrives as 1889785610 and
// 10000.0 as 0. The first modal-fit restore after loading the 4C6 beam data
// pushes 23 sets x 50 002 numbers through it, after which every array AND
// every scalar the engine received was garbage (fit lines at 10^9 Hz, Calc
// TF dividing by zero). Typed arrays therefore travel as their bytes
// (`to_bytes`, a single memory copy, ~500x faster as well), and the rest of
// the payload as JSON text, which Python parses itself.
//
// The Python side is `pydvma.engine._call_packed` / `_unpack_payload`.

/** The key marking a placeholder for buffer `k` in the JSON text. */
export const BUF_KEY = '__pydvma_buf__';
/** The key marking a non-finite number (JSON has no NaN or Infinity). */
export const NUM_KEY = '__pydvma_num__';

/** numpy dtype strings for the typed arrays a payload may carry. */
const DTYPES: Record<string, string> = {
  Float64Array: '<f8',
  Float32Array: '<f4',
  Int8Array: '|i1',
  Uint8Array: '|u1',
  Uint8ClampedArray: '|u1',
  Int16Array: '<i2',
  Uint16Array: '<u2',
  Int32Array: '<i4',
  Uint32Array: '<u4',
  BigInt64Array: '<i8',
  BigUint64Array: '<u8',
};

export interface PackedPayload {
  /** The payload with every typed array replaced by a placeholder. */
  json: string;
  /** Each placeholder's bytes, in placeholder order. */
  bufs: Uint8Array[];
}

/**
 * Split `payload` into JSON text and the bytes of its typed arrays.
 *
 * A typed array (or DataView / ArrayBuffer, sent as bytes) becomes
 * `{"__pydvma_buf__": k, "dtype": "<f8", "length": n}` and its bytes go to
 * `bufs[k]` (a view, not a copy). NaN and ±Infinity become
 * `{"__pydvma_num__": "nan" | "inf" | "-inf"}`, and `undefined` becomes
 * `null`, as pyodide's own conversion gave Python `None` for both
 * `undefined` and (at the top level) `null`. Plain objects and arrays are
 * walked; anything else that JSON cannot carry (a function, a BigInt
 * scalar) throws, naming its path.
 */
export function packPayload(payload: unknown): PackedPayload {
  const bufs: Uint8Array[] = [];
  const walk = (v: unknown, path: string): unknown => {
    if (v === undefined || v === null) return null;
    if (typeof v === 'number') {
      if (Number.isFinite(v)) return v;
      return { [NUM_KEY]: Number.isNaN(v) ? 'nan' : v > 0 ? 'inf' : '-inf' };
    }
    if (typeof v === 'string' || typeof v === 'boolean') return v;
    if (ArrayBuffer.isView(v) || v instanceof ArrayBuffer) {
      const name = v instanceof ArrayBuffer ? 'ArrayBuffer' : v.constructor.name;
      const dtype = v instanceof ArrayBuffer || v instanceof DataView ? '|u1' : DTYPES[name];
      if (!dtype) throw new Error(`packPayload: unsupported array type ${name} at ${path}`);
      const bytes = v instanceof ArrayBuffer
        ? new Uint8Array(v)
        : new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
      const length = v instanceof ArrayBuffer || v instanceof DataView
        ? bytes.byteLength
        : (v as unknown as { length: number }).length;
      bufs.push(bytes);
      return { [BUF_KEY]: bufs.length - 1, dtype, length };
    }
    if (Array.isArray(v)) return v.map((x, i) => walk(x, `${path}[${i}]`));
    if (v instanceof Map) {
      const o: Record<string, unknown> = {};
      for (const [k, x] of v) o[String(k)] = walk(x, `${path}.${String(k)}`);
      return o;
    }
    if (typeof v === 'object') {
      const o: Record<string, unknown> = {};
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) o[k] = walk(x, `${path}.${k}`);
      return o;
    }
    throw new Error(`packPayload: cannot send a ${typeof v} at ${path}`);
  };
  const json = JSON.stringify(walk(payload, 'payload'));
  return { json, bufs };
}
