// The app's Export CSV / Export Matlab hand the document Save builds (.dvma
// bytes) to the engine's dvma_to_csv / dvma_to_mat ops, which run python's own
// writers: one writer per format for python and the app. `exportBytes` is the
// app's side of that hand-off.
import { expect, test } from 'vitest';
import { exportBytes } from '../../src/lib/export/data';

const dvma = new Uint8Array([0x50, 0x4b, 1, 2]);

test('exportBytes sends the document to the format\'s op and returns its bytes', async () => {
  const calls: [string, Record<string, unknown>][] = [];
  const enqueue = async (op: string, payload: Record<string, unknown>) => {
    calls.push([op, payload]);
    return op === 'dvma_to_csv' ? { csv: new Uint8Array([35, 32]) } : { mat: new Uint8Array([7]) };
  };
  expect(Array.from(await exportBytes(enqueue, dvma, 'csv'))).toEqual([35, 32]);
  expect(Array.from(await exportBytes(enqueue, dvma, 'mat'))).toEqual([7]);
  expect(calls.map(([op]) => op)).toEqual(['dvma_to_csv', 'dvma_to_mat']);
  expect(calls[0][1].dvma_bytes).toBe(dvma);
});

test('exportBytes accepts the Map and plain-array shapes the worker can return', async () => {
  const asMap = async () => new Map([['csv', new Uint8Array([1, 2])]]);
  expect(Array.from(await exportBytes(asMap, dvma, 'csv'))).toEqual([1, 2]);
  const asArray = async () => ({ mat: [3, 4] });
  const out = await exportBytes(asArray, dvma, 'mat');
  expect(out).toBeInstanceOf(Uint8Array);
  expect(Array.from(out)).toEqual([3, 4]);
});
