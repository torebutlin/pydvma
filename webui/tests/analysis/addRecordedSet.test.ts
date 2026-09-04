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

// ---- round-13: a bridged capture keeps its FULL acquisition settings ----

test('recordingToItem merges the container settings under the capture-derived keys', () => {
  const rec = fakeRecording(1, 100);
  const item = recordingToItem(rec, 'bridged', {
    deviceDriver: 'nidaq',
    settings: {
      fs: 12500,               // the REQUESTED rate — the capture's own wins
      channels: 1, stored_time: 60, device_driver: 'nidaq',
      device_index: 0, NI_mode: 'DAQmx_Val_PseudoDiff', VmaxNI: 5,
      iepe_excit_current_A: { __array__: { dtype: '<f8', shape: [1], data: [0.002] } },
      output_fs: 12500, pretrig_samples: null,
    },
  });
  expect(item.settings).toMatchObject({
    device_index: 0, NI_mode: 'DAQmx_Val_PseudoDiff', VmaxNI: 5,
    output_fs: 12500, pretrig_samples: null,
    iepe_excit_current_A: { __array__: { dtype: '<f8', shape: [1], data: [0.002] } },
  });
  // The four keys the app has always written describe the samples kept.
  expect(item.settings).toMatchObject({
    fs: rec.fs, channels: rec.nChannels,
    stored_time: rec.nSamples / rec.fs, device_driver: 'nidaq',
  });
});

test('recordingToItem without bridge meta still writes the four classic keys', () => {
  const rec = fakeRecording(1, 100);
  const item = recordingToItem(rec, 'web');
  expect(item.settings).toEqual({
    fs: rec.fs, channels: rec.nChannels,
    stored_time: rec.nSamples / rec.fs, device_driver: 'web_audio',
  });
});
