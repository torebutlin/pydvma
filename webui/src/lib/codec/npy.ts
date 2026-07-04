// .npy v1/v2 codec — the subset pydvma's .dvma containers use.
// Complex arrays are exposed interleaved [re, im, ...] with isComplex=true.
export interface NpyArray {
  shape: number[];
  isComplex: boolean;
  data: Float64Array | Float32Array | Uint8Array;
}

const MAGIC = [0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59];

// Bytes per element for every supported dtype. Single source of the
// "unsupported dtype" rejection — the parse switch is exhaustive over these keys.
const ELEM_BYTES = { '<f8': 8, '<f4': 4, '<c16': 16, '|b1': 1, '<i8': 8, '<i4': 4 } as const;

/**
 * Reorder a typed array from Fortran (column-major) storage to C (row-major)
 * order for the given logical `shape`. `perElem` is the number of scalar
 * slots per logical element (2 for interleaved complex, else 1). numpy can
 * save a `fortran_order: True` .npy — pydvma's legacy sonogram/coherence
 * arrays are stored this way — and the whole rest of this codebase assumes
 * C-order buffers, so we transpose on read once rather than thread an order
 * flag everywhere. 0/1-D arrays are already identical in both orders and
 * pass through untouched.
 */
function fortranToC<T extends Float64Array | Float32Array | Uint8Array>(
  src: T, shape: number[], perElem: number,
): T {
  if (shape.length < 2) return src;
  const n = shape.reduce((a, b) => a * b, 1);
  // C strides (row-major) and F strides (column-major) over logical elements.
  const cStride = new Array(shape.length).fill(1);
  for (let d = shape.length - 2; d >= 0; d--) cStride[d] = cStride[d + 1] * shape[d + 1];
  const fStride = new Array(shape.length).fill(1);
  for (let d = 1; d < shape.length; d++) fStride[d] = fStride[d - 1] * shape[d - 1];
  const out = new (src.constructor as new (len: number) => T)(n * perElem);
  const idx = new Array(shape.length).fill(0);
  for (let c = 0; c < n; c++) {
    // Multi-index for C-order position c → source offset via F strides.
    let rem = c;
    for (let d = 0; d < shape.length; d++) { idx[d] = Math.floor(rem / cStride[d]); rem -= idx[d] * cStride[d]; }
    let f = 0;
    for (let d = 0; d < shape.length; d++) f += idx[d] * fStride[d];
    for (let e = 0; e < perElem; e++) out[c * perElem + e] = src[f * perElem + e];
  }
  return out;
}

export function parseNpy(bytes: Uint8Array): NpyArray {
  if (bytes.length < 10) throw new Error('not a .npy file');
  for (let i = 0; i < 6; i++) if (bytes[i] !== MAGIC[i]) throw new Error('not a .npy file');
  const major = bytes[6];
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerLen = major >= 2 ? view.getUint32(8, true) : view.getUint16(8, true);
  const dataStart = (major >= 2 ? 12 : 10) + headerLen;
  const header = new TextDecoder('ascii').decode(bytes.subarray(major >= 2 ? 12 : 10, dataStart));

  const descr = /'descr':\s*'([^']+)'/.exec(header)?.[1];
  const fortran = /'fortran_order':\s*(True|False)/.exec(header)?.[1];
  const shapeTxt = /'shape':\s*\(([^)]*)\)/.exec(header)?.[1];
  if (!descr || !fortran || shapeTxt === undefined) throw new Error(`bad npy header: ${header}`);
  const isFortran = fortran === 'True';
  const shape = shapeTxt.split(',').map(s => s.trim()).filter(Boolean).map(Number);
  if (shape.some(n => !Number.isInteger(n) || n < 0)) throw new Error(`bad npy shape: (${shapeTxt})`);
  const count = shape.reduce((a, b) => a * b, 1);

  const elemBytes = (ELEM_BYTES as Record<string, number>)[descr];
  if (elemBytes === undefined) throw new Error(`unsupported dtype ${descr}`);

  // slice() copies -> result buffers are always 8-byte aligned
  const raw = bytes.slice(dataStart);
  if (raw.byteLength < count * elemBytes)
    throw new Error(`truncated .npy: need ${count * elemBytes} data bytes, got ${raw.byteLength}`);
  // Fortran-stored multi-D arrays are transposed to C-order here so every
  // downstream consumer sees the same row-major layout.
  const fix = <T extends Float64Array | Float32Array | Uint8Array>(d: T, perElem: number): T =>
    isFortran ? fortranToC(d, shape, perElem) : d;
  switch (descr as keyof typeof ELEM_BYTES) {
    case '<f8': return { shape, isComplex: false, data: fix(new Float64Array(raw.buffer, 0, count), 1) };
    case '<f4': return { shape, isComplex: false, data: fix(new Float32Array(raw.buffer, 0, count), 1) };
    case '<c16': return { shape, isComplex: true, data: fix(new Float64Array(raw.buffer, 0, count * 2), 2) };
    case '|b1': return { shape, isComplex: false, data: fix(raw.subarray(0, count), 1) };
    case '<i8': {
      // int64 widened to float64: exact only within ±2^53
      const big = new BigInt64Array(raw.buffer, 0, count);
      const out = new Float64Array(count);
      for (let i = 0; i < count; i++) out[i] = Number(big[i]);
      return { shape, isComplex: false, data: fix(out, 1) };
    }
    case '<i4': {
      const ints = new Int32Array(raw.buffer, 0, count);
      return { shape, isComplex: false, data: fix(Float64Array.from(ints), 1) };
    }
  }
}

export function serializeNpy(a: NpyArray): Uint8Array {
  const descr = a.isComplex ? '<c16' : a.data instanceof Float32Array ? '<f4'
    : a.data instanceof Uint8Array ? '|b1' : '<f8';
  const shape = a.shape.length === 1 ? `(${a.shape[0]},)` : `(${a.shape.join(', ')})`;
  let header = `{'descr': '${descr}', 'fortran_order': False, 'shape': ${shape}, }`;
  const unpadded = 10 + header.length + 1;
  header = header + ' '.repeat((64 - (unpadded % 64)) % 64) + '\n';
  if (header.length > 0xffff) throw new Error('npy header too long');

  const body = a.data instanceof Uint8Array
    ? a.data
    : new Uint8Array(a.data.buffer, a.data.byteOffset, a.data.byteLength);
  const out = new Uint8Array(10 + header.length + body.byteLength);
  out.set(MAGIC, 0); out[6] = 1; out[7] = 0;
  new DataView(out.buffer).setUint16(8, header.length, true);
  out.set(new TextEncoder().encode(header), 10);
  out.set(body, 10 + header.length);
  return out;
}
