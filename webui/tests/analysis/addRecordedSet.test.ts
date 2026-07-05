/**
 * Integration test: addRecordedSet adds a recorded TimeData item into an
 * existing (or empty) dataset, populates the selection tray, and seeds
 * the derived store with time arrays for immediate plotting.
 */
import { get } from 'svelte/store';
import { expect, test } from 'vitest';
import { createActions } from '../../src/lib/analysis/actions';
import { createSelection } from '../../src/lib/stores/selection';
import { createEngineStore } from '../../src/lib/stores/engine';
import { recordingToItem } from '../../src/lib/stores/acquire';
import type { Recording } from '../../src/lib/audio/source';
import type { EngineClient } from '../../src/lib/worker/client';

/** Stub engine client — no real Worker, no pyodide. Sufficient for
 *  addRecordedSet (which never calls the engine). */
const stubClient: EngineClient = {
  init: async () => {},
  call: async () => ({}) as any,
};

function fakeRecording(nCh = 2, nSamples = 200, fs = 44100): Recording {
  const timeAxis = new Float64Array(nSamples);
  const data = new Float64Array(nSamples * nCh);
  for (let i = 0; i < nSamples; i++) {
    timeAxis[i] = i / fs;
    for (let c = 0; c < nCh; c++) {
      data[i * nCh + c] = Math.sin(2 * Math.PI * 440 * i / fs + c);
    }
  }
  return { data, timeAxis, fs, nChannels: nCh, nSamples };
}

test('addRecordedSet creates a dataset when none exists', () => {
  const sel = createSelection();
  const eng = createEngineStore(stubClient);
  const actions = createActions(eng, sel);

  expect(get(actions.dataset)).toBeNull();

  const rec = fakeRecording();
  const item = recordingToItem(rec, 'capture_1');
  const setId = actions.addRecordedSet(item);

  // Dataset is now populated.
  const ds = get(actions.dataset);
  expect(ds).not.toBeNull();
  expect(ds!.items).toHaveLength(1);
  expect(ds!.items[0].kind).toBe('TimeData');

  // Selection tray has one set.
  const sets = get(sel.setsView);
  expect(sets).toHaveLength(1);
  expect(sets[0].id).toBe(setId);
  expect(sets[0].nChannels).toBe(2);

  // Derived store is seeded with time arrays.
  const derived = get(actions.derived);
  expect(derived[setId]).toBeDefined();
  expect(derived[setId].time).toBeDefined();
  expect(derived[setId].time!.axis.length).toBe(200);
});

test('addRecordedSet appends to an existing dataset', () => {
  const sel = createSelection();
  const eng = createEngineStore(stubClient);
  const actions = createActions(eng, sel);

  // Add first set.
  const item1 = recordingToItem(fakeRecording(1, 100), 'first');
  actions.addRecordedSet(item1);

  // Add second set.
  const item2 = recordingToItem(fakeRecording(2, 300), 'second');
  const setId2 = actions.addRecordedSet(item2);

  const ds = get(actions.dataset);
  expect(ds!.items).toHaveLength(2);

  const sets = get(sel.setsView);
  expect(sets).toHaveLength(2);

  // Both have time data in derived.
  const derived = get(actions.derived);
  expect(Object.keys(derived)).toHaveLength(2);
  expect(derived[setId2].time!.axis.length).toBe(300);
});

test('addRecordedSet works alongside loadDataset sets', () => {
  const sel = createSelection();
  const eng = createEngineStore(stubClient);
  const actions = createActions(eng, sel);

  // Simulate loading a dataset first.
  const preItem = recordingToItem(fakeRecording(1, 50), 'loaded');
  actions.loadDataset({
    formatVersion: 2,
    pydvmaVersion: 'test',
    items: [preItem],
  });

  expect(get(sel.setsView)).toHaveLength(1);

  // Now add a recorded set on top.
  const item = recordingToItem(fakeRecording(2, 100), 'recorded');
  const newId = actions.addRecordedSet(item);

  expect(get(sel.setsView)).toHaveLength(2);
  const ds = get(actions.dataset);
  expect(ds!.items).toHaveLength(2);
  expect(get(actions.derived)[newId].time).toBeDefined();
});
