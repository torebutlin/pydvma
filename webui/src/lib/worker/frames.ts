// frames.ts — binary codec for the /engine websocket protocol.
//
// Mirrors pydvma/engine_host.py EXACTLY; that module's docstring (plus the
// protocol block in dev/plans/2026-08-17-native-engine-plan.md) is the
// normative spec for BOTH this codec and the Python one. One binary frame =
// [u32 LE header_len][header JSON utf-8][blobs end-to-end in ascending
// __bin__ index order]. header_len counts BYTES of the encoded JSON text --
// never characters, never elements (JS strings count UTF-16 code units;
// TextEncoder gives the real byte length). Float64Array / Uint8Array values
// anywhere in the tree are lifted out into the trailing blobs and replaced
// in place by {__bin__, kind: 'f8'|'bytes', len} placeholders (len always in
// BYTES). The blob region must fit EXACTLY -- no padding, no trailing bytes;
// a decode where the declared total disagrees with the bytes actually
// present is rejected, whichever direction the mismatch runs. Non-finite
// scalar numbers (NaN/Infinity/-Infinity) are not valid JSON, so
// JSON.stringify already turns a bare scalar into `null` -- exactly the wire
// behaviour engine_host.py's sanitiser produces, so no extra code is needed
// here. Array VALUES are unaffected: an "f8" blob is raw IEEE-754 bytes that
// never passes through JSON.stringify, so it carries NaN/Inf natively.

/** A lifted-binary-value marker in the decoded (or about-to-be-encoded) header tree. */
interface BinPlaceholder {
  __bin__: number;
  kind: 'f8' | 'bytes';
  len: number;
}

/** `__bin__` is reserved: any dict/object carrying it (with a numeric value) is a placeholder. */
function isPlaceholder(v: unknown): v is BinPlaceholder {
  return v !== null && typeof v === 'object' && typeof (v as { __bin__?: unknown }).__bin__ === 'number';
}

/**
 * Encode `header` into one binary frame; the inverse of {@link decodeFrame}.
 *
 * `header` is a JSON-able tree that may also hold `Float64Array` / `Uint8Array`
 * values anywhere inside it -- see the module docstring for the full wire
 * format. The lift walk is recursive through plain objects and arrays
 * (payloads like `calc_fit`'s `sets` nest arrays inside lists of dicts).
 * Non-finite scalar numbers are left as-is for `JSON.stringify` to sanitise
 * to `null` natively -- matching the Python side's `allow_nan=False` +
 * pre-sanitise behaviour without any extra code.
 *
 * Any OTHER `ArrayBufferView` (`Int32Array`, `Float32Array`, `DataView`,
 * ...) throws `TypeError` rather than silently falling into the plain-
 * object branch (which would serialise it as `{"0":1,"1":2,...}` with no
 * error) -- mirrors `engine_host.encode_frame` raising `TypeError` for any
 * non-`<f8>` ndarray dtype instead of silently converting.
 *
 * Builds one `Uint8Array` sized from the summed header + blob lengths (no
 * incremental resizing) and blits each blob straight into it, mirroring
 * `engine_host.encode_frame`'s single-allocation guarantee.
 */
export function encodeFrame(header: unknown): ArrayBuffer {
  const blobs: Uint8Array[] = [];

  function lift(v: unknown): unknown {
    if (v instanceof Float64Array) {
      // Copy out only this view's own bytes -- a typed array can be a
      // window onto a larger/shared buffer (byteOffset != 0, or a buffer
      // that outlives this call), and the wire blob must contain exactly
      // its own elements, nothing else from the underlying buffer.
      const b = new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength));
      blobs.push(b);
      return { __bin__: blobs.length - 1, kind: 'f8', len: b.byteLength };
    }
    if (v instanceof Uint8Array) {
      const b = new Uint8Array(v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength));
      blobs.push(b);
      return { __bin__: blobs.length - 1, kind: 'bytes', len: b.byteLength };
    }
    if (ArrayBuffer.isView(v)) {
      // Any other typed-array view (Int32Array, Float32Array, DataView, ...)
      // -- without this check it falls through to the plain-object branch
      // below and silently mis-encodes as {"0":1,"1":2,...}. Float32Array
      // is pervasive in this codebase's audio paths, so this trap is real.
      throw new TypeError(
        `engine frames carry Float64Array/Uint8Array only, got ${(v as ArrayBufferView).constructor.name}`,
      );
    }
    if (Array.isArray(v)) return v.map(lift);
    if (v !== null && typeof v === 'object') {
      const out: Record<string, unknown> = {};
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) out[k] = lift(x);
      return out;
    }
    return v;
  }

  const head = new TextEncoder().encode(JSON.stringify(lift(header)));
  const blobTotal = blobs.reduce((n, b) => n + b.byteLength, 0);
  const out = new Uint8Array(4 + head.byteLength + blobTotal);
  new DataView(out.buffer).setUint32(0, head.byteLength, true);
  out.set(head, 4);
  let pos = 4 + head.byteLength;
  for (const b of blobs) {
    out.set(b, pos);
    pos += b.byteLength;
  }
  return out.buffer;
}

