/**
 * Round-11 P5 — the axis-auto notifier.
 *
 * Tore's report: "when processing or adding data or changing view the axes
 * weren't always auto-ed when I'd expect… when data is added to a view then
 * the view (at least the y-range) should be auto-ed." The actions layer is
 * what knows WHEN a view's contents changed; these tests pin exactly which
 * operations announce it, with which view and which `viewWasEmpty` flag.
 *
 * The distinction that carries the "bit of care" in the feedback: a FIRST
 * result for a set is new lines (re-fit), a RECOMPUTE of one that already
 * exists is not (the user is looking at a window they chose).
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions, type ViewNotifier } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';
import type { ViewId } from '../../src/lib/stores/viewstate';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

const fftResult = () => ({
  freq_axis: real([2], [0, 1]), freq_data: cplx([2, 2], [1, 0, 1, 0, 1, 0, 1, 0]),
});
const psdResult = () => ({
  freq_axis: real([2], [0, 1]), psd: real([2, 2], [1, 2, 3, 4]), Cxy: real([2, 2], [1, 1, 1, 1]),
});
const tfResult = () => ({
  freq_axis: real([2], [0, 1]), tf_data: cplx([2, 1], [1, 0, 1, 0]),
  coherence: real([2, 1], [0.9, 0.8]),
});
const sonoResult = () => ({
  time_axis: real([2], [0, 1]), freq_axis: real([2], [0, 1]),
  sono_data: real([2, 2], [1, 2, 3, 4]),
});
const blaResult = () => ({
  freq_axis: real([2], [0, 1]), tf_data: cplx([2, 1], [1, 0, 1, 0]),
  bla_sigma_nl: real([2, 1], [0.1, 0.2]), bla_sigma_n: real([2, 1], [0.01, 0.02]),
  bla: { M: 2, n_exc: 1 },
});

/** A 2-channel TimeData-only dataset (the standard actions-test fixture). */
function makeDataset(nSets = 1): DvmaDataset {
  const items: DvmaItem[] = [];
  for (let s = 0; s < nSets; s++) {
    items.push({
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
        time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
      },
      meta: { test_name: `set_${s}`, timestring: `t${s}` },
      settings: { fs: 2 },
    });
  }
  return { formatVersion: 1, pydvmaVersion: '1.5.0', items };
}

/** A recorded capture, as `recordingToItem` builds one. */
function recordedItem(name = 'rec'): DvmaItem {
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 1], isComplex: false, data: Float64Array.from([1, 2, 3]) },
    },
    meta: { test_name: name, timestring: 'tr' },
    settings: { fs: 2 },
  };
}

/** A TF-only file (no source TimeData) — populates the tf view on load. */
function orphanTfDataset(): DvmaDataset {
  return {
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [{
      kind: 'TfData',
      arrays: {
        freq_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 1]) },
        tf_data: {
          shape: [2, 2], isComplex: true,
          data: Float64Array.from([1, 0, 2, 0, 3, 0, 4, 0]),
        },
      },
      meta: { test_name: 'orphan_tf', timestring: 'to' },
      settings: null,
    }],
  };
}

function fakeEngine(responder: (op: string) => Promise<unknown>): EngineStore {
  return {
    status: writable('ready'),
    boot: async () => {},
    whenReady: async () => {},
    enqueue: (op: string) => responder(op),
    client: {} as unknown,
  } as unknown as EngineStore;
}

interface Added { view: ViewId; viewWasEmpty: boolean; }

/** Actions wired to a recording notifier (what App wires to the view store). */
function harness(responder: (op: string) => Promise<unknown> = async () => ({})) {
  const added: Added[] = [];
  const units: ViewId[][] = [];
  const notify: ViewNotifier = {
    linesAdded: (view, info) => added.push({ view, viewWasEmpty: info.viewWasEmpty }),
    unitsChanged: (views) => units.push([...views]),
  };
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const actions = createActions(fakeEngine(responder), sel, settings, undefined, undefined, notify);
  return { sel, settings, actions, added, units };
}

