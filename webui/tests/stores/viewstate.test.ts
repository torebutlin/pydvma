import { get } from 'svelte/store';
import { expect, test } from 'vitest';
import { createViewState } from '../../src/lib/stores/viewstate';

test('axis ranges are per-view and restored on return', () => {
  const vs = createViewState();
  vs.setRange('time', { x: [0, 0.5], y: [-1, 1] });
  vs.activate('tf');
  expect(get(vs.current).range.x).toBeNull();       // tf untouched
  vs.activate('time');
  expect(get(vs.current).range.x).toEqual([0, 0.5]);
});

test('zoom history: push/back/forward', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [0, 500], y: [-60, 40] });
  vs.setRange('tf', { x: [80, 120], y: [-30, 20] });
  vs.back('tf');
  expect(get(vs.current).range.x).toEqual([0, 500]);
  vs.forward('tf');
  expect(get(vs.current).range.x).toEqual([80, 120]);
});

test('back from first zoom restores the initial null (autofit) range', () => {
  const vs = createViewState();
  vs.activate('time');
  vs.setRange('time', { x: [0, 0.25], y: [-2, 2] });
  vs.back('time');
  expect(get(vs.current).range).toEqual({ x: null, y: null });  // initial autofit state
  vs.forward('time');
  expect(get(vs.current).range.x).toEqual([0, 0.25]);
});

test('frequency x-range is shared across the TF plot-type family', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [100, 300], y: [-40, 10] });
  expect(get(vs.sharedFreqRange)).toEqual([100, 300]);   // feeds Nyquist fmin/fmax
});

test('restore ignores invalid snapshots entirely (no partial application)', () => {
  const vs = createViewState();
  vs.setRange('time', { x: [0, 1], y: [-1, 1] });
  vs.restore({});
  vs.restore('garbage');
  vs.restore(null);
  vs.restore({ views: { time: {} }, active: 'tf' });   // missing view keys
  expect(get(vs.active)).toBe('time');                 // untouched
  expect(get(vs.current).range.x).toEqual([0, 1]);     // untouched
});

test('restore merges stale-schema slices over fresh defaults', () => {
  const vs = createViewState();
  vs.setRange('tf', { x: [1, 2], y: [3, 4] });
  const stale = JSON.parse(JSON.stringify(vs.serialize()));
  delete stale.views.tf.future;                        // field absent in an older schema
  const vs2 = createViewState();
  vs2.restore(stale);
  vs2.activate('tf');
  expect(get(vs2.current).range.x).toEqual([1, 2]);
  vs2.back('tf');                                      // needs the defaulted future: []
  expect(get(vs2.current).range).toEqual({ x: null, y: null });
  vs2.forward('tf');
  expect(get(vs2.current).range.x).toEqual([1, 2]);
});

test('restore coerces an invalid active view to time', () => {
  const vs = createViewState();
  vs.activate('sono');
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  snap.active = 'bogus';
  const vs2 = createViewState();
  vs2.restore(snap);
  expect(get(vs2.active)).toBe('time');
});

test('zoom history is capped at 50 entries; back() still walks correctly', () => {
  const vs = createViewState();
  for (let i = 1; i <= 60; i++) vs.setRange('time', { x: [0, i], y: [0, 1] });
  expect(get(vs.current).history.length).toBe(50);
  vs.back('time');
  expect(get(vs.current).range.x).toEqual([0, 59]);
  for (let i = 0; i < 49; i++) vs.back('time');
  expect(get(vs.current).range.x).toEqual([0, 10]);    // oldest surviving entry
  vs.back('time');                                     // stack empty -> no-op
  expect(get(vs.current).range.x).toEqual([0, 10]);
});

test('state is serialisable and restorable (debuggability, spec §11)', () => {
  const vs = createViewState();
  vs.setRange('sono', { x: [0, 2], y: [0, 1500] });
  const snap = vs.serialize();
  const vs2 = createViewState();
  vs2.restore(JSON.parse(JSON.stringify(snap)));
  vs2.activate('sono');
  expect(get(vs2.current).range.x).toEqual([0, 2]);
});
