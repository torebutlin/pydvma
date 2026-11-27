/**
 * A line's colour and weight, picked in the tray card's ⋯ pop-up
 * (`actions.setLineStyle` / `actions.resetLineStyles`, 2026-11-27, 4C6 lab:
 * two lines from two sets came out the same colour).
 *
 * The choice lives on the selection record and reaches the document when it
 * is written (`stampUiState` → `ui.line_colors` / `ui.line_widths`), like a
 * renamed channel, so a Save, an autosave, the session journal and a restore
 * all keep it. A modal fit's lines follow their measured line's colour.
 */
import { get, writable } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection, LINE_PALETTE } from '../../src/lib/stores/selection';
import { createAnalysisSettings } from '../../src/lib/stores/analysisSettings';
import { createModalStore } from '../../src/lib/stores/modal';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { DvmaDataset, DvmaItem } from '../../src/lib/model/dataset';

const real = (shape: number[], data: number[]) =>
  ({ shape, data: Float64Array.from(data), complex: false });
const cplx = (shape: number[], interleaved: number[]) =>
  ({ shape, data: Float64Array.from(interleaved), complex: true });

/** An engine answering a TF and a one-mode fit. */
const engine = () => ({
  status: writable('ready'),
  boot: async () => {},
  whenReady: async () => {},
  enqueue: async (op: string) => (op === 'calc_tf'
    ? { freq_axis: real([2], [0, 1]), tf_data: cplx([2, 1], [2, 0, 2, 0]), coherence: real([2, 1], [0.9, 0.8]) }
    : op === 'calc_fit'
      ? {
        M: real([1, 6], [80, 0.02, 1, 0, 0, 0]),
        fn: real([1], [80]), zn: real([1], [0.02]), an: real([1, 1], [1]), pn: real([1, 1], [0]),
        message: 'fn=80.00 (Hz)',
        recon_freq_axis: real([2], [60, 110]), recon_tf_data: cplx([2, 1], [1, 0, 1, 0]),
        global_freq_axis: real([2], [0, 1]), global_tf_data: cplx([2, 1], [0.5, 0, 0.5, 0]),
      }
      : {}),
  client: {} as unknown,
} as unknown as EngineStore);

/** A 2-channel capture, as the logger records one. */
function capture(name: string, uid?: string, ui?: DvmaItem['ui']): DvmaItem {
  return {
    kind: 'TimeData',
    arrays: {
      time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
      time_data: { shape: [3, 2], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6]) },
    },
    meta: { test_name: name, timestring: 'tr', ...(uid ? { unique_id: uid } : {}) },
    settings: { fs: 2, channels: 2 },
    ...(ui ? { ui } : {}),
  };
}

function setup() {
  const sel = createSelection();
  const settings = createAnalysisSettings(sel);
  const modal = createModalStore();
  const actions = createActions(engine(), sel, settings, modal);
  return { sel, actions };
}

/** Save → reopen: the bytes a Save writes, loaded into a FRESH app. */
function reopen(actions: ReturnType<typeof createActions>) {
  actions.stampUiState();
  const ds = get(actions.dataset) as DvmaDataset;
  const fresh = setup();
  fresh.actions.loadDataset(readDvma(writeDvma(ds)));
  return fresh;
}

const rec = (sel: ReturnType<typeof createSelection>, i = 0) => get(sel.sets)[i];

test('a picked colour and weight survive Save and reopen', () => {
  const { actions } = setup();
  const id = actions.addRecordedSet(capture('beam'));
  actions.setLineStyle(id, 1, { color: LINE_PALETTE[6] });
  actions.setLineStyle(id, 0, { weight: 'bold' });

  const after = reopen(actions);

  expect(rec(after.sel).colors).toEqual([LINE_PALETTE[0], LINE_PALETTE[6]]);
  expect(rec(after.sel).widths).toEqual(['bold', 'normal']);
  // Reset in the reopened file goes back to the colours IT gave the set.
  after.actions.resetLineStyles(rec(after.sel).id);
  expect(rec(after.sel).colors).toEqual([LINE_PALETTE[0], LINE_PALETTE[1]]);
});

