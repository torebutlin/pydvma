import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

/** A 1-set, 2-channel TimeData-only dataset. */
function makeDataset(): DvmaDataset {
  const items: DvmaItem[] = [{
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: 'set_0', timestring: 't0' },
    settings: { fs: 2 },
  }];
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
}

interface Recorded { op: string; payload: Record<string, unknown>; }
function fakeEngine(responder: (op: string, payload: Record<string, unknown>) => unknown): { engine: EngineStore; calls: Recorded[] } {
  const calls: Recorded[] = [];
  const engine = {
    status: writable('ready'), boot: async () => {}, whenReady: async () => {},
    enqueue: (op: string, payload: Record<string, unknown> = {}) => {
      calls.push({ op, payload });
      return Promise.resolve(responder(op, payload));
    },
    client: {} as unknown,
  } as unknown as EngineStore;
  return { engine, calls };
}

const tfResult = () => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, 1], [2, 0, 2, 0]),
  coherence: real([2, 1], [0.9, 0.8]),
});
const fitResult = () => ({
  M: real([1, 6], [80, 0.02, 1, 0, 0, 0]),
  fn: real([1], [80]), zn: real([1], [0.02]),
  an: real([1, 1], [1]), pn: real([1, 1], [0]),
  message: 'fn=80.00 (Hz)',
  recon_freq_axis: real([2], [60, 110]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
  global_freq_axis: real([2], [0, 1]), global_tf_data: cplx([2, 1], [0.5, 0, 0.5, 0]),
});

function harness(responder: (op: string, payload: Record<string, unknown>) => unknown) {
  const { engine, calls } = fakeEngine(responder);
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const modal = createModalStore();
  const actions = createActions(engine, sel, settings, modal);
  return { actions, modal, sel, calls };
}

test('calcFit sends calc_fit with the TF slice + freq range and updates the modal store', async () => {
  const { actions, modal, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);

  const fit = calls.find((c) => c.op === 'calc_fit');
  expect(fit).toBeTruthy();
  expect(fit!.payload.freq_range).toEqual([60, 110]);
  expect(fit!.payload.measurement_type).toBe('acc');
  expect(fit!.payload.action).toBe('fit');
  expect(fit!.payload.n_modes).toBe(1);
  expect(fit!.payload.n_tf).toBe(1);          // one output column
  expect(fit!.payload.ch_in).toBe(0);
  expect(fit!.payload.n_channels).toBe(2);
  // First fit re-sends no prior matrix — the key is OMITTED (not sent as JS
  // null, which pyodide would surface as a falsy JsNull, not Python None).
  expect('M' in fit!.payload).toBe(false);
  // interleaved complex tf_data: [re,im,…] of the |H|=2 column → length 2·Nf.
  expect((fit!.payload.tf_data as Float64Array).length).toBe(4);

  const s = get(modal);
  expect(s.modes.map((m) => m.fn)).toEqual([80]);
  expect(s.local?.axis.length).toBe(2);
});

test('a second fit for the same set re-sends the accumulated matrix', async () => {
  const { actions, modal, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  await actions.calcFit('all', [190, 250], 'acc', 'fit', 1);
  const fits = calls.filter((c) => c.op === 'calc_fit');
  expect(fits).toHaveLength(2);
  expect('M' in fits[1].payload).toBe(true);   // accumulate against the stored model
  expect((fits[1].payload.M as { shape: number[] }).shape).toEqual([1, 6]);
  // Modal store still targets the same set → matrix carried, not reset.
  expect(get(modal).setId).not.toBeNull();
});

test('reject action forwards action=reject', async () => {
  const { actions, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'reject');
  const fit = calls.find((c) => c.op === 'calc_fit');
  expect(fit!.payload.action).toBe('reject');
});

test('delete_one forwards action=delete_one with the mode index', async () => {
  const { actions, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);   // one mode
  await actions.calcFit('all', null, 'acc', 'delete_one', 1, 0);
  const del = calls.filter((c) => c.op === 'calc_fit').at(-1)!;
  expect(del.payload.action).toBe('delete_one');
  expect(del.payload.index).toBe(0);
});

test('recon (mute recompute) sends the muted indices', async () => {
  const { actions, modal, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);   // one mode, index 0
  modal.toggleMute(0);
  await actions.calcFit('all', null, 'acc', 'recon');
  const recon = calls.filter((c) => c.op === 'calc_fit').at(-1)!;
  expect(recon.payload.action).toBe('recon');
  expect(recon.payload.mute).toEqual([0]);
});

test('refine keeps the improved result and leaves an undo slot', async () => {
  // fit returns one mode; refine returns a refined mode + converged:true.
  const refined = () => ({
    ...fitResult(), fn: real([1], [82]), zn: real([1], [0.018]),
    M: real([1, 6], [82, 0.018, 1, 0, 0, 0]),
    converged: true, cost_before: 1, cost_after: 0.2,
  });
  const { actions, modal } = harness((op, p) =>
    op === 'calc_tf' ? tfResult() : op === 'calc_fit'
      ? (p.action === 'refine' ? refined() : fitResult()) : {});
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  await actions.calcFit('all', null, 'acc', 'refine');
  const s = get(modal);
  expect(s.modes.map((m) => m.fn)).toEqual([82]);   // refined value kept
  expect(s.undo).not.toBeNull();                     // manual undo still available
});

test('refine AUTO-REVERTS to the pre-refine model when the engine reports not converged', async () => {
  // refine returns a WORSE model with converged:false — the store must revert.
  const worse = () => ({
    ...fitResult(), fn: real([1], [999]), zn: real([1], [0.5]),
    M: real([1, 6], [999, 0.5, 1, 0, 0, 0]),
    converged: false, cost_before: 1, cost_after: 5,
  });
  const { actions, modal } = harness((op, p) =>
    op === 'calc_tf' ? tfResult() : op === 'calc_fit'
      ? (p.action === 'refine' ? worse() : fitResult()) : {});
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);   // mode at 80
  await actions.calcFit('all', null, 'acc', 'refine');         // engine says worse
  const s = get(modal);
  expect(s.modes.map((m) => m.fn)).toEqual([80]);   // reverted to the fit, not 999
  expect(s.undo).toBeNull();                         // revert consumed the slot
});

test('calcFit no-ops (no engine call) before any TF exists', async () => {
  const { actions, calls } = harness(() => ({}));
  actions.loadDataset(makeDataset());
  await actions.calcFit('all', [60, 110]);
  expect(calls.some((c) => c.op === 'calc_fit')).toBe(false);
});

/** An ORPHAN TF dataset: a TfData with NO linked TimeData (3 identity columns).
 *  The loader restores it with chIn = null (columns ARE the lines). */
function orphanDataset(): DvmaDataset {
  return {
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [{
      kind: 'TfData',
      arrays: {
        freq_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 1]) },
        // 3 columns, interleaved [re,im,…] row-major (2 rows × 3 cols).
        tf_data: { shape: [2, 3], isComplex: true, data: Float64Array.from([1, 0, 0.8, 0, 1.3, 0, 1, 0, 0.8, 0, 1.3, 0]) },
      },
      meta: { test_name: 'orphan' }, settings: null,
    }],
  };
}
const fitResult3 = () => ({
  M: real([1, 14], [80, 0.02, 1, 0.8, 1.3, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
  fn: real([1], [80]), zn: real([1], [0.02]),
  an: real([1, 3], [1, 0.8, 1.3]), pn: real([1, 3], [0, 0, 0]),
  message: 'fn=80.00 (Hz)',
  recon_freq_axis: real([2], [60, 110]), recon_tf_data: cplx([2, 3], [1, 0, 0.8, 0, 1.3, 0, 1, 0, 0.8, 0, 1.3, 0]),
  global_freq_axis: real([2], [0, 1]), global_tf_data: cplx([2, 3], [1, 0, 0.8, 0, 1.3, 0, 1, 0, 0.8, 0, 1.3, 0]),
});

test('an ORPHAN TF fit OMITS ch_in from the payload (round-6 bug 1)', async () => {
  const { actions, modal, calls } = harness((op) => (op === 'calc_fit' ? fitResult3() : {}));
  actions.loadDataset(orphanDataset());
  await actions.calcFit('all', [0, 1], 'acc', 'fit', 1);
  const fit = calls.find((c) => c.op === 'calc_fit');
  expect(fit).toBeTruthy();
  // The engine has NO ch_in default that raised before the fix; the JS side
  // must OMIT the key for an orphan so Python's ch_in=None default applies.
  expect('ch_in' in fit!.payload).toBe(false);
  expect(fit!.payload.n_tf).toBe(3);          // three orphan columns are the lines
  expect(fit!.payload.n_channels).toBe(3);    // identity geometry (nChannels === Nout)
  // The store keeps chIn null so the recon overlay uses the identity remap.
  expect(get(modal).chIn).toBeNull();
  expect(get(modal).modes.map((m) => m.fn)).toEqual([80]);
});

test('calcDamping returns decoded fn/Qn', async () => {
  const { actions, calls } = harness((op) => (op === 'calc_damping' ? { fn: real([2], [80, 220]), Qn: real([2], [25, 33]) } : {}));
  actions.loadDataset(makeDataset());
  const { fn, Qn } = await actions.calcDamping('all', 1, 512);
  expect(Array.from(fn)).toEqual([80, 220]);
  expect(Array.from(Qn)).toEqual([25, 33]);
  const call = calls.find((c) => c.op === 'calc_damping');
  expect(call!.payload.ch).toBe(1);
  expect(call!.payload.nperseg).toBe(512);
});

test('exportArrays returns raw per-set columns (real for time, complex for tf)', async () => {
  const { actions } = harness((op) => (op === 'calc_tf' ? tfResult() : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');

  const time = actions.exportArrays('time');
  expect(time).toHaveLength(1);
  expect(time[0].columns).toHaveLength(2);                  // 2 channels
  expect(Array.from(time[0].columns[0] as Float64Array)).toEqual([1, 3, 5]);   // ch0 column

  const tf = actions.exportArrays('tf');
  expect(tf).toHaveLength(1);
  const col0 = (tf[0].columns as { re: Float64Array; im: Float64Array }[])[0];
  expect(Array.from(col0.re)).toEqual([2, 2]);             // |H| real parts
});

test('exportMat builds a payload of the computed kinds and returns the bytes', async () => {
  const bytes = new Uint8Array([1, 2, 3, 4]);
  const { actions, calls } = harness((op) => (op === 'calc_tf' ? tfResult() : op === 'export_mat' ? { mat: bytes } : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');

  const out = await actions.exportMat();
  expect(out).toEqual(bytes);
  const call = calls.find((c) => c.op === 'export_mat');
  expect((call!.payload.time_sets as unknown[]).length).toBe(1);   // time seeded
  expect((call!.payload.tf_sets as unknown[]).length).toBe(1);     // tf computed
  expect((call!.payload.freq_sets as unknown[]).length).toBe(0);   // no FFT
});

// ---- Round-7f fit self-awareness flags: phase-significance after a fit,
// divergence after a refine (both surfaced as toasts; JW-logger heritage —
// the original printed every fitted mode's phase). ----

function toastRecorder() {
  const pushed: { message: string; level?: string }[] = [];
  const toasts = {
    push: (message: string, opts?: { level?: string }) => {
      pushed.push({ message, level: opts?.level });
      return pushed.length;
    },
    dismiss: () => {},
  } as unknown as import('../../src/lib/stores/toast').Toasts;
  return { toasts, pushed };
}

function harnessWithToasts(responder: (op: string, payload: Record<string, unknown>) => unknown) {
  const { engine, calls } = fakeEngine(responder);
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const modal = createModalStore();
  const { toasts, pushed } = toastRecorder();
  const actions = createActions(engine, sel, settings, modal, toasts);
  return { actions, modal, sel, calls, pushed };
}

/** fitResult with a chosen packed-matrix pn (radians) on the single mode. */
const fitResultWithPhase = (pn: number, fn = 80) => ({
  ...fitResult(),
  M: real([1, 6], [fn, 0.02, 1, pn, 0, 0]),
  fn: real([1], [fn]), zn: real([1], [0.02]),
});

test('a fit whose modal phase lands far from 0/180° warns about the TF type', async () => {
  const { actions, modal, pushed } = harnessWithToasts((op) =>
    (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResultWithPhase(Math.PI / 2) : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  expect(get(modal).modes[0].phaseDevDeg).toBeCloseTo(90, 5);
  expect(pushed.some((t) => /phase.*TF type/i.test(t.message))).toBe(true);
});

test('a near-real fitted phase raises no TF-type warning', async () => {
  const { actions, modal, pushed } = harnessWithToasts((op) =>
    (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResultWithPhase(0.1) : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  expect(get(modal).modes[0].phaseDevDeg).toBeCloseTo(5.73, 1);
  expect(pushed.some((t) => /TF type/i.test(t.message))).toBe(false);
});

test('a phase near 180° counts as REAL (no warning) — sign flips are fine', async () => {
  const { actions, modal, pushed } = harnessWithToasts((op) =>
    (op === 'calc_tf' ? tfResult() : op === 'calc_fit' ? fitResultWithPhase(Math.PI - 0.05) : {}));
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  expect(get(modal).modes[0].phaseDevDeg).toBeLessThan(3);
  expect(pushed.some((t) => /TF type/i.test(t.message))).toBe(false);
});

test('a refine that drags a mode far from its peak warns (with the residual toast intact)', async () => {
  let refined = false;
  const { actions, pushed } = harnessWithToasts((op, payload) => {
    if (op === 'calc_tf') return tfResult();
    if (op === 'calc_fit' && payload.action === 'refine') {
      refined = true;
      return { ...fitResultWithPhase(0, 140), converged: true, cost_before: 10, cost_after: 5 };
    }
    if (op === 'calc_fit') return fitResultWithPhase(0, 80);
    return {};
  });
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);   // fn = 80
  await actions.calcFit('all', null, 'acc', 'refine');        // fn -> 140
  expect(refined).toBe(true);
  expect(pushed.some((t) => /moved 1 mode.*80\.0.*140\.0/i.test(t.message))).toBe(true);
});

test('a refine with a small frequency drift stays quiet', async () => {
  const { actions, pushed } = harnessWithToasts((op, payload) => {
    if (op === 'calc_tf') return tfResult();
    if (op === 'calc_fit' && payload.action === 'refine') {
      return { ...fitResultWithPhase(0, 81), converged: true, cost_before: 10, cost_after: 5 };
    }
    if (op === 'calc_fit') return fitResultWithPhase(0, 80);
    return {};
  });
  actions.loadDataset(makeDataset());
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  await actions.calcFit('all', null, 'acc', 'refine');
  expect(pushed.some((t) => /moved/.test(t.message))).toBe(false);
  expect(pushed.some((t) => /residual down/.test(t.message))).toBe(true);
});

// ---- Round-7h: the fit uses the lines left VISIBLE — the legend/tray
// tri-state is the fit's line selector (multi-instrument sets fit one line
// at a time by hiding/soloing). ----

/** A 1-set, 3-channel TimeData dataset (TF → 2 output columns, chIn 0). */
function makeDataset3ch(): DvmaDataset {
  const items: DvmaItem[] = [{
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 3], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6, 7, 8, 9]) },
    },
    meta: { test_name: 'set_0', timestring: 't0' },
    settings: { fs: 2 },
  }];
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
}

const tfResult2col = () => ({
  freq_axis: real([2], [0, 1]),
  tf_data: cplx([2, 2], [1, 0, 2, 0, 1, 0, 2, 0]),
  coherence: real([2, 2], [0.9, 0.9, 0.8, 0.8]),
});

test('hiding a line excludes its TF column from the fit (chans recorded)', async () => {
  const { actions, modal, sel, calls } = harness((op) =>
    (op === 'calc_tf' ? tfResult2col() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset3ch());
  const id = get(sel.sets)[0].id;
  await actions.calcTf('all');                    // chIn 0 → columns = ch 1, ch 2
  sel.cycleLine(id, 1); sel.cycleLine(id, 1);     // channel 1 → off
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  const fit = calls.find((c) => c.op === 'calc_fit')!;
  expect(fit.payload.n_tf).toBe(1);
  // 2 freq rows × 1 column × [re,im]
  expect((fit.payload.tf_data as Float64Array).length).toBe(4);
  // The remaining column is channel 2's — recorded on the fit target.
  expect(get(modal).targets[0].chans).toEqual([2]);
});

test('a visibility change starts a FRESH model on the next fit (no stale M)', async () => {
  const { actions, sel, calls } = harness((op) =>
    (op === 'calc_tf' ? tfResult2col() : op === 'calc_fit' ? fitResult() : {}));
  actions.loadDataset(makeDataset3ch());
  const id = get(sel.sets)[0].id;
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);   // both lines
  sel.cycleLine(id, 1); sel.cycleLine(id, 1);                 // ch 1 → off
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);   // subset fit
  const fits = calls.filter((c) => c.op === 'calc_fit');
  expect(fits).toHaveLength(2);
  // Mixed column geometries cannot merge: the second fit starts fresh.
  expect('M' in fits[1].payload).toBe(false);
});

test('every line hidden → no engine call, explanatory toast', async () => {
  const { actions, sel, calls, pushed } = harnessWithToasts((op) =>
    (op === 'calc_tf' ? tfResult2col() : {}));
  actions.loadDataset(makeDataset3ch());
  const id = get(sel.sets)[0].id;
  await actions.calcTf('all');
  for (const ch of [1, 2]) { sel.cycleLine(id, ch); sel.cycleLine(id, ch); }
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  expect(calls.some((c) => c.op === 'calc_fit')).toBe(false);
  expect(pushed.some((t) => /every TF line is hidden/i.test(t.message))).toBe(true);
});

test('fitLineSummary counts visible vs total lines for the Fit-card hint', async () => {
  const { actions, sel } = harness((op) => (op === 'calc_tf' ? tfResult2col() : {}));
  actions.loadDataset(makeDataset3ch());
  const id = get(sel.sets)[0].id;
  await actions.calcTf('all');
  expect(actions.fitLineSummary('all')).toEqual({ fitted: 2, total: 2 });
  sel.cycleLine(id, 2); sel.cycleLine(id, 2);     // channel 2 → off
  expect(actions.fitLineSummary('all')).toEqual({ fitted: 1, total: 2 });
});
