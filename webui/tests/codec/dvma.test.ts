import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { zipSync } from 'fflate';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
import { itemChannels, setItemMeta, type DvmaItem } from '../../src/lib/model/dataset';

const bytes = new Uint8Array(readFileSync('tests/fixtures/impulse.dvma'));

/** zip a hand-built manifest (plus optional extra members) for rejection tests */
function zipManifest(manifest: unknown, extra: Record<string, Uint8Array> = {}): Uint8Array {
  return zipSync({
    'manifest.json': new TextEncoder().encode(JSON.stringify(manifest)),
    ...extra,
  });
}

test('reads the pydvma-written fixture', () => {
  const ds = readDvma(bytes);
  expect(ds.formatVersion).toBe(1);
  const kinds = ds.items.map(i => i.kind);
  expect(kinds).toContain('TimeData');
  expect(kinds).toContain('TfData');
  const td = ds.items.find(i => i.kind === 'TimeData')!;
  expect(td.meta.test_name).toBe('webui fixture');
  expect(td.meta.units).toEqual(['N', 'm/s']);
  expect(itemChannels(td)).toBe(2);
  expect(td.arrays.time_axis.shape[0]).toBe(td.arrays.time_data.shape[0]);
  const tf = ds.items.find(i => i.kind === 'TfData')!;
  expect(tf.arrays.tf_data.isComplex).toBe(true);
});

test('write -> read round trip preserves arrays and meta', () => {
  const ds = readDvma(bytes);
  const ds2 = readDvma(writeDvma(ds));
  expect(ds2.items.length).toBe(ds.items.length);
  const a = ds.items[0].arrays.time_data.data as Float64Array;
  const b = ds2.items[0].arrays.time_data.data as Float64Array;
  expect(Array.from(b.subarray(0, 16))).toEqual(Array.from(a.subarray(0, 16)));
  expect(ds2.items[0].meta.units).toEqual(ds.items[0].meta.units);
  // tagged manifest meta must survive verbatim for EVERY item
  ds.items.forEach((item, i) => {
    expect(ds2.items[i].metaRaw).toEqual(item.metaRaw);
  });
});

test('setItemMeta keeps meta and metaRaw consistent through a round trip', () => {
  const ds = readDvma(bytes);
  const td = ds.items.find(i => i.kind === 'TimeData')!;
  const origRaw = structuredClone(td.metaRaw)!;
  setItemMeta(td, 'test_name', 'renamed');
  const ds2 = readDvma(writeDvma(ds));
  const td2 = ds2.items.find(i => i.kind === 'TimeData')!;
  expect(td2.meta.test_name).toBe('renamed');
  expect(td2.metaRaw!.test_name).toBe('renamed');
  // untouched keys keep their original tagged encodings, deep-equal
  expect(td2.metaRaw!.timestamp).toEqual(origRaw.timestamp);
  expect(td2.metaRaw!.unique_id).toEqual(origRaw.unique_id);
  expect((td2.metaRaw!.timestamp as Record<string, unknown>).__datetime__).toBeTypeOf('string');
  expect((td2.metaRaw!.unique_id as Record<string, unknown>).__uuid__).toBeTypeOf('string');
});

test('rejects bytes that are not a zip', () => {
  expect(() => readDvma(new Uint8Array([1, 2, 3]))).toThrow(/dvma container/);
});

test('rejects a zip whose manifest has the wrong format', () => {
  expect(() => readDvma(zipManifest({ format: 'other', format_version: 1, items: [] })))
    .toThrow(/unexpected format other/);
});

test('rejects a newer format_version', () => {
  expect(() => readDvma(zipManifest({ format: 'dvma-dataset', format_version: 2, items: [] })))
    .toThrow(/format_version 2/);
});

test('rejects a manifest without an items array', () => {
  expect(() => readDvma(zipManifest({ format: 'dvma-dataset', format_version: 1 })))
    .toThrow(/no items array/);
});

test('rejects an unknown data kind', () => {
  const manifest = {
    format: 'dvma-dataset', format_version: 1, pydvma_version: 'x',
    items: [{ kind: 'HoloData', arrays: {}, meta: {}, settings: null }],
  };
  expect(() => readDvma(zipManifest(manifest))).toThrow(/unknown data kind "HoloData"/);
});

test('rejects a manifest referencing a missing member', () => {
  const manifest = {
    format: 'dvma-dataset', format_version: 1, pydvma_version: 'x',
    items: [{
      kind: 'TimeData',
      arrays: { time_data: 'arrays/0000_time_data.npy' },
      meta: {}, settings: null,
    }],
  };
  expect(() => readDvma(zipManifest(manifest))).toThrow(/missing member arrays\/0000_time_data\.npy/);
});

test('rejects non-finite meta on a JS-authored item (no metaRaw)', () => {
  const src = readDvma(bytes).items[0];
  const jsItem: DvmaItem = { kind: src.kind, arrays: src.arrays, meta: { gain: Infinity }, settings: null };
  expect(() => writeDvma({ formatVersion: 1, pydvmaVersion: 'x', items: [jsItem] }))
    .toThrow(/items\[0\]\.meta\.gain/);
});