test('an untouched set writes no style keys', () => {
  const { actions } = setup();
  actions.addRecordedSet(capture('beam'));
  actions.stampUiState();
  const ui = get(actions.dataset)!.items[0].ui ?? {};
  expect(ui.line_colors).toBeUndefined();
  expect(ui.line_widths).toBeUndefined();
});

test('a style change re-emits the document once', () => {
  const { actions } = setup();
  const id = actions.addRecordedSet(capture('beam'));
  let emissions = 0;
  const unsub = actions.dataset.subscribe(() => { emissions += 1; });
  emissions = 0;

  actions.setLineStyle(id, 0, { color: LINE_PALETTE[3], weight: 'thin' });
  expect(emissions).toBe(1);
  actions.setLineStyle(id, 0, { color: LINE_PALETTE[3] });   // no change: no emit
  expect(emissions).toBe(1);
  actions.resetLineStyles(id);
  expect(emissions).toBe(2);
  unsub();
});

test('malformed style keys in a file are ignored', () => {
  const { sel, actions } = setup();
  expect(() => actions.loadDataset({
    formatVersion: 2, pydvmaVersion: '2.9.1',
    items: [capture('beam', 'u1', {
      line_colors: { 0: 'red', 1: '#12345', 5: '#123456' } as Record<string, string>,
      line_widths: { 0: 'huge', 1: 'thin', x: 'bold' } as unknown as Record<string, 'bold'>,
    })],
  })).not.toThrow();
  expect(rec(sel).colors).toEqual([LINE_PALETTE[0], LINE_PALETTE[1]]);
  expect(rec(sel).widths).toEqual(['normal', 'thin']);
});

test('styles are restored for a set opened from a TF-only file, with its channel labels', () => {
  const { sel, actions } = setup();
  const tf: DvmaItem = {
    kind: 'TfData',
    arrays: {
      freq_axis: { shape: [2], isComplex: false, data: Float64Array.from([0, 1]) },
      tf_data: { shape: [2, 2], isComplex: true, data: Float64Array.from([1, 0, 2, 0, 3, 0, 4, 0]) },
    },
    meta: { test_name: 'grid' },
    settings: { fs: 2, channels: 2 },
    ui: { line_colors: { 1: LINE_PALETTE[9] }, line_widths: { 0: 'bold' }, channel_labels: { 0: 'p1' } },
  };
  actions.loadDataset({ formatVersion: 2, pydvmaVersion: '2.9.1', items: [tf] });
  expect(rec(sel).colors[1]).toBe(LINE_PALETTE[9]);
  expect(rec(sel).widths[0]).toBe('bold');
  expect(get(sel.channelLabel)(rec(sel).id, 0)).toBe('p1');
});

test('recolouring a fitted line recolours its fit line, not its weight', async () => {
  const { sel, actions } = setup();
  actions.loadDataset({ formatVersion: 2, pydvmaVersion: '2.9.1', items: [capture('beam', 'UID1')] });
  await actions.calcTf('all');
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  const data = get(sel.setsView).find((s) => s.role === 'data')!;
  const fit = get(sel.setsView).find((s) => s.role === 'fit')!;

  actions.setLineStyle(data.id, 1, { color: LINE_PALETTE[10], weight: 'bold' });

  expect(sel.lineColor(fit.id, 1)).toBe(LINE_PALETTE[10]);
  expect(sel.lineColor(fit.id, 0)).toBe(sel.lineColor(data.id, 0));
  expect(get(sel.sets).find((s) => s.id === fit.id)!.widths[1]).toBe('normal');
  actions.resetLineStyles(data.id);
  expect(sel.lineColor(fit.id, 1)).toBe(LINE_PALETTE[1]);
});

