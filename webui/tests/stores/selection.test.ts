import { get } from 'svelte/store';
import { expect, test, beforeEach } from 'vitest';
import { createSelection } from '../../src/lib/stores/selection';

let sel: ReturnType<typeof createSelection>;
beforeEach(() => {
  sel = createSelection();
  sel.addSet({ name: 'set_0', nChannels: 2, durationS: 2, timestamp: 't0' });
  sel.addSet({ name: 'set_1', nChannels: 2, durationS: 2, timestamp: 't1' });
  sel.addSet({ name: 'set_2', nChannels: 8, durationS: 2, timestamp: 't2' });
});

test('lines default on; individual cycle on->fade->off->on', () => {
  expect(get(sel.state)('0:1')).toBe('on');
  sel.cycleLine(0, 1); expect(get(sel.state)('0:1')).toBe('fade');
  sel.cycleLine(0, 1); expect(get(sel.state)('0:1')).toBe('off');
  sel.cycleLine(0, 1); expect(get(sel.state)('0:1')).toBe('on');
});

test('set cycle drives every channel in the set together', () => {
  sel.cycleSet(2);
  for (let ch = 0; ch < 8; ch++) expect(get(sel.state)(`2:${ch}`)).toBe('fade');
});

test('mixed set cycles to uniform on first', () => {
  sel.cycleLine(1, 0);                       // set_1 now mixed (fade, on)
  sel.cycleSet(1);
  expect(get(sel.state)('1:0')).toBe('on');
  expect(get(sel.state)('1:1')).toBe('on');
});

test('channel cycle applies across all sets, including collapsed', () => {
  sel.cycleChannel(1);
  expect(get(sel.state)('0:1')).toBe('fade');
  expect(get(sel.state)('1:1')).toBe('fade');
  expect(get(sel.state)('2:1')).toBe('fade');
  expect(get(sel.state)('0:0')).toBe('on');  // other channels untouched
});

test('solo isolates one set; steppers move the solo', () => {
  sel.solo(1);
  expect(get(sel.state)('1:0')).toBe('on');
  expect(get(sel.state)('0:0')).toBe('off');
  sel.step(1);                                // solo moves to set_2
  expect(get(sel.state)('2:0')).toBe('on');
  expect(get(sel.state)('1:0')).toBe('off');
});

test('allOff flags a fully-off set (legend omission + strikethrough)', () => {
  sel.cycleSet(0); sel.cycleSet(0);           // on -> fade -> off
  expect(get(sel.setsView)[0].allOff).toBe(true);
  expect(get(sel.legendEntries).some(e => e.set === 0)).toBe(false);
  expect(get(sel.legendEntries).some(e => e.set === 1)).toBe(true);
});

test('rename propagates to legend labels', () => {
  sel.rename(0, 'hammer test');
  expect(get(sel.legendEntries)[0].label).toBe('hammer test · ch_0');
});
