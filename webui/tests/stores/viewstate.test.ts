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

test('state is serialisable and restorable (debuggability, spec §11)', () => {
  const vs = createViewState();
  vs.setRange('sono', { x: [0, 2], y: [0, 1500] });
  const snap = vs.serialize();
  const vs2 = createViewState();
  vs2.restore(JSON.parse(JSON.stringify(snap)));
  vs2.activate('sono');
  expect(get(vs2.current).range.x).toEqual([0, 2]);
});
