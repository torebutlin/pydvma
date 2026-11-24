/** CRC-32 (IEEE, the PNG polynomial) lookup table. */
const CRC_TABLE: Uint32Array = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

/** CRC-32 of `bytes`, as PNG chunks use it (over chunk type + data). */
function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];

/**
 * Stamp a physical resolution into a PNG: writes a `pHYs` chunk (pixels per
 * metre, unit byte 1) straight after `IHDR` and drops any `pHYs` already
 * there, so applying it twice leaves one. 600 dpi is 23622 pixels per metre
 * (600 / 0.0254, rounded). Pure bytes in and out; throws "not a PNG" when
 * the 8-byte signature or the first chunk is wrong.
 */
export function withPngDpi(png: Uint8Array, dpi: number): Uint8Array {
  if (png.length < 33 || SIGNATURE.some((b, i) => png[i] !== b)) throw new Error('not a PNG');
  const dv = new DataView(png.buffer, png.byteOffset, png.byteLength);
  const type = (o: number) => String.fromCharCode(png[o], png[o + 1], png[o + 2], png[o + 3]);
  if (type(12) !== 'IHDR') throw new Error('not a PNG (no IHDR)');

  const ppm = Math.round(dpi / 0.0254);
  const chunk = new Uint8Array(21);
  const cv = new DataView(chunk.buffer);
  cv.setUint32(0, 9);
  chunk.set([0x70, 0x48, 0x59, 0x73], 4); // 'pHYs'
  cv.setUint32(8, ppm);
  cv.setUint32(12, ppm);
  chunk[16] = 1;
  cv.setUint32(17, crc32(chunk.subarray(4, 17)));

  const parts: Uint8Array[] = [png.subarray(0, 33), chunk]; // signature + IHDR (8 + 25)
  let o = 33;
  while (o + 12 <= png.length) {
    const len = dv.getUint32(o);
    const end = o + 12 + len;
    if (end > png.length) throw new Error('not a PNG (truncated chunk)');
    if (type(o + 4) !== 'pHYs') parts.push(png.subarray(o, end));
    o = end;
  }
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let p = 0;
  for (const part of parts) { out.set(part, p); p += part.length; }
  return out;
}
