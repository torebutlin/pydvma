import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { zipSync } from 'fflate';
import { LARGE_MEMBER_BYTES, readDvma, writeDvma } from '../../src/lib/codec/dvma';
import { serializeNpy } from '../../src/lib/codec/npy';
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

// ---- Schoukens BLA persistence: bla_sigma_nl/bla_sigma_n arrays + bla meta
// (Task 6) — the codec has no per-kind field whitelist, so these should
// round-trip through the generic arrays/meta loops with no dvma.ts changes.

test('a TfData item with BLA sigma arrays + bla meta round-trips intact', () => {
  const ds = readDvma(bytes);
  const freq_axis = { shape: [3], isComplex: false, data: Float64Array.from([10, 20, 30]) };
  const tf_data = {
    shape: [3, 1], isComplex: true,
    data: Float64Array.from([1, 0.1, 2, 0.2, 3, 0.3]),   // interleaved re/im
  };
  const bla_sigma_nl = { shape: [3, 1], isComplex: false, data: Float64Array.from([0.01, 0.02, 0.03]) };
  const bla_sigma_n = { shape: [3, 1], isComplex: false, data: Float64Array.from([0.001, 0.002, 0.003]) };
  const bla = {
    multisine: { n_samples: 256, k1: 8, k2: 100, p_periods: 2, t_periods: 2, seed: 42, amp_rms: 0.1, n_exc: 2, M: 2 },
    x_mode: 'measured', x_channels: [0, 1], resp_channels: [2],
    fs: 8192.0, excited_bins: [8, 9, 10], q: 0,
  };
  const blaItem: DvmaItem = {
    kind: 'TfData',
    arrays: { freq_axis, tf_data, bla_sigma_nl, bla_sigma_n },
    meta: { units: ['g/N'], test_name: 'bla q0', bla },
    settings: null,
  };
  ds.items.push(blaItem);

  const ds2 = readDvma(writeDvma(ds));
  const found = ds2.items.filter(i => i.kind === 'TfData' && i.meta.test_name === 'bla q0');
  expect(found.length).toBe(1);
  const tf = found[0];
  expect(tf.arrays.bla_sigma_nl.shape).toEqual([3, 1]);
  expect(Array.from(tf.arrays.bla_sigma_nl.data as Float64Array)).toEqual([0.01, 0.02, 0.03]);
  expect(Array.from(tf.arrays.bla_sigma_n.data as Float64Array)).toEqual([0.001, 0.002, 0.003]);
  expect(tf.arrays.tf_data.isComplex).toBe(true);
  expect(Array.from(tf.arrays.tf_data.data as Float64Array)).toEqual([1, 0.1, 2, 0.2, 3, 0.3]);
  expect(tf.meta.bla).toEqual(bla);
});