/**
 * Decode one binary frame back into the header tree; the inverse of {@link encodeFrame}.
 *
 * Accepts an `ArrayBuffer` (what `WebSocket` with `binaryType = 'arraybuffer'`
 * delivers) or a `Uint8Array` (normalised the same way, in case one has
 * already been unwrapped by the caller).
 *
 * Placeholders are replaced by `Float64Array` / `Uint8Array` values
 * reconstructed from the frame's blob tail. Every blob's start offset is
 * computed purely from the declared `len` of the placeholders walked in
 * ASCENDING `__bin__` INDEX order -- never from wherever a placeholder
 * happens to sit in the JSON tree -- so key/array reordering in a payload
 * can never desync the offsets (mirrors `engine_host.decode_frame` exactly).
 *
 * Throws if the blob region's declared total size disagrees with the bytes
 * actually present (truncated OR corrupt with trailing bytes -- the format
 * has no padding, so this must be an exact fit both directions), if an
 * `"f8"` placeholder's `len` isn't a whole number of float64 elements, or if
 * a placeholder names an unrecognised `kind`.
 */
export function decodeFrame(data: ArrayBuffer | Uint8Array): unknown {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const n = view.getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(4, 4 + n)));
  const blobBase = 4 + n;

  // Blob k starts after the lengths of blobs 0..k-1; collect lengths by
  // walking once for placeholders, then lay out offsets in ASCENDING INDEX
  // order (never JSON-tree traversal order -- see the module docstring).
  const lens = new Map<number, number>();
  (function index(v: unknown): void {
    if (Array.isArray(v)) {
      v.forEach(index);
    } else if (isPlaceholder(v)) {
      lens.set(v.__bin__, v.len);
    } else if (v !== null && typeof v === 'object') {
      Object.values(v as Record<string, unknown>).forEach(index);
    }
  })(header);

  const starts = new Map<number, number>();
  let pos = blobBase;
  for (const k of [...lens.keys()].sort((a, b) => a - b)) {
    starts.set(k, pos);
    pos += lens.get(k)!;
  }

  if (pos !== bytes.byteLength) {
    throw new Error(
      `engine frame truncated or corrupt: blob region is ${bytes.byteLength - blobBase} ` +
        `bytes, header declares ${pos - blobBase}`,
    );
  }

  function restore(v: unknown): unknown {
    if (Array.isArray(v)) return v.map(restore);
    if (isPlaceholder(v)) {
      const start = starts.get(v.__bin__)!;
      if (v.kind === 'f8') {
        if (v.len % 8 !== 0) {
          throw new Error(`f8 blob len must be a multiple of 8, got ${v.len}`);
        }
        return new Float64Array(
          bytes.buffer.slice(bytes.byteOffset + start, bytes.byteOffset + start + v.len),
        );
      }
      if (v.kind === 'bytes') {
        return new Uint8Array(
          bytes.buffer.slice(bytes.byteOffset + start, bytes.byteOffset + start + v.len),
        );
      }
      throw new Error(`unknown blob kind ${JSON.stringify(v.kind)}`);
    }
    if (v !== null && typeof v === 'object') {
      const out: Record<string, unknown> = {};
      for (const [k, x] of Object.entries(v as Record<string, unknown>)) out[k] = restore(x);
      return out;
    }
    return v;
  }

  return restore(header);
}
