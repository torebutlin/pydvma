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
  sel.toggleCollapse(2);                        // collapse set_2 so the case is real
  expect(get(sel.setsView)[2].collapsed).toBe(true);
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

// ── Group shift (round-8): ‹ › move a selected line-subset as one ──────────
test('shiftLines moves a hand-picked pair one channel together', () => {
  sel.none();
  sel.cycleLine(2, 2);                         // off → on
  sel.cycleLine(2, 5);
  sel.shiftLines(1);
  expect(get(sel.state)(2, 3)).toBe('on');
  expect(get(sel.state)(2, 6)).toBe('on');
  expect(get(sel.state)(2, 2)).toBe('off');
  expect(get(sel.state)(2, 5)).toBe('off');
  expect(get(sel.state)(0, 0)).toBe('off');    // all-off set stays off
});

test('shiftLines wraps circularly within each set', () => {
  sel.none();
  sel.cycleLine(0, 1);                         // set_0 (2ch): only ch 1 on
  sel.shiftLines(1);                           // wraps to ch 0
  expect(get(sel.state)(0, 0)).toBe('on');
  expect(get(sel.state)(0, 1)).toBe('off');
  sel.shiftLines(-1);                          // and back
  expect(get(sel.state)(0, 1)).toBe('on');
  expect(get(sel.state)(0, 0)).toBe('off');
});

test('shiftLines keeps each line\'s own tri-state (fade shifts as fade)', () => {
  sel.none();
  sel.cycleLine(2, 0);                         // ch 0: on
  sel.cycleLine(2, 1); sel.cycleLine(2, 1);    // ch 1: off → on → fade
  sel.shiftLines(1);
  expect(get(sel.state)(2, 1)).toBe('on');
  expect(get(sel.state)(2, 2)).toBe('fade');
  expect(get(sel.state)(2, 0)).toBe('off');
});

test('shiftLines leaves uniform sets untouched while a subset set rotates', () => {
  sel.cycleLine(2, 0); sel.cycleLine(2, 0);    // set_2 ch 0 → off (others on)
  sel.shiftLines(1);
  expect(get(sel.state)(0, 0)).toBe('on');     // all-on sets unchanged
  expect(get(sel.state)(1, 1)).toBe('on');
  expect(get(sel.state)(2, 1)).toBe('off');    // the hole moved by one
  expect(get(sel.state)(2, 0)).toBe('on');
});

test('shiftLines rotates a live lineHighlight with its set', () => {
  sel.soloLine(2, 7);
  sel.shiftLines(1);
  expect(get(sel.lineHighlight)).toEqual({ setId: 2, ch: 0 });   // wraps
  expect(get(sel.state)(2, 0)).toBe('on');
  expect(get(sel.state)(2, 7)).toBe('off');
});

test('shiftLines: a soloed data set advances to the next set while a fit line RIDES ALONG (round-10b)', () => {
  // Tore's report: data line + fit line selected, ‹ › dropped the fit and
  // just moved to the next data line. With single-channel sets a selected
  // line IS a whole-set solo, and the old dispatch stepped sets (data only).
  const a = sel.addSet({ name: 'file_a', nChannels: 1, durationS: 1, timestamp: 'a' }); // id 3
  const fit = sel.addSet({ name: 'Modal fit', nChannels: 1, durationS: 0, timestamp: 'f', role: 'fit' });
  sel.none();
  sel.cycleLine(0, 0); sel.cycleLine(0, 1);    // set_0 (2ch): fully on = clean solo
  sel.cycleLine(fit, 0);                       // + the fit line visible
  sel.shiftLines(1);
  // Data family solo advanced set_0 → set_1; the fit line survived.
  expect(get(sel.state)(0, 0)).toBe('off');
  expect(get(sel.state)(1, 0)).toBe('on');
  expect(get(sel.state)(1, 1)).toBe('on');
  expect(get(sel.state)(fit, 0)).toBe('on');   // NOT dropped
  expect(get(sel.highlight)).toBe(1);          // highlight follows the solo
  // Wraps: two more steps go set_2 then back to set_0, fit still riding.
  sel.shiftLines(1); sel.shiftLines(1);
  expect(get(sel.state)(a, 0)).toBe('on');
  expect(get(sel.state)(fit, 0)).toBe('on');
});

test('shiftLines: data and fit families soloing in parallel cycle in LOCKSTEP', () => {
  // One fit pseudo-set per fitted data set: soloing a data set + its fit
  // set and stepping moves BOTH to their family's next set together.
  const fitA = sel.addSet({ name: 'fit A', nChannels: 1, durationS: 0, timestamp: 'fa', role: 'fit' });
  const fitB = sel.addSet({ name: 'fit B', nChannels: 1, durationS: 0, timestamp: 'fb', role: 'fit' });
  sel.none();
  sel.cycleLine(0, 0); sel.cycleLine(0, 1);    // data solo: set_0
  sel.cycleLine(fitA, 0);                      // fit solo: fit A
  sel.shiftLines(1);
  expect(get(sel.state)(1, 0)).toBe('on');     // data advanced to set_1
  expect(get(sel.state)(0, 0)).toBe('off');
  expect(get(sel.state)(fitB, 0)).toBe('on');  // fit advanced to fit B
  expect(get(sel.state)(fitA, 0)).toBe('off');
});

