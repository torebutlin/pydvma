import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { zipSync } from 'fflate';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
import { itemChannels, setItemMeta, type DvmaItem, type DvmaItemUi } from '../../src/lib/model/dataset';

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

test('rejects non-finite meta injected via setItemMeta on a python-read item', () => {
  const ds = readDvma(bytes);
  setItemMeta(ds.items[0], 'gain', NaN);   // lands in metaRaw, which writeDvma serializes
  expect(() => writeDvma(ds)).toThrow(/gain/);
});

// ---- Plan 2 persistence: ui field round-trip ----

test('write -> read round trip preserves ui.channel_labels', () => {
  const ds = readDvma(bytes);
  const td = ds.items.find(i => i.kind === 'TimeData')!;
  td.ui = { channel_labels: { '0': 'hammer', '1': 'accel' } };
  const ds2 = readDvma(writeDvma(ds));
  const td2 = ds2.items.find(i => i.kind === 'TimeData')!;
  expect(td2.ui).toBeDefined();
  expect(td2.ui!.channel_labels).toEqual({ '0': 'hammer', '1': 'accel' });
});

test('write -> read round trip preserves ui.analysis settings', () => {
  const ds = readDvma(bytes);
  const td = ds.items.find(i => i.kind === 'TimeData')!;
  td.ui = {
    analysis: {
      freq: { window: 'flattop', mode: 'psd', nFrames: 20 },
      tf: { chIn: 1, window: 'hann', averaging: 'across', nFrames: 5 },
      sono: { nFft: 1024, dynRangeDb: 80 },
    },
  };
  const ds2 = readDvma(writeDvma(ds));
  const td2 = ds2.items.find(i => i.kind === 'TimeData')!;
  expect(td2.ui!.analysis!.freq).toEqual({ window: 'flattop', mode: 'psd', nFrames: 20 });
  expect(td2.ui!.analysis!.tf).toEqual({ chIn: 1, window: 'hann', averaging: 'across', nFrames: 5 });
  expect(td2.ui!.analysis!.sono).toEqual({ nFft: 1024, dynRangeDb: 80 });
});

test('ui field absent on items with no ui state (keeps files clean)', () => {
  const ds = readDvma(bytes);
  // No ui set on any item → the manifest entry should have no ui key.
  const ds2 = readDvma(writeDvma(ds));
  ds2.items.forEach(item => {
    expect(item.ui).toBeUndefined();
  });
});

test('readDvma ignores non-object ui gracefully', () => {
  const ds = readDvma(bytes);
  // Manually write a dataset whose manifest ui is a string (bad data).
  const src = writeDvma(ds);
  const ds2 = readDvma(src);
  // Simulate a manifest with ui: "garbage" by re-zipping.
  const manifest = {
    format: 'dvma-dataset', format_version: 1, pydvma_version: '1.5.0',
    items: [{ kind: 'TimeData', arrays: {}, meta: {}, settings: null, ui: 'garbage' }],
  };
  const parsed = readDvma(zipManifest(manifest));
  // Non-object ui should be silently ignored (undefined).
  expect(parsed.items[0].ui).toBeUndefined();
});

// ---- Modal-fit persistence: ModalData item round-trip (round-5 item 13) ----

test('a JS-authored ModalData item write -> read round-trips M + meta', () => {
  const ds = readDvma(bytes);
  // Append a ModalData item as `syncModal` would build it (matches pydvma's
  // container.py ModalData schema: array M + meta units/test_name/timestamp/
  // timestring/id_link/channels, plus webui-only keys pydvma ignores).
  const iso = '2026-07-08T00:00:00.000Z';
  const M = { shape: [2, 6], isComplex: false, data: Float64Array.from([80, 0.02, 1, 0, 0, 0, 220, 0.01, 0.6, 0, 0, 0]) };
  const meta = {
    units: ['m/s²', 'N'], test_name: 'modal_set_0', timestamp: iso, timestring: iso,
    id_link: 'UID1', channels: 1, measurement_type: 'acc', source_ch_in: 0, source_n_channels: 2,
  };
  const modalItem: DvmaItem = {
    kind: 'ModalData', arrays: { M }, meta,
    metaRaw: { ...meta, timestamp: { __datetime__: iso } }, settings: null,
  };
  ds.items.push(modalItem);

  const ds2 = readDvma(writeDvma(ds));
  const md = ds2.items.find(i => i.kind === 'ModalData')!;
  expect(md).toBeTruthy();
  expect(md.arrays.M.shape).toEqual([2, 6]);
  expect(Array.from(md.arrays.M.data as Float64Array))
    .toEqual([80, 0.02, 1, 0, 0, 0, 220, 0.01, 0.6, 0, 0, 0]);
  expect(md.meta.id_link).toBe('UID1');
  expect(md.meta.channels).toBe(1);
  expect(md.meta.measurement_type).toBe('acc');       // webui-only key preserved in JS
  expect(md.meta.source_ch_in).toBe(0);
  expect(md.meta.source_n_channels).toBe(2);
  // timestamp decodes back to the ISO string (tagged __datetime__ in metaRaw).
  expect(md.meta.timestamp).toBe(iso);
  expect((md.metaRaw!.timestamp as Record<string, unknown>).__datetime__).toBe(iso);
});

test('ui with both labels and analysis round-trips together', () => {
  const ds = readDvma(bytes);
  const td = ds.items.find(i => i.kind === 'TimeData')!;
  td.ui = {
    channel_labels: { '1': 'response' },
    analysis: { freq: { window: 'blackman', mode: 'csd', nFrames: 15 } },
  };
  const ds2 = readDvma(writeDvma(ds));
  const td2 = ds2.items.find(i => i.kind === 'TimeData')!;
  expect(td2.ui!.channel_labels).toEqual({ '1': 'response' });
  expect(td2.ui!.analysis!.freq).toEqual({ window: 'blackman', mode: 'csd', nFrames: 15 });
  // tf and sono should be absent (not written).
  expect(td2.ui!.analysis!.tf).toBeUndefined();
  expect(td2.ui!.analysis!.sono).toBeUndefined();
});
