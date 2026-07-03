// .npy v1/v2 codec — the subset pydvma's .dvma containers use.
// Complex arrays are exposed interleaved [re, im, ...] with isComplex=true.
export interface NpyArray {
  shape: number[];
  isComplex: boolean;
  data: Float64Array | Float32Array | Uint8Array;
}

const MAGIC = [0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59];

export function parseNpy(bytes: Uint8Array): NpyArray {
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
  if (fortran === 'True') throw new Error('fortran_order arrays are not supported');
  const shape = shapeTxt.split(',').map(s => s.trim()).filter(Boolean).map(Number);
  const count = shape.reduce((a, b) => a * b, 1);

  // slice() copies -> result buffers are always 8-byte aligned
  const raw = bytes.slice(dataStart);
  switch (descr) {
    case '<f8': return { shape, isComplex: false, data: new Float64Array(raw.buffer, 0, count) };
    case '<f4': return { shape, isComplex: false, data: new Float32Array(raw.buffer, 0, count) };
    case '<c16': return { shape, isComplex: true, data: new Float64Array(raw.buffer, 0, count * 2) };
    case '|b1': return { shape, isComplex: false, data: raw.subarray(0, count) };
    case '<i8': {
      const big = new BigInt64Array(raw.buffer, 0, count);
      const out = new Float64Array(count);
      for (let i = 0; i < count; i++) out[i] = Number(big[i]);
      return { shape, isComplex: false, data: out };
    }
    case '<i4': {
      const ints = new Int32Array(raw.buffer, 0, count);
      return { shape, isComplex: false, data: Float64Array.from(ints) };
    }
    default: throw new Error(`unsupported dtype ${descr}`);
  }
}

export function serializeNpy(a: NpyArray): Uint8Array {
  const descr = a.isComplex ? '<c16' : a.data instanceof Float32Array ? '<f4'
    : a.data instanceof Uint8Array ? '|b1' : '<f8';
  const shape = a.shape.length === 1 ? `(${a.shape[0]},)` : `(${a.shape.join(', ')})`;
  let header = `{'descr': '${descr}', 'fortran_order': False, 'shape': ${shape}, }`;
  const unpadded = 10 + header.length + 1;
  header = header + ' '.repeat((64 - (unpadded % 64)) % 64) + '\n';

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
