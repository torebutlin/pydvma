import { get } from 'svelte/store';
import { expect, test, beforeEach } from 'vitest';
import { createSelection, LINE_PALETTE } from '../../src/lib/stores/selection';

let sel: ReturnType<typeof createSelection>;
beforeEach(() => {
  sel = createSelection();
  sel.addSet({ name: 'set_0', nChannels: 2, durationS: 2, timestamp: 't0' }); // id 0
  sel.addSet({ name: 'set_1', nChannels: 2, durationS: 2, timestamp: 't1' }); // id 1
  sel.addSet({ name: 'set_2', nChannels: 8, durationS: 2, timestamp: 't2' }); // id 2
});

test('lines default on; individual cycle on->fade->off->on', () => {
  expect(get(sel.state)(0, 1)).toBe('on');
  sel.cycleLine(0, 1); expect(get(sel.state)(0, 1)).toBe('fade');
  sel.cycleLine(0, 1); expect(get(sel.state)(0, 1)).toBe('off');
  sel.cycleLine(0, 1); expect(get(sel.state)(0, 1)).toBe('on');
});

test('set cycle drives every channel in the set together', () => {
  sel.cycleSet(2);
  for (let ch = 0; ch < 8; ch++) expect(get(sel.state)(2, ch)).toBe('fade');
});

test('mixed set cycles to uniform on first', () => {
  sel.cycleLine(1, 0);                       // set_1 now mixed (fade, on)
  sel.cycleSet(1);
  expect(get(sel.state)(1, 0)).toBe('on');
  expect(get(sel.state)(1, 1)).toBe('on');
});

test('channel cycle applies across all sets, including collapsed', () => {
  sel.cycleChannel(1);
  expect(get(sel.state)(0, 1)).toBe('fade');
  expect(get(sel.state)(1, 1)).toBe('fade');
  expect(get(sel.state)(2, 1)).toBe('fade');
  expect(get(sel.state)(0, 0)).toBe('on');   // other channels untouched
});

test('solo isolates one set; steppers move the solo', () => {
  sel.solo(1);
  expect(get(sel.state)(1, 0)).toBe('on');
  expect(get(sel.state)(0, 0)).toBe('off');
  sel.step(1);                                // solo moves to set_2
  expect(get(sel.state)(2, 0)).toBe('on');
  expect(get(sel.state)(1, 0)).toBe('off');
});

test('allOff flags a fully-off set (legend omission + strikethrough)', () => {
  sel.cycleSet(0); sel.cycleSet(0);           // on -> fade -> off
  expect(get(sel.setsView)[0].allOff).toBe(true);
  expect(get(sel.legendEntries).some(e => e.setId === 0)).toBe(false);
  expect(get(sel.legendEntries).some(e => e.setId === 1)).toBe(true);
});

test('rename propagates to legend labels', () => {
  sel.rename(0, 'hammer test');
  expect(get(sel.legendEntries)[0].label).toBe('hammer test · ch_0');
});

test('trayFocus: solo → that set; all shown → "all"; ≤1 set → "all"', () => {
  // Three sets present (from beforeEach). All shown initially → 'all'.
  sel.all();
  expect(get(sel.trayFocus)).toBe('all');
  sel.solo(1);
  expect(get(sel.trayFocus)).toBe(1);          // exactly one set fully on
  // Bringing a second set back on leaves a non-solo state → 'all'.
  sel.cycleSet(0);                             // set_0 on
  expect(get(sel.trayFocus)).toBe('all');
  // A partial/faded set is not a clean solo.
  sel.solo(2); sel.cycleLine(2, 1);           // set_2 now mixed on/fade
  expect(get(sel.trayFocus)).toBe('all');
});

test('trayFocus: a single set reads as "all" (no solo distinction)', () => {
  const one = createSelection();
  one.addSet({ name: 'only', nChannels: 2, durationS: 1, timestamp: 't0' });
  expect(get(one.trayFocus)).toBe('all');
});

test('removeSet keeps surviving sets intact; ids stable, index reflows', () => {
  sel.cycleLine(0, 1);                        // 0:1 -> fade
  sel.cycleLine(2, 3); sel.cycleLine(2, 3);   // 2:3 -> off
  const c20 = sel.lineColor(2, 0);
  sel.removeSet(1);                           // remove the MIDDLE set by id
  expect(get(sel.state)(0, 1)).toBe('fade');  // survivors keep exact tri-states
  expect(get(sel.state)(2, 3)).toBe('off');
  expect(get(sel.state)(2, 0)).toBe('on');
  const view = get(sel.setsView);
  expect(view.map(v => v.id)).toEqual([0, 2]);    // identity survives removal
  expect(view.map(v => v.index)).toEqual([0, 1]); // ordering reflows
  expect(sel.lineColor(2, 0)).toBe(c20);          // colour owned, not positional
});

test('removeSet of the highlighted set moves highlight to next survivor', () => {
  sel.solo(1);
  sel.removeSet(1);
  expect(get(sel.highlight)).toBe(2);
});

test('addSet after none() defaults the new lines to on', () => {
  sel.none();
  const id = sel.addSet({ name: 'set_3', nChannels: 2, durationS: 1, timestamp: 't3' });
  expect(id).toBe(3);
  expect(get(sel.state)(id, 0)).toBe('on');
  expect(get(sel.state)(id, 1)).toBe('on');
  expect(get(sel.state)(0, 0)).toBe('off');   // existing sets stay off
  // 12 channels already allocated -> new set's colours wrap the palette
  expect(sel.lineColor(id, 0)).toBe(LINE_PALETTE[0]);
});

test('sets with >4 channels auto-collapse; toggleCollapse flips', () => {
  let view = get(sel.setsView);
  expect(view[2].collapsed).toBe(true);       // 8-channel set
  expect(view[0].collapsed).toBe(false);      // 2-channel set
  sel.toggleCollapse(2); sel.toggleCollapse(0);
  view = get(sel.setsView);
  expect(view[2].collapsed).toBe(false);
  expect(view[0].collapsed).toBe(true);
});

test('colours assigned at addSet by cumulative offset; stable across cycling and removal', () => {
  expect(sel.lineColor(0, 0)).toBe(LINE_PALETTE[0]);
  expect(sel.lineColor(1, 0)).toBe(LINE_PALETTE[2]);  // starts after set_0's 2 channels
  expect(sel.lineColor(2, 5)).toBe(LINE_PALETTE[9]);  // start 4 + ch 5
  const before = [sel.lineColor(2, 0), sel.lineColor(2, 7)];
  sel.cycleSet(0); sel.cycleChannel(1); sel.solo(1);  // heavy state churn
  sel.removeSet(0);
  expect(sel.lineColor(2, 0)).toBe(before[0]);
  expect(sel.lineColor(2, 7)).toBe(before[1]);
  sel.all();                                          // bring set_2 back for legend check
  const entry = get(sel.legendEntries).find(e => e.setId === 2 && e.ch === 0);
  expect(entry?.color).toBe(before[0]);
});

test('step(-1) wraps from the first set to the last', () => {
  sel.solo(0);
  sel.step(-1);
  expect(get(sel.state)(2, 0)).toBe('on');
  expect(get(sel.state)(0, 0)).toBe('off');
  expect(get(sel.highlight)).toBe(2);
});

test('solo with an unknown id is a no-op', () => {
  sel.solo(99);
  expect(get(sel.state)(0, 0)).toBe('on');
  expect(get(sel.state)(2, 0)).toBe('on');
  expect(get(sel.highlight)).toBe(0);
});