test('shiftLines: a clean data solo with NO fit lines advances like the old set stepping', () => {
  sel.solo(1);
  sel.shiftLines(1);
  expect(get(sel.state)(2, 0)).toBe('on');
  expect(get(sel.state)(2, 7)).toBe('on');     // whole set on
  expect(get(sel.state)(1, 0)).toBe('off');
  expect(get(sel.highlight)).toBe(2);
  sel.shiftLines(-1);                          // and back
  expect(get(sel.state)(1, 1)).toBe('on');
  expect(get(sel.state)(2, 0)).toBe('off');
});

test('shiftLines: a one-line fit set stays on its line while the data channel steps', () => {
  const fitId = sel.addSet({
    name: 'Modal fit', nChannels: 1, durationS: 0, timestamp: 'tf', role: 'fit',
  });
  sel.none();
  sel.cycleLine(2, 4);                         // the fitted data channel
  sel.cycleLine(fitId, 0);                     // its dashed recon line
  sel.shiftLines(1);
  expect(get(sel.state)(2, 5)).toBe('on');     // data channel stepped
  expect(get(sel.state)(fitId, 0)).toBe('on'); // 1-channel set wraps to itself
  expect(get(sel.state)(2, 4)).toBe('off');
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

test('only sets past AUTO_COLLAPSE_CHANNELS auto-collapse; toggleCollapse flips', () => {
  // Round-6 item 5: the threshold was raised from 4 to 16 so common
  // many-channel sets (e.g. a 10-channel orphan-TF grid) start EXPANDED.
  const big = sel.addSet({ name: 'big', nChannels: 20, durationS: 1, timestamp: 't3' }); // > 16
  let view = get(sel.setsView);
  expect(view[0].collapsed).toBe(false);      // 2-channel set — expanded
  expect(view[2].collapsed).toBe(false);      // 8-channel set — now expanded (was collapsed at >4)
  expect(view.find((v) => v.id === big)!.collapsed).toBe(true); // 20-channel set — collapsed
  sel.toggleCollapse(0); sel.toggleCollapse(big);
  view = get(sel.setsView);
  expect(view[0].collapsed).toBe(true);
  expect(view.find((v) => v.id === big)!.collapsed).toBe(false);
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

// ---- Modal-fit pseudo-set (role, dataSetsView, colours, trayFocus) — round-5 item 13 ----

test('a fit role set: appears in setsView but NOT in dataSetsView', () => {
  const fitId = sel.addSet({ name: 'Modal fit (set_0)', nChannels: 2, durationS: 0, timestamp: '', role: 'fit' });
  const all = get(sel.setsView).map(s => s.id);
  const data = get(sel.dataSetsView).map(s => s.id);
  expect(all).toContain(fitId);
  expect(data).not.toContain(fitId);
  // Data sets keep their roles + order.
  expect(get(sel.dataSetsView).every(s => s.role === 'data')).toBe(true);
  expect(get(sel.setsView).find(s => s.id === fitId)?.role).toBe('fit');
});

test('a fit set adopts supplied colours verbatim and does NOT shift later data colours', () => {
  const target0 = sel.lineColor(0, 0);
  const target1 = sel.lineColor(0, 1);
  const fitId = sel.addSet({
    name: 'Modal fit (set_0)', nChannels: 2, durationS: 0, timestamp: '',
    role: 'fit', colors: [target0!, target1!],
  });
  // Fit set mirrors the target colours.
  expect(sel.lineColor(fitId, 0)).toBe(target0);
  expect(sel.lineColor(fitId, 1)).toBe(target1);
  // A data set added AFTER the fit set keeps the palette offset it would have
  // had WITHOUT the fit set (12 data channels already: 2+2+8) — the fit set's
  // channels don't advance the palette.
  const dataId = sel.addSet({ name: 'set_3', nChannels: 1, durationS: 1, timestamp: 't3' });
  expect(sel.lineColor(dataId, 0)).toBe(LINE_PALETTE[12 % LINE_PALETTE.length]);
});

test('setSetVisible forces a whole set on/off (2-state, unlike cycleSet)', () => {
  sel.setSetVisible(2, false);
  for (let ch = 0; ch < 8; ch++) expect(get(sel.state)(2, ch)).toBe('off');
  sel.setSetVisible(2, true);
  for (let ch = 0; ch < 8; ch++) expect(get(sel.state)(2, ch)).toBe('on');
  sel.setSetVisible(99, true);   // unknown id no-op (no throw)
});

test('trayFocus ignores a fit set: a data-set solo still reads as that set', () => {
  sel.addSet({ name: 'Modal fit', nChannels: 2, durationS: 0, timestamp: '', role: 'fit' }); // id 3
  // Solo data set 1: trayFocus should read 1 even though the fit set is 'on'.
  sel.solo(1);
  expect(get(sel.trayFocus)).toBe(1);
  // Showing every set → 'all' (the fit set being on must not make it read a solo).
  sel.all();
  expect(get(sel.trayFocus)).toBe('all');
});