test('a Nonlin replace\'s Undo brings the sets back with their styles', () => {
  const { sel, actions } = setup();
  actions.loadDataset({ formatVersion: 2, pydvmaVersion: '2.9.1', items: [capture('m', 'uid-m')] });
  const id = rec(sel).id;
  actions.setLineStyle(id, 0, { color: LINE_PALETTE[7], weight: 'bold' });

  actions.removeBlaRun([id], { label: 'set' });
  expect(actions.undoRemoveBlaRun()).toBe(true);

  expect(rec(sel).colors).toEqual([LINE_PALETTE[7], LINE_PALETTE[1]]);
  expect(rec(sel).widths).toEqual(['bold', 'normal']);
  actions.resetLineStyles(rec(sel).id);
  expect(rec(sel).colors).toEqual([LINE_PALETTE[0], LINE_PALETTE[1]]);
});

test('a restored pick does not move the next set\'s automatic colours', () => {
  // Saved: A's ch1 picked as palette 6 (it was given 1); B untouched, given 2, 3.
  const { sel, actions } = setup();
  actions.loadDataset({
    formatVersion: 2, pydvmaVersion: '2.9.1',
    items: [capture('A', 'ua', { line_colors: { 1: LINE_PALETTE[6] } }), capture('B', 'ub')],
  });
  expect(rec(sel, 0).colors).toEqual([LINE_PALETTE[0], LINE_PALETTE[6]]);
  expect(rec(sel, 1).colors).toEqual([LINE_PALETTE[2], LINE_PALETTE[3]]);
});

test('delete, then pick, then reopen: no two lines share a colour', () => {
  // Reviewer's repro: log A, log B, delete A (B is 2, 3); pick a colour on B;
  // a reopen gives B fresh automatic colours (0, 1), and the pick landed on
  // the other line's colour.
  for (const [ch, pick] of [[0, 1], [1, 0]] as const) {
    const { actions } = setup();
    const a = actions.addRecordedSet(capture('A'));
    const b = actions.addRecordedSet(capture('B'));
    actions.removeSet(a);
    actions.setLineStyle(b, ch, { color: LINE_PALETTE[pick] });
    const after = reopen(actions);
    const cols = rec(after.sel).colors;
    expect(cols[ch]).toBe(LINE_PALETTE[pick]);
    expect(new Set(cols).size).toBe(2);
  }
});

test('recolouring a line whose fit covers only some lines recolours that fit line only', async () => {
  // A fit over the lines left visible: hide ch 1 of a 3-channel set, fit ch 2.
  // The fit card then has ONE line, mirroring source ch 2.
  const sel = createSelection();
  const tf2col = {
    freq_axis: real([2], [0, 1]),
    tf_data: cplx([2, 2], [1, 0, 2, 0, 1, 0, 2, 0]),
    coherence: real([2, 2], [0.9, 0.9, 0.8, 0.8]),
  };
  const base = engine();
  const eng = { ...base, enqueue: async (op: string) => (op === 'calc_tf' ? tf2col : base.enqueue(op)) } as EngineStore;
  const actions = createActions(eng, sel, createAnalysisSettings(sel), createModalStore());
  actions.loadDataset({
    formatVersion: 2, pydvmaVersion: '2.9.1',
    items: [{
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [3], isComplex: false, data: Float64Array.from([0, 0.5, 1]) },
        time_data: { shape: [3, 3], isComplex: false, data: Float64Array.from([1, 2, 3, 4, 5, 6, 7, 8, 9]) },
      },
      meta: { test_name: 'set_0', timestring: 't0', unique_id: 'U3' },
      settings: { fs: 2 },
    }],
  });
  const id = rec(sel).id;
  await actions.calcTf('all');
  sel.cycleLine(id, 1); sel.cycleLine(id, 1);           // hide ch 1
  await actions.calcFit('all', [60, 110], 'acc', 'fit', 1);
  await new Promise((r) => setTimeout(r, 0));
  const fit = get(sel.setsView).find((s) => s.role === 'fit')!;
  expect(fit.nChannels).toBe(1);

  actions.setLineStyle(id, 1, { color: LINE_PALETTE[8] });   // not fitted
  expect(sel.lineColor(fit.id, 0)).toBe(LINE_PALETTE[2]);
  actions.setLineStyle(id, 2, { color: LINE_PALETTE[9] });   // the fitted line
  expect(sel.lineColor(fit.id, 0)).toBe(LINE_PALETTE[9]);
});
