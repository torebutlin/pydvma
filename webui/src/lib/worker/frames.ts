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
// never passes through JSON.stringify, so it carries NaN/Inf natively. Blob
// bytes are copied verbatim (memcpy), never reinterpreted -- this assumes a
// little-endian host, true of every target runtime here (browsers, Node,
// and wasm32).

const TEXT_ENCODER = new TextEncoder();
const TEXT_DECODER = new TextDecoder();

/** A lifted-binary-value placeholder in the decoded (or about-to-be-encoded) header tree. */
interface BinPlaceholder {
  __bin__: number;
  kind: 'f8' | 'bytes';
  len: number;
}

/** Anything carrying the reserved `__bin__` key, before its value has been validated. */
interface RawBinCandidate {
  __bin__: unknown;
  kind?: unknown;
  len?: unknown;
}

/**
 * `__bin__` is a RESERVED key: `engine_host.py` treats ANY dict carrying it
 * as a placeholder purely by key PRESENCE (`if '__bin__' in v`), not by
 * checking the value's type -- no legitimate op payload ever contains this
 * key. Mirrored here the same way: presence alone routes into
 * {@link asPlaceholder}, which validates the value and throws on a
 * malformed one rather than letting it silently fall through to the
 * generic-object walk below (which would otherwise let a corrupt frame's
 * `__bin__: "not a number"` masquerade as ordinary payload data instead of
 * failing loudly).
 */
function hasBinKey(v: unknown): v is RawBinCandidate {
  return v !== null && typeof v === 'object' && '__bin__' in v;
}

/** Validate + narrow a `__bin__`-bearing object into a real placeholder. */
function asPlaceholder(v: RawBinCandidate): BinPlaceholder {
  if (typeof v.__bin__ !== 'number') {
    throw new TypeError(
      `__bin__ must be a number, got ${typeof v.__bin__} (${JSON.stringify(v.__bin__)})`,
    );
  }
  return v as BinPlaceholder;
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
 * incremental resizing). `blobs` holds the ORIGINAL views handed in, not
 * copies -- `encodeFrame` is fully synchronous end to end, so nothing can
 * mutate a view's backing buffer between `lift` and the blit loop below,
 * which copies each blob's own byte range into the frame exactly once.
 * That is the single copy each blob's bytes take on their way into the
 * frame, mirroring `engine_host.encode_frame`'s single-allocation,
 * single-copy guarantee (a raw memoryview blit in Python, a typed-array
 * blit here). A caller mutating a view's buffer AFTER `encodeFrame`
 * returns is fine -- the frame's bytes are already committed by then.
 */
export function encodeFrame(header: unknown): ArrayBuffer {
  const blobs: ArrayBufferView[] = [];

  function lift(v: unknown): unknown {
    if (v instanceof Float64Array) {
      blobs.push(v);
      return { __bin__: blobs.length - 1, kind: 'f8', len: v.byteLength };
    }
    if (v instanceof Uint8Array) {
      blobs.push(v);
      return { __bin__: blobs.length - 1, kind: 'bytes', len: v.byteLength };
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

  const head = TEXT_ENCODER.encode(JSON.stringify(lift(header)));
  const blobTotal = blobs.reduce((n, b) => n + b.byteLength, 0);
  const out = new Uint8Array(4 + head.byteLength + blobTotal);
  new DataView(out.buffer).setUint32(0, head.byteLength, true);
  out.set(head, 4);
  let pos = 4 + head.byteLength;
  for (const b of blobs) {
    // Wrap each view's own byte range as a fresh Uint8Array (zero-copy --
    // same buffer, just a Uint8-typed window onto it) so `set` performs a
    // raw byte-for-byte blit. Passing a Float64Array to Uint8Array#set
    // directly would NOT copy bytes: TypedArray#set between differing
    // element kinds runs a VALUE conversion per element (ToUint8 on each
    // float), silently corrupting the blob -- this wrap is what makes the
    // single `set` below a real memcpy instead of that trap.
    out.set(new Uint8Array(b.buffer, b.byteOffset, b.byteLength), pos);
    pos += b.byteLength;
  }
  return out.buffer;
}

/**
 * Decode one binary frame back into the header tree; the inverse of {@link encodeFrame}.
 *
 * Accepts an `ArrayBuffer` (what `WebSocket` with `binaryType = 'arraybuffer'`
 * delivers) or a `Uint8Array` (normalised the same way, including one with a
 * non-zero `byteOffset` -- e.g. a view into a pooled Node `Buffer` -- since
 * every offset below is computed relative to `bytes.byteOffset`, never 0).
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
 * `"f8"` placeholder's `len` isn't a whole number of float64 elements, if a
 * placeholder names an unrecognised `kind`, or if a `__bin__`-bearing object
 * has a non-numeric `__bin__` (see {@link asPlaceholder}).
 */
export function decodeFrame(data: ArrayBuffer | Uint8Array): unknown {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const n = view.getUint32(0, true);
  const header = JSON.parse(TEXT_DECODER.decode(bytes.subarray(4, 4 + n)));
  const blobBase = 4 + n;

  // Blob k starts after the lengths of blobs 0..k-1; collect lengths by
  // walking once for placeholders, then lay out offsets in ASCENDING INDEX
  // order (never JSON-tree traversal order -- see the module docstring).
  const lens = new Map<number, number>();
  (function index(v: unknown): void {
    if (Array.isArray(v)) {
      v.forEach(index);
    } else if (hasBinKey(v)) {
      const p = asPlaceholder(v);
      lens.set(p.__bin__, p.len);
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
    if (hasBinKey(v)) {
      const p = asPlaceholder(v);
      const start = starts.get(p.__bin__)!;
      if (p.kind === 'f8') {
        if (p.len % 8 !== 0) {
          throw new Error(`f8 blob len must be a multiple of 8, got ${p.len}`);
        }
        // slice() copies -- blob starts are JSON-header-length-dependent,
        // so 8-byte alignment (Float64Array requires it) is luck, not
        // guaranteed; a raw view would also pin the WHOLE frame buffer
        // alive for as long as this one decoded array survives. Same two
        // reasons npy.ts's parseNpy copies its data region instead of
        // viewing it in place.
        return new Float64Array(
          bytes.buffer.slice(bytes.byteOffset + start, bytes.byteOffset + start + p.len),
        );
      }
      if (p.kind === 'bytes') {
        return new Uint8Array(
          bytes.buffer.slice(bytes.byteOffset + start, bytes.byteOffset + start + p.len),
        );
      }
      throw new Error(`unknown blob kind ${JSON.stringify(p.kind)}`);
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