// ── data ADD paths ──────────────────────────────────────────────────────────

test('addRecordedSet announces new time lines; the FIRST capture also releases x', () => {
  const { actions, added } = harness();
  actions.addRecordedSet(recordedItem('a'));
  expect(added).toEqual([{ view: 'time', viewWasEmpty: true }]);
  // A second capture lands beside data that is already there: y only.
  actions.addRecordedSet(recordedItem('b'));
  expect(added[1]).toEqual({ view: 'time', viewWasEmpty: false });
});

test('loadDataset announces every view the file populates (fresh load ⇒ all empty)', () => {
  const { actions, added } = harness();
  actions.loadDataset(makeDataset(1));
  expect(added).toEqual([{ view: 'time', viewWasEmpty: true }]);
});

test('loadDataset append: a view that already held lines re-fits y only', () => {
  const { actions, added } = harness();
  actions.loadDataset(makeDataset(1));
  added.length = 0;
  actions.loadDataset(makeDataset(1), { append: true });
  expect(added).toEqual([{ view: 'time', viewWasEmpty: false }]);
});

test('loadDataset append: a view the appended file fills for the FIRST time releases x', () => {
  const { actions, added } = harness();
  actions.loadDataset(makeDataset(1));            // time only
  added.length = 0;
  actions.loadDataset(orphanTfDataset(), { append: true });
  expect(added).toEqual([{ view: 'tf', viewWasEmpty: true }]);
});

test('a non-append RELOAD counts every view as empty (the old data is dropped)', () => {
  const { actions, added } = harness();
  actions.loadDataset(orphanTfDataset());
  added.length = 0;
  actions.loadDataset(orphanTfDataset());         // replaces, does not append
  expect(added).toEqual([{ view: 'tf', viewWasEmpty: true }]);
});

// ── first calc vs recompute ────────────────────────────────────────────────

test('calcFft announces frequency lines on the FIRST calc only, not on a recompute', async () => {
  const { actions, added } = harness(async (op) => (op === 'calc_fft' ? fftResult() : {}));
  actions.loadDataset(makeDataset(1));
  added.length = 0;
  await actions.calcFft('all');
  expect(added).toEqual([{ view: 'frequency', viewWasEmpty: true }]);
  await actions.calcFft('all');                   // same slice recomputed
  expect(added).toHaveLength(1);
});

test('calcFft on a SECOND set announces again, with the view no longer empty', async () => {
  const { sel, actions, added } = harness(async (op) => (op === 'calc_fft' ? fftResult() : {}));
  actions.loadDataset(makeDataset(2));
  const [a, b] = get(sel.sets).map((s) => s.id);
  added.length = 0;
  await actions.calcFft(a);
  await actions.calcFft(b);
  expect(added).toEqual([
    { view: 'frequency', viewWasEmpty: true },
    { view: 'frequency', viewWasEmpty: false },
  ]);
});

test('calcPsd announces the frequency view once (psd + coherence are one slice pair)', async () => {
  const { actions, added } = harness(async (op) => (op === 'calc_psd' ? psdResult() : {}));
  actions.loadDataset(makeDataset(1));
  added.length = 0;
  await actions.calcPsd('all');
  expect(added).toEqual([{ view: 'frequency', viewWasEmpty: true }]);
  await actions.calcPsd('all');
  expect(added).toHaveLength(1);
});

test('calcTf announces tf lines on the first calc only, not on a recompute', async () => {
  const { actions, added } = harness(async (op) => (op === 'calc_tf' ? tfResult() : {}));
  actions.loadDataset(makeDataset(1));
  added.length = 0;
  await actions.calcTf('all');
  expect(added).toEqual([{ view: 'tf', viewWasEmpty: true }]);
  await actions.calcTf('all');
  expect(added).toHaveLength(1);
});

