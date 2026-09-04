/**
 * Round-14 follow-up (2026-09-04): the compute actions over `'all'` must only
 * consider TIME-BEARING working sets.
 *
 * A TF-only working set — an orphan `TfData` from a TF-only file, or the
 * Nonlin stage's BLA result set (one `TfData` per excitation, `nOut`
 * columns) — has no time series to recompute from. `calcTf('all')` used to
 * treat it as a measurement: with one response column it tripped the
 * single-channel guard ("Transfer function needs at least one output channel
 * besides the input — set “set” has only one channel", the lab's intermittent
 * error, raised while the real two-channel sets computed fine), and with more
 * columns `calcFft('all')` dereferenced a `time_axis` that does not exist.
 * An EXPLICIT TF-only target is refused with a clear message instead.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset } from '../../src/lib/model/dataset';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

function fakeEngine() {
  const calls: string[] = [];
  const engine = {
    status: writable('ready'),
    boot: async () => {},
    whenReady: async () => {},
    enqueue: async (op: string) => {
      calls.push(op);
      if (op === 'calc_tf' || op === 'calc_tf_averaged') {
        return { freq_axis: real([2], [0, 1]), tf_data: cplx([2, 1], [1, 0, 1, 0]), coherence: real([2, 1], [0.9, 0.8]) };
      }
      if (op === 'calc_fft') return { freq_axis: real([2], [0, 1]), freq_data: cplx([2, 2], [1, 0, 2, 0, 3, 0, 4, 0]) };
      if (op === 'calc_psd') {
        return { freq_axis: real([2], [0, 1]), psd: real([2, 2], [1, 2, 3, 4]), Cxy: cplx([2, 2, 2], new Array(16).fill(0)) };
      }
      return {};
    },
    client: {} as any,
  } as unknown as EngineStore;
  return { engine, calls };
}

/** One 2-channel measurement plus an ORPHAN 1-column TfData (no source). */
function datasetWithOrphanTf(): DvmaDataset {
  return {
    formatVersion: 2, pydvmaVersion: 'test',
    items: [
      {
        kind: 'TimeData',
        arrays: {
          time_axis: { shape: [4], isComplex: false, data: Float64Array.from([0, 0.5, 1, 1.5]) },
          time_data: { shape: [4, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6, 7, 8]) },
        },
        meta: { test_name: 'measurement', timestring: 't0', unique_id: 'src-1' },
        settings: { fs: 2 },
      },
      {
        kind: 'TfData',
        arrays: {
          freq_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 1]) },
          tf_data: { shape: [2, 1], isComplex: true, data: Float64Array.from([1, 0, 1, 0]) },
        },
        meta: { test_name: 'set', timestring: 't1', id_link: 'no-such-source' },
        settings: null,
      },
    ],
  };
}

function loaded() {
  const { engine, calls } = fakeEngine();
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const actions = createActions(engine, sel, settings);
  actions.loadDataset(datasetWithOrphanTf());
  const sets = get(sel.sets);
  expect(sets.map((s) => [s.name, s.nChannels])).toEqual([['measurement', 2], ['set', 1]]);
  const orphanId = sets[1].id;
  const srcId = sets[0].id;
  return { actions, calls, orphanId, srcId };
}

test("calcTf('all') computes the measurement and ignores the TF-only set", async () => {
  const { actions, calls, srcId } = loaded();
  await actions.calcTf('all');
  expect(calls).toEqual(['calc_tf']);
  expect(get(actions.computeErrors).tf ?? '').toBe('');
  expect(get(actions.derived)[srcId]?.tf).toBeDefined();
});

test("calcFft('all') and calcPsd('all') skip the TF-only set instead of crashing", async () => {
  const { actions, calls } = loaded();
  await actions.calcFft('all');
  await actions.calcPsd('all');
  expect(calls).toEqual(['calc_fft', 'calc_psd']);
  expect(get(actions.computeErrors).fft ?? '').toBe('');
  expect(get(actions.computeErrors).psd ?? '').toBe('');
});

test('an explicit TF-only target is refused with a clear message', async () => {
  const { actions, calls, orphanId } = loaded();
  await actions.calcTf(orphanId);
  expect(calls).toEqual([]);
  expect(get(actions.computeErrors).tf).toMatch(/time signal/);
  expect(get(actions.computeErrors).tf).toMatch(/set/);
});

test('a genuinely single-channel MEASUREMENT still gets the output-channel message', async () => {
  const { engine, calls } = fakeEngine();
  const sel = createSelection();
  const actions = createActions(engine, sel, createAnalysisSettings(sel));
  actions.loadDataset({
    formatVersion: 2, pydvmaVersion: 'test',
    items: [{
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 0.5]) },
        time_data: { shape: [2, 1], isComplex: false, data: Float64Array.from([1, 2]) },
      },
      meta: { test_name: 'mono', timestring: 't0' },
      settings: { fs: 2 },
    }],
  });
  await actions.calcTf('all');
  expect(calls).toEqual([]);
  expect(get(actions.computeErrors).tf).toMatch(/mono.*only one channel/);
});
