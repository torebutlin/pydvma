/**
 * Round-4 bugs 3 + 4: loading a file that already carries derived kinds.
 *
 * Bug 3 — a legacy `.npy` (or `.dvma`) that contains a TF/FFT/coherence must
 * SEED those views on load, not just the time series. `loadDataset` links
 * each derived item to its source TimeData set via `id_link → unique_id` and
 * populates `derived[setId].tf / .freq / .csd`.
 *
 * Bug 4 — `loadDataset` returns the populated views in priority order
 * (time → frequency → tf → sono) so App can jump the active view to one that
 * HAS data. A TF-only file (no TimeData) yields an orphan set + `['tf']`.
 */
import { readFileSync } from 'node:fs';
import { get } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createEngineStore } from '../../src/lib/stores/engine';
import { readDvma } from '../../src/lib/codec/dvma';
import { buildPlotModel, type SetArrays, type VisibleLine } from '../../src/lib/plot/model';
import type { EngineClient } from '../../src/lib/worker/client';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';
import type { NpyArray } from '../../src/lib/codec/npy';

const stubClient: EngineClient = { init: async () => {}, call: async () => ({}) as any };

function actions() {
  const sel = createSelection();
  const a = createActions(createEngineStore(stubClient), sel);
  return { sel, a };
}

const realArr = (shape: number[], data: number[]): NpyArray =>
  ({ shape, isComplex: false, data: Float64Array.from(data) });
/** Complex NpyArray stored interleaved [re,im,…] (the npy codec convention). */
const cplxArr = (shape: number[], interleaved: number[]): NpyArray =>
  ({ shape, isComplex: true, data: Float64Array.from(interleaved) });

function timeItem(uid: string): DvmaItem {
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: realArr([3], [0, 0.5, 1]),
      time_data: realArr([3, 2], [1, 2, 3, 4, 5, 6]),
    },
    meta: { test_name: 'src', timestring: 't0', unique_id: uid },
    settings: { fs: 2 },
  };
}

function tfItem(link: string | null): DvmaItem {
  return {
    kind: 'TfData',
    arrays: {
      freq_axis: realArr([2], [0, 1]),
      tf_data: cplxArr([2, 1], [1, 0, 0.5, 0.5]),     // (Nf=2, Nout=1) complex
      tf_coherence: realArr([2, 1], [0.9, 0.8]),
    },
    meta: { test_name: 'tf', timestring: 't0', ...(link ? { id_link: link } : {}) },
    settings: { fs: 2 },
  };
}

function freqItem(link: string | null): DvmaItem {
  return {
    kind: 'FreqData',
    arrays: {
      freq_axis: realArr([2], [0, 1]),
      freq_data: cplxArr([2, 2], [1, 0, 2, 0, 3, 0, 4, 0]),  // (Nf=2, Nc=2) complex
    },
    meta: { test_name: 'fft', timestring: 't0', ...(link ? { id_link: link } : {}) },
    settings: { fs: 2 },
  };
}

test('bug 3: a linked TfData + FreqData seed the TF and Frequency views on load', () => {
  const { sel, a } = actions();
  const ds: DvmaDataset = {
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [timeItem('u1'), freqItem('u1'), tfItem('u1')],
  };
  const views = a.loadDataset(ds);

  // ONE set (the derived items attach to the source TimeData, not new sets).
  expect(get(sel.sets)).toHaveLength(1);
  const setId = get(sel.sets)[0].id;
  const d = get(a.derived);

  // Time, FFT, and TF slices all present on the one set.
  expect(d[setId].time).toBeDefined();
  expect(d[setId].freq, 'FFT view must be seeded from the loaded FreqData').toBeDefined();
  expect(d[setId].tf, 'TF view must be seeded from the loaded TfData').toBeDefined();

  // TF slice carries the out/in remap fields with the documented chIn=0
  // convention (pydvma TfData has no input-channel field) and the source
  // channel count (2), and its decoded columns match the stored TF.
  expect(d[setId].tf!.chIn).toBe(0);
  expect(d[setId].tf!.nChannels).toBe(2);
  expect(d[setId].tf!.data.shape).toEqual([2, 1]);
  expect(Array.from(d[setId].tf!.data.re)).toEqual([1, 0.5]);
  expect(Array.from(d[setId].tf!.data.im!)).toEqual([0, 0.5]);
  expect(d[setId].tf!.coherence).toBeDefined();

  // Populated views (priority order) — the common case still lands on time.
  expect(views).toEqual(['time', 'frequency', 'tf']);
});

