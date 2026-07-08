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

test('cycleSet from a mixed set: mixed → on → fade → off → on', () => {
  sel.cycleLine(1, 0);                       // set_1 mixed: (fade, on)
  const setState = () => [get(sel.state)(1, 0), get(sel.state)(1, 1)];
  sel.cycleSet(1); expect(setState()).toEqual(['on', 'on']);     // mixed → on
  sel.cycleSet(1); expect(setState()).toEqual(['fade', 'fade']); // on → fade
  sel.cycleSet(1); expect(setState()).toEqual(['off', 'off']);   // fade → off
  sel.cycleSet(1); expect(setState()).toEqual(['on', 'on']);     // off → on (wrap)
});

test('cycleSet with an unknown id is a no-op', () => {
  sel.cycleSet(99);
  expect(get(sel.state)(0, 0)).toBe('on');
  expect(get(sel.state)(1, 0)).toBe('on');
});

test('setsView.allFade: true only when every line is uniformly fade', () => {
  // set_0 (2ch): all on → neither flag.
  expect(get(sel.setsView)[0].allFade).toBe(false);
  expect(get(sel.setsView)[0].allOff).toBe(false);
  // Cycle the whole set once: on → fade → allFade true, allOff false.
  sel.cycleSet(0);
  expect(get(sel.setsView)[0].allFade).toBe(true);
  expect(get(sel.setsView)[0].allOff).toBe(false);
  // Another whole-set cycle: fade → off → allOff true, allFade false.
  sel.cycleSet(0);
  expect(get(sel.setsView)[0].allFade).toBe(false);
  expect(get(sel.setsView)[0].allOff).toBe(true);
});

