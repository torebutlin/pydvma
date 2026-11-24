import { expect, it } from 'vitest';
import { withPngDpi } from '../../src/lib/export/pngDpi';

const png = Uint8Array.from(
  atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='),
  (c) => c.charCodeAt(0),
);

it('inserts a 600 dpi pHYs chunk right after IHDR', () => {
  const out = withPngDpi(png, 600);
  const dv = new DataView(out.buffer, out.byteOffset);
  expect(dv.getUint32(33)).toBe(9);
  expect(new TextDecoder().decode(out.subarray(37, 41))).toBe('pHYs');
  expect(dv.getUint32(41)).toBe(23622); expect(dv.getUint32(45)).toBe(23622); expect(out[49]).toBe(1);
  expect(dv.getUint32(50)).toBe(0x14944341); // CRC-32 of 'pHYs' + data
  expect(out.length).toBe(png.length + 21);
});
it('replaces an existing pHYs instead of adding a second', () => {
  const twice = withPngDpi(withPngDpi(png, 300), 600);
  expect(new TextDecoder('latin1').decode(twice).split('pHYs')).toHaveLength(2);
  expect(new DataView(twice.buffer, twice.byteOffset).getUint32(41)).toBe(23622);
});
it('refuses bytes that are not a PNG', () => {
  expect(() => withPngDpi(new Uint8Array([1, 2, 3]), 600)).toThrow(/not a PNG/);
});