test('bug 4: a TF-only file (no TimeData) makes an orphan set and lands on the TF view', () => {
  const { sel, a } = actions();
  const ds: DvmaDataset = {
    formatVersion: 1, pydvmaVersion: '1.5.0', items: [tfItem(null)],
  };
  const views = a.loadDataset(ds);

  // An orphan set is created so the TF still shows. Round-5 item 3: an orphan
  // TF has NO measured input, so its columns ARE the lines — chIn = null and
  // nChannels = Nout (1 column here), NOT Nout + 1.
  expect(get(sel.sets)).toHaveLength(1);
  const setId = get(sel.sets)[0].id;
  expect(get(sel.sets)[0].nChannels).toBe(1);
  const d = get(a.derived);
  expect(d[setId].tf).toBeDefined();
  expect(d[setId].tf!.chIn).toBeNull();
  expect(d[setId].tf!.nChannels).toBe(1);

  // No time series ⇒ the only populated view is TF, so App jumps there.
  expect(views).toEqual(['tf']);
});

test('round-5 item 3: a multi-column orphan TF makes N chips/lines (columns are the lines)', () => {
  // An 11-column ruler-grid orphan TF (the ruler_grid_acc_3.mat shape) must
  // load as 11 source channels — one chip and one distinct line per column —
  // NOT 12 (the old chIn=0 convention that added a phantom input channel and
  // left 11 chips but only 10 drawable lines).
  const cols = 11;
  const nf = 2;
  const interleaved: number[] = [];
  for (let f = 0; f < nf; f++) for (let c = 0; c < cols; c++) interleaved.push(c + 1, 0);
  const orphan: DvmaItem = {
    kind: 'TfData',
    arrays: {
      freq_axis: realArr([nf], [0, 1]),
      tf_data: cplxArr([nf, cols], interleaved),   // (Nf, 11) complex
    },
    meta: { test_name: 'ruler', timestring: 't0' },   // NO id_link ⇒ orphan
    settings: { fs: 2 },
  };
  const { sel, a } = actions();
  a.loadDataset({ formatVersion: 1, pydvmaVersion: '1.5.0', items: [orphan] });

  expect(get(sel.sets)).toHaveLength(1);
  const set = get(sel.sets)[0];
  expect(set.nChannels).toBe(cols);                 // 11 chips, CH 0..10
  // 11 distinct colours (identity mapping ⇒ chip colour == line colour).
  expect(new Set(set.colors).size).toBe(cols);
  const setId = set.id;
  const d = get(a.derived);
  expect(d[setId].tf!.chIn).toBeNull();             // orphan ⇒ no input to drop
  expect(d[setId].tf!.nChannels).toBe(cols);
});

test('bug 4: an FFT-only file lands on the Frequency view', () => {
  const { a } = actions();
  const views = a.loadDataset({
    formatVersion: 1, pydvmaVersion: '1.5.0', items: [freqItem(null)],
  });
  expect(views).toEqual(['frequency']);
});

test('bug 4: a plain time-only file keeps the time view', () => {
  const { a } = actions();
  const views = a.loadDataset({
    formatVersion: 1, pydvmaVersion: '1.5.0', items: [timeItem('u1')],
  });
  expect(views).toEqual(['time']);
});