test('setsView.allFade is false for a mixed (part-fade) set', () => {
  sel.cycleSet(0);                           // both lines fade
  sel.cycleLine(0, 0);                       // 0:0 fade → off → mixed (off, fade)
  const v = get(sel.setsView)[0];
  expect(v.allFade).toBe(false);
  expect(v.allOff).toBe(false);
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

// ── Line-level Solo / step (round-5 item 3) ────────────────────────────────
test('soloLine isolates one line across all sets; others go off', () => {
  sel.soloLine(2, 3);                          // set_2, channel 3
  expect(get(sel.state)(2, 3)).toBe('on');
  expect(get(sel.state)(2, 0)).toBe('off');    // sibling channel off
  expect(get(sel.state)(0, 0)).toBe('off');    // other set off
  expect(get(sel.state)(1, 0)).toBe('off');
  expect(get(sel.lineHighlight)).toEqual({ setId: 2, ch: 3 });
  expect(get(sel.highlight)).toBe(2);          // owning set becomes highlighted
});

test('soloLine: unknown set or out-of-range channel is a no-op', () => {
  sel.soloLine(99, 0);
  expect(get(sel.lineHighlight)).toBeNull();
  sel.soloLine(0, 5);                          // set_0 has only 2 channels
  expect(get(sel.lineHighlight)).toBeNull();
});

test('stepLine walks every (set,ch) line in order and wraps', () => {
  // Flattened order: (0,0)(0,1)(1,0)(1,1)(2,0..7) = 12 lines.
  sel.stepLine(1);                             // first › → line 0 = (0,0)
  expect(get(sel.lineHighlight)).toEqual({ setId: 0, ch: 0 });
  sel.stepLine(1);                             // → (0,1)
  expect(get(sel.lineHighlight)).toEqual({ setId: 0, ch: 1 });
  sel.stepLine(1);                             // → (1,0)
  expect(get(sel.lineHighlight)).toEqual({ setId: 1, ch: 0 });
  expect(get(sel.state)(1, 0)).toBe('on');     // stepping solos the line
  expect(get(sel.state)(0, 1)).toBe('off');
  sel.stepLine(-1);                            // back to (0,1)
  expect(get(sel.lineHighlight)).toEqual({ setId: 0, ch: 1 });
});

test('stepLine(-1) from no highlight wraps to the last line', () => {
  sel.stepLine(-1);
  expect(get(sel.lineHighlight)).toEqual({ setId: 2, ch: 7 });   // last (set_2, ch 7)
});

test('removeSet clears a line-highlight that pointed at the removed set', () => {
  sel.soloLine(1, 0);
  expect(get(sel.lineHighlight)).toEqual({ setId: 1, ch: 0 });
  sel.removeSet(1);
  expect(get(sel.lineHighlight)).toBeNull();
});

test('allOff: legendEntries (plot list) omits the off set; legendRows (legend UI) keeps it', () => {
  sel.cycleSet(0); sel.cycleSet(0);           // on -> fade -> off
  expect(get(sel.setsView)[0].allOff).toBe(true);
  // Plot-facing list drops the off set (nothing to DRAW)...
  expect(get(sel.legendEntries).some(e => e.setId === 0)).toBe(false);
  expect(get(sel.legendEntries).some(e => e.setId === 1)).toBe(true);
  // ...but the legend UI keeps every line so an off line can be re-enabled.
  const rows0 = get(sel.legendRows).filter(e => e.setId === 0);
  expect(rows0).toHaveLength(2);
  expect(rows0.every(e => e.state === 'off')).toBe(true);
});

test('legendRows keeps an individually-off line (struck-through, re-enableable)', () => {
  sel.cycleLine(0, 1); sel.cycleLine(0, 1);   // 0:1 on -> fade -> off
  // Dropped from the plot list...
  expect(get(sel.legendEntries).some(e => e.setId === 0 && e.ch === 1)).toBe(false);
  // ...but still listed in the legend rows, carrying its 'off' state.
  const row = get(sel.legendRows).find(e => e.setId === 0 && e.ch === 1);
  expect(row?.state).toBe('off');
  // The sibling on-line is present and 'on'.
  expect(get(sel.legendRows).find(e => e.setId === 0 && e.ch === 0)?.state).toBe('on');
});

test('legendRows carries labels + colours like legendEntries', () => {
  sel.rename(0, 'hammer test');
  sel.renameChannel(0, 1, 'accel');
  const row = get(sel.legendRows).find(e => e.setId === 0 && e.ch === 1);
  expect(row?.label).toBe('hammer test · accel');
  expect(row?.color).toBe(get(sel.legendEntries).find(e => e.setId === 0 && e.ch === 1)?.color);
});

test('rename propagates to legend labels', () => {
  sel.rename(0, 'hammer test');
  expect(get(sel.legendEntries)[0].label).toBe('hammer test · ch_0');
});

test('channelLabel defaults to ch_<n>; renameChannel sets a custom label', () => {
  const label = get(sel.channelLabel);
  expect(label(0, 0)).toBe('ch_0');
  expect(label(0, 1)).toBe('ch_1');
  sel.renameChannel(0, 0, 'hammer');
  expect(get(sel.channelLabel)(0, 0)).toBe('hammer');
  expect(get(sel.channelLabel)(0, 1)).toBe('ch_1');   // sibling untouched
});

test('renameChannel with a blank/whitespace label resets to the default', () => {
  sel.renameChannel(0, 0, 'hammer');
  expect(get(sel.channelLabel)(0, 0)).toBe('hammer');
  sel.renameChannel(0, 0, '   ');                      // whitespace → reset
  expect(get(sel.channelLabel)(0, 0)).toBe('ch_0');
  sel.renameChannel(0, 0, 'accel');
  sel.renameChannel(0, 0, '');                         // empty → reset
  expect(get(sel.channelLabel)(0, 0)).toBe('ch_0');
});

test('channel labels are per-set independent', () => {
  sel.renameChannel(0, 0, 'hammer');
  expect(get(sel.channelLabel)(0, 0)).toBe('hammer');
  expect(get(sel.channelLabel)(1, 0)).toBe('ch_0');   // set_1 ch_0 untouched
  sel.renameChannel(1, 0, 'accel');
  expect(get(sel.channelLabel)(0, 0)).toBe('hammer'); // set_0 still hammer
  expect(get(sel.channelLabel)(1, 0)).toBe('accel');
});

test('renameChannel with an unknown set id is a no-op', () => {
  sel.renameChannel(99, 0, 'ghost');
  expect(get(sel.channelLabel)(99, 0)).toBe('ch_0');  // default for unknown
});

test('custom channel label flows into legendEntries', () => {
  sel.renameChannel(0, 1, 'accel');
  const entry = get(sel.legendEntries).find(e => e.setId === 0 && e.ch === 1);
  expect(entry?.label).toBe('set_0 · accel');
  // the un-renamed sibling keeps the default channel label
  const sib = get(sel.legendEntries).find(e => e.setId === 0 && e.ch === 0);
  expect(sib?.label).toBe('set_0 · ch_0');
});

test('renameChannel is trimmed (leading/trailing whitespace stripped)', () => {
  sel.renameChannel(0, 0, '  hammer  ');
  expect(get(sel.channelLabel)(0, 0)).toBe('hammer');
});

test('removeSet drops that set custom channel labels', () => {
  sel.renameChannel(1, 0, 'accel');
  expect(get(sel.channelLabel)(1, 0)).toBe('accel');
  sel.removeSet(1);
  // a fresh set that happens to reuse... ids are never reused, but the
  // stored label must not leak — a new set at a *different* id is default.
  const id = sel.addSet({ name: 'reborn', nChannels: 2, durationS: 1, timestamp: 't9' });
  expect(get(sel.channelLabel)(id, 0)).toBe('ch_0');
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