test("calcTf 'across' (ensemble) announces the tf view for its single attached slice", async () => {
  const { sel, settings, actions, added } =
    harness(async (op) => (op === 'calc_tf_averaged' ? tfResult() : {}));
  actions.loadDataset(makeDataset(2));
  const a = get(sel.sets)[0].id;
  settings.patch(a, 'tf', { averaging: 'across' });
  added.length = 0;
  await actions.calcTf('all');
  expect(added).toEqual([{ view: 'tf', viewWasEmpty: true }]);
  await actions.calcTf('all');
  expect(added).toHaveLength(1);
});

test('calcSono announces the sono view once; a re-run at another channel does not', async () => {
  const { sel, actions, added } = harness(async (op) => (op === 'calc_sono' ? sonoResult() : {}));
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;
  added.length = 0;
  await actions.calcSono(id, 0);
  expect(added).toEqual([{ view: 'sono', viewWasEmpty: true }]);
  await actions.calcSono(id, 1);
  expect(added).toHaveLength(1);
});

test('addBlaSets announces the tf view once for the whole run', () => {
  const { actions, added } = harness();
  actions.loadDataset(makeDataset(1));
  added.length = 0;
  actions.addBlaSets([blaResult(), blaResult()], { names: ['bla q1', 'bla q2'] });
  expect(added).toEqual([{ view: 'tf', viewWasEmpty: true }]);
});

test('addBlaSets with no results announces nothing', () => {
  const { actions, added } = harness();
  actions.loadDataset(makeDataset(1));
  added.length = 0;
  actions.addBlaSets([]);
  expect(added).toHaveLength(0);
});

// ── recompute-in-place must NOT reset ──────────────────────────────────────

test('cleanImpulse + its recomputes announce nothing (the user keeps their window)', async () => {
  const cleanResult = () => ({
    time_axis: real([3], [0, 0.5, 1]),
    time_data: real([3, 2], [0, 0, 3, 4, 0, 0]),
  });
  const { sel, actions, added } = harness(async (op) => {
    if (op === 'clean_impulse') return cleanResult();
    if (op === 'calc_fft') return fftResult();
    return {};
  });
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;
  await actions.calcFft(id);
  added.length = 0;
  await actions.cleanImpulse(id, 0);
  expect(added).toHaveLength(0);
});

// ── UNITS changes ──────────────────────────────────────────────────────────

test('setCalFactors announces a units change on time + frequency + tf', () => {
  const { sel, actions, units } = harness();
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;
  actions.setCalFactors(id, [0.01, 0.01], ['g', 'g']);
  expect(units).toEqual([['time', 'frequency', 'tf']]);
});

test('setIwPower announces a units change on the spectral views only', () => {
  const { sel, actions, units } = harness();
  actions.loadDataset(makeDataset(1));
  const id = get(sel.sets)[0].id;
  actions.setIwPower(id, 1);
  expect(units).toEqual([['frequency', 'tf']]);
});

test('notifyUnitsChanged passes a card-driven quantity switch straight through', () => {
  // The Frequency card's FFT ↔ PSD ↔ CSD toggle reaches the view layer here
  // (it holds `actions`, not the view store).
  const { actions, units } = harness();
  actions.notifyUnitsChanged(['frequency']);
  expect(units).toEqual([['frequency']]);
});

test('actions built WITHOUT a notifier behave exactly as before', async () => {
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const engine = fakeEngine(async (op) => (op === 'calc_fft' ? fftResult() : {}));
  const actions = createActions(engine, sel, settings);
  actions.loadDataset(makeDataset(1));
  actions.addRecordedSet(recordedItem());
  await actions.calcFft('all');
  actions.notifyUnitsChanged(['frequency']);           // no-op, must not throw
  expect(Object.keys(get(actions.derived))).toHaveLength(2);
});