test('an ordinary TfData item with no BLA fields is unaffected by the round trip', () => {
  const ds = readDvma(bytes);
  const tf = ds.items.find(i => i.kind === 'TfData')!;
  expect(tf.arrays.bla_sigma_nl).toBeUndefined();
  expect(tf.arrays.bla_sigma_n).toBeUndefined();
  expect(tf.meta.bla).toBeUndefined();
  const ds2 = readDvma(writeDvma(ds));
  const tf2 = ds2.items.find(i => i.kind === 'TfData')!;
  expect(tf2.arrays.bla_sigma_nl).toBeUndefined();
  expect(tf2.arrays.bla_sigma_n).toBeUndefined();
  expect(tf2.meta.bla).toBeUndefined();
  // its ordinary fields still round-trip unchanged
  expect(tf2.arrays.tf_data.shape).toEqual(tf.arrays.tf_data.shape);
  expect(Array.from(tf2.arrays.tf_data.data as Float64Array))
    .toEqual(Array.from(tf.arrays.tf_data.data as Float64Array));
  expect(tf2.meta.test_name).toBe(tf.meta.test_name);
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

test('channel_calibration meta (provenance, with null entries) survives write/read', () => {
  const ds = readDvma(bytes);
  const td = ds.items.find(i => i.kind === 'TimeData')!;
  const cc = [{
    method: 'reference_tone', date: '2026-11-06T10:00:00.000Z', sensitivity: 0.05, unit: 'Pa',
    reference: { level: 94, level_unit: 'dB SPL', freq: 1000 }, gain_db: null, input_mode: null,
    pad: null, device: null, note: '', carried: false,
  }, null];
  setItemMeta(td, 'channel_calibration', cc);
  const td2 = readDvma(writeDvma(ds)).items.find(i => i.kind === 'TimeData')!;
  expect(td2.metaRaw!.channel_calibration).toEqual(cc);
  expect(td2.meta.channel_calibration).toEqual(cc);
});

/** Compression method of every member, read from the zip's central directory. */
function zipMethods(zip: Uint8Array): Record<string, number> {
  const view = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
  let eocd = zip.length - 22;                       // no archive comment here
  while (eocd >= 0 && view.getUint32(eocd, true) !== 0x06054b50) eocd--;
  const count = view.getUint16(eocd + 10, true);
  let p = view.getUint32(eocd + 16, true);
  const out: Record<string, number> = {};
  for (let i = 0; i < count; i++) {
    expect(view.getUint32(p, true)).toBe(0x02014b50);
    const method = view.getUint16(p + 10, true);
    const nameLen = view.getUint16(p + 28, true);
    const extraLen = view.getUint16(p + 30, true);
    const commentLen = view.getUint16(p + 32, true);
    out[new TextDecoder().decode(zip.subarray(p + 46, p + 46 + nameLen))] = method;
    p += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

test('a member over 16 MiB is written stored (level 0) and round-trips; small ones stay deflated', () => {
  // Long recordings (Task 11): deflating a several-hundred-MB float64 member
  // gains a few percent on real noise and freezes the main thread for
  // seconds, so members over 16 MiB go in uncompressed. Both readers
  // (fflate unzipSync, python's zipfile) read either method.
  const ds = readDvma(bytes);
  const n = (20 * 1024 * 1024) / 8;                 // 20 MiB of float64
  const data = new Float64Array(n);
  for (let i = 0; i < n; i++) data[i] = Math.sin(i * 0.001) + i * 1e-9;
  const axis = new Float64Array(n);
  for (let i = 0; i < n; i++) axis[i] = i / 48000;
  const big: DvmaItem = {
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [n], isComplex: false, data: axis },
      time_data: { shape: [n, 1], isComplex: false, data },
    },
    meta: { test_name: 'long' }, settings: { fs: 48000, channels: 1 },
  };
  ds.items.push(big);
  const out = writeDvma(ds);
  const methods = zipMethods(out);
  const idx = String(ds.items.length - 1).padStart(4, '0');
  expect(methods[`arrays/${idx}_time_data.npy`]).toBe(0);    // stored
  expect(methods[`arrays/${idx}_time_axis.npy`]).toBe(0);
  expect(methods['manifest.json']).toBe(8);                   // deflated
  expect(methods['arrays/0000_time_data.npy']).toBe(8);       // the fixture's small arrays
  const back = readDvma(out).items[ds.items.length - 1];
  expect(back.arrays.time_data.shape).toEqual([n, 1]);
  const got = back.arrays.time_data.data as Float64Array;
  let same = got.length === n;
  for (let i = 0; same && i < n; i++) same = got[i] === data[i];
  expect(same).toBe(true);
  expect((back.arrays.time_axis.data as Float64Array)[n - 1]).toBe(axis[n - 1]);
});

test('a container whose large member is deflated (older writers) still reads', () => {
  // Every .dvma written before Task 11 deflates every member, however big.
  const n = (17 * 1024 * 1024) / 8;
  const data = new Float64Array(n).map((_, i) => i % 7);
  const manifest = {
    format: 'dvma-dataset', format_version: 1, pydvma_version: '2.8.4', storage: 'npy',
    items: [{ kind: 'TimeData', arrays: { time_axis: 'arrays/0000_time_axis.npy', time_data: 'arrays/0000_time_data.npy' }, meta: {}, settings: null }],
  };
  const zip = zipSync({
    'arrays/0000_time_axis.npy': serializeNpy({ shape: [n], isComplex: false, data }),
    'arrays/0000_time_data.npy': serializeNpy({ shape: [n, 1], isComplex: false, data }),
    'manifest.json': new TextEncoder().encode(JSON.stringify(manifest)),
  }, { level: 6 });
  expect(zipMethods(zip)['arrays/0000_time_data.npy']).toBe(8);
  const td = readDvma(zip).items[0];
  expect((td.arrays.time_data.data as Float64Array)[n - 1]).toBe((n - 1) % 7);
});

test('the stored threshold is on the member size, as in python', () => {
  // A 1-D float64 member exactly LARGE_MEMBER_BYTES long (npy header
  // included) stays deflated; one element more and it is stored.
  expect(LARGE_MEMBER_BYTES).toBe(16 * 1024 * 1024);
  const probe = 2097136;
  const header = serializeNpy({ shape: [probe], isComplex: false, data: new Float64Array(probe) }).length - probe * 8;
  const nAt = (LARGE_MEMBER_BYTES - header) / 8;
  expect(Number.isInteger(nAt)).toBe(true);
  for (const [n, method] of [[nAt, 8], [nAt + 1, 0]] as const) {
    const ds = { formatVersion: 1, pydvmaVersion: '', items: [{
      kind: 'MetaData' as const, meta: {}, settings: null,
      arrays: { x: { shape: [n], isComplex: false, data: new Float64Array(n) } },
    }] };
    expect(zipMethods(writeDvma(ds))['arrays/0000_x.npy']).toBe(method);
  }
});
