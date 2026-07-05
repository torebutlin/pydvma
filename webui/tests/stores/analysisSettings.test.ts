import { get } from 'svelte/store';
import { expect, test, beforeEach } from 'vitest';
import { createSelection } from '../../src/lib/stores/selection';
import { createAnalysisSettings, defaults } from '../../src/lib/stores/analysisSettings';

let sel: ReturnType<typeof createSelection>;
let settings: ReturnType<typeof createAnalysisSettings>;

beforeEach(() => {
  sel = createSelection();
  settings = createAnalysisSettings(sel);
});

test('defaults() match the cards prior local defaults; fresh object each call', () => {
  const d = defaults();
  expect(d.freq).toEqual({ window: 'hann', mode: 'fft', nFrames: 10 });
  expect(d.tf).toEqual({ chIn: 0, window: 'hann', averaging: 'within', nFrames: 10 });
  expect(d.sono).toEqual({ nFft: 512, dynRangeDb: 60 });
  expect(defaults()).not.toBe(d);         // not aliased
  expect(defaults().freq).not.toBe(d.freq);
});

test('a set appearing in the tray is seeded with defaults; removal prunes it', () => {
  const id = sel.addSet({ name: 's0', nChannels: 2, durationS: 1, timestamp: 't0' });
  expect(get(settings.map)[id]).toEqual(defaults());
  sel.removeSet(id);
  expect(id in get(settings.map)).toBe(false);   // pruned, no leak
});

test('patch to one set leaves others untouched; patch-all writes every set', () => {
  const a = sel.addSet({ name: 'a', nChannels: 1, durationS: 1, timestamp: 't0' });
  const b = sel.addSet({ name: 'b', nChannels: 1, durationS: 1, timestamp: 't1' });

  settings.patch(a, 'freq', { window: 'flattop' });
  expect(settings.get(a, 'freq').window).toBe('flattop');
  expect(settings.get(b, 'freq').window).toBe('hann');   // untouched

  settings.patch('all', 'freq', { mode: 'psd' });
  expect(settings.get(a, 'freq').mode).toBe('psd');
  expect(settings.get(b, 'freq').mode).toBe('psd');
  // patch-all preserves the per-set field it didn't touch
  expect(settings.get(a, 'freq').window).toBe('flattop');
  expect(settings.get(b, 'freq').window).toBe('hann');
});

test('patch to an unknown set id is a no-op', () => {
  const a = sel.addSet({ name: 'a', nChannels: 1, durationS: 1, timestamp: 't0' });
  settings.patch(999, 'sono', { nFft: 1024 });
  expect(settings.get(a, 'sono').nFft).toBe(512);
  expect(999 in get(settings.map)).toBe(false);
});

test('isMixed: false with <2 sets; true when sets disagree; cleared by patch-all', () => {
  const a = sel.addSet({ name: 'a', nChannels: 1, durationS: 1, timestamp: 't0' });
  expect(settings.isMixed('freq', 'window')).toBe(false);     // single set

  const b = sel.addSet({ name: 'b', nChannels: 1, durationS: 1, timestamp: 't1' });
  expect(settings.isMixed('freq', 'window')).toBe(false);     // both default → agree

  settings.patch(a, 'freq', { window: 'flattop' });
  expect(settings.isMixed('freq', 'window')).toBe(true);      // now disagree
  expect(settings.isMixed('freq', 'mode')).toBe(false);       // mode still agrees

  settings.patch('all', 'freq', { window: 'hamming' });
  expect(settings.isMixed('freq', 'window')).toBe(false);     // patch-all made them agree
});

test('settingFor: set id returns its own; all returns first-set representative', () => {
  const a = sel.addSet({ name: 'a', nChannels: 1, durationS: 1, timestamp: 't0' });
  const b = sel.addSet({ name: 'b', nChannels: 1, durationS: 1, timestamp: 't1' });
  settings.patch(a, 'tf', { chIn: 3 });
  settings.patch(b, 'tf', { chIn: 5 });
  expect(settings.settingFor(b, 'tf').chIn).toBe(5);
  expect(settings.settingFor('all', 'tf').chIn).toBe(3);      // first set represents
});

test('settingFor with no sets returns defaults', () => {
  expect(settings.settingFor('all', 'sono')).toEqual(defaults().sono);
});

test('analysisTarget defaults to all', () => {
  expect(get(settings.analysisTarget)).toBe('all');
});

test('a single loaded set reads as target "all" (no solo distinction)', () => {
  sel.addSet({ name: 'only', nChannels: 2, durationS: 1, timestamp: 't0' });
  expect(get(settings.analysisTarget)).toBe('all');   // not the lone set id
});

test('setTarget(setId) solos in the tray; target follows; no loop', () => {
  const a = sel.addSet({ name: 'a', nChannels: 2, durationS: 1, timestamp: 't0' });
  const b = sel.addSet({ name: 'b', nChannels: 2, durationS: 1, timestamp: 't1' });

  settings.setTarget(b);
  expect(get(settings.analysisTarget)).toBe(b);
  // Tray was driven to solo b: b on, a off.
  expect(get(sel.state)(b, 0)).toBe('on');
  expect(get(sel.state)(a, 0)).toBe('off');
});

test('setTarget(all) shows every set; target reads all', () => {
  const a = sel.addSet({ name: 'a', nChannels: 2, durationS: 1, timestamp: 't0' });
  const b = sel.addSet({ name: 'b', nChannels: 2, durationS: 1, timestamp: 't1' });
  settings.setTarget(b);
  settings.setTarget('all');
  expect(get(settings.analysisTarget)).toBe('all');
  expect(get(sel.state)(a, 0)).toBe('on');
  expect(get(sel.state)(b, 0)).toBe('on');
});

test('tray → target: soloing a set in the tray moves the target to it', () => {
  const a = sel.addSet({ name: 'a', nChannels: 2, durationS: 1, timestamp: 't0' });
  const b = sel.addSet({ name: 'b', nChannels: 2, durationS: 1, timestamp: 't1' });
  // Drive the tray directly (as a user click on the tray would), NOT via setTarget.
  sel.solo(a);
  expect(get(settings.analysisTarget)).toBe(a);
  sel.all();
  expect(get(settings.analysisTarget)).toBe('all');
});

test('no ping-pong: setTarget then a tray echo does not flip the target back', () => {
  const a = sel.addSet({ name: 'a', nChannels: 2, durationS: 1, timestamp: 't0' });
  sel.addSet({ name: 'b', nChannels: 2, durationS: 1, timestamp: 't1' });

  let flips = 0;
  const unsub = settings.analysisTarget.subscribe(() => { flips++; });
  flips = 0;                       // discount the sync initial callback
  settings.setTarget(a);
  unsub();
  // Exactly one settle to `a` — the solo echo through trayFocus must not
  // add a second emission back to 'all' or re-emit `a`.
  expect(flips).toBe(1);
  expect(get(settings.analysisTarget)).toBe(a);
});
