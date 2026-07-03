import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
import { itemChannels } from '../../src/lib/model/dataset';

const bytes = new Uint8Array(readFileSync('tests/fixtures/impulse.dvma'));

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
});