test('bug 3 end-to-end: a real pydvma .dvma (Time+FFT+CrossSpec+TF) seeds tf + freq', () => {
  // legacy_with_tf.dvma is written by pydvma's container.save (Time + derived
  // FreqData/CrossSpecData/TfData, real complex128 arrays, `__uuid__`-tagged
  // id_link). Exercises the FULL read path: readDvma decodes the uuid tags to
  // matching strings so loadDataset links the TF/FFT back onto the source set.
  const bytes = new Uint8Array(readFileSync('tests/fixtures/legacy_with_tf.dvma'));
  const { sel, a } = actions();
  const views = a.loadDataset(readDvma(bytes));

  expect(get(sel.sets)).toHaveLength(1);            // derived items linked, not new sets
  const setId = get(sel.sets)[0].id;
  const d = get(a.derived);
  expect(d[setId].time).toBeDefined();
  expect(d[setId].freq, 'loaded FFT must seed the Frequency view').toBeDefined();
  expect(d[setId].tf, 'loaded TF must seed the TF view').toBeDefined();
  expect(d[setId].csd, 'loaded coherence must seed').toBeDefined();
  expect(d[setId].tf!.chIn).toBe(0);
  expect(d[setId].tf!.nChannels).toBe(2);
  expect(d[setId].tf!.data.shape[1]).toBe(1);       // Nout = nChannels - 1
  // Time present ⇒ the common case still lands on the time view.
  expect(views[0]).toBe('time');
  expect(views).toContain('tf');
  expect(views).toContain('frequency');
});

test('an unlinked derived item (missing id_link) still shows via its own set', () => {
  // A TimeData plus a TF whose id_link matches nothing: the TF must not be
  // dropped — it gets an orphan set so the TF view is still available.
  const { sel, a } = actions();
  a.loadDataset({
    formatVersion: 1, pydvmaVersion: '1.5.0',
    items: [timeItem('u1'), tfItem('does-not-match')],
  });
  expect(get(sel.sets)).toHaveLength(2);        // source set + orphan TF set
  const d = get(a.derived);
  expect(Object.values(d).some((s) => s.tf)).toBe(true);
});

test('round-5 item 3 end-to-end: a real orphan-TF .dvma → 3 chips + 3 distinct plotted lines', () => {
  // orphan_tf_3col.dvma is written by pydvma's container.save from a bare
  // TfData (4 freq points × 3 columns, NO source TimeData, NO id_link) — the
  // shape a JW-logger `.mat` import produces. This exercises the FULL read
  // path (readDvma → loadDataset) and the orphan convention: 3 columns ⇒ 3
  // source channels (chIn=null identity), 3 distinct chip colours, and — fed
  // through buildPlotModel — 3 distinct plotted lines, none dropped.
  const bytes = new Uint8Array(readFileSync('tests/fixtures/orphan_tf_3col.dvma'));
  const { sel, a } = actions();
  const views = a.loadDataset(readDvma(bytes));

  expect(views).toEqual(['tf']);                     // TF-only ⇒ lands on TF
  expect(get(sel.sets)).toHaveLength(1);
  const set = get(sel.sets)[0];
  expect(set.nChannels).toBe(3);                     // 3 chips (CH 0..2), NOT 4
  expect(new Set(set.colors).size).toBe(3);          // 3 distinct colours
  const setId = set.id;
  const slice = get(a.derived)[setId].tf!;
  expect(slice.chIn).toBeNull();                     // orphan ⇒ no input to drop
  expect(slice.nChannels).toBe(3);
  expect(slice.data.shape).toEqual([4, 3]);

  // Fed through the plot model, all 3 columns draw as distinct lines whose
  // colours match the tray chips (identity mapping — none dropped).
  const setArrays: SetArrays[] = [{ setId, tf: slice }];
  const visible: VisibleLine[] = [0, 1, 2].map((ch) => ({
    setId, ch, state: 'on', color: set.colors[ch],
  }));
  const model = buildPlotModel({ view: 'tf', tfPlotType: 'mag', sets: setArrays, visible });
  expect(model.lines).toHaveLength(3);
  expect(model.lines.map((l) => l.color)).toEqual(set.colors);
});
