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

// ── Transient (live-drag) commits (round-6 item 6) ─────────────────────────
test('a transient gesture with many live frames records exactly ONE history entry', () => {
  const vs = createViewState();
  vs.activate('tf');
  const h0 = get(vs.current).history.length;
  vs.beginTransient('tf');
  for (let f = 0; f < 60; f++) vs.setRangeLive('tf', { x: [f, 500 - f], y: null });
  // Live frames update the range but push NO history.
  expect(get(vs.current).range.x).toEqual([59, 441]);
  expect(get(vs.current).history.length).toBe(h0);
  vs.commitTransient('tf', { x: [60, 440], y: null });
  expect(get(vs.current).range.x).toEqual([60, 440]);
  expect(get(vs.current).history.length).toBe(h0 + 1);   // exactly one entry for the whole drag
});

test('undo after a transient gesture returns to the PRE-drag range (one step)', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [0, 1000], y: null });          // committed starting window
  vs.beginTransient('tf');
  vs.setRangeLive('tf', { x: [100, 200], y: null });
  vs.setRangeLive('tf', { x: [300, 400], y: null });
  vs.commitTransient('tf', { x: [300, 400], y: null });
  expect(get(vs.current).range.x).toEqual([300, 400]);
  vs.back('tf');
  expect(get(vs.current).range.x).toEqual([0, 1000]);    // straight back past all live frames
});

test('cancelTransient reverts the live preview without touching history', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [0, 800], y: null });
  const h0 = get(vs.current).history.length;
  vs.beginTransient('tf');
  vs.setRangeLive('tf', { x: [50, 90], y: null });
  vs.cancelTransient('tf');
  expect(get(vs.current).range.x).toEqual([0, 800]);     // reverted
  expect(get(vs.current).history.length).toBe(h0);       // no new entry
});

test('commitTransient with no open gesture acts as a plain setRange (one entry)', () => {
  const vs = createViewState();
  vs.activate('tf');
  const h0 = get(vs.current).history.length;
  vs.commitTransient('tf', { x: [10, 20], y: null });    // e.g. a numeric-field edit
  expect(get(vs.current).range.x).toEqual([10, 20]);
  expect(get(vs.current).history.length).toBe(h0 + 1);
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

// ---- axis scale toggles (R3) ----

test('xScale/yScale default lin/log; setters scope to the active view', () => {
  const vs = createViewState();
  // Defaults: x linear, y log (magnitude stays dB by default).
  expect(get(vs.current).xScale).toBe('lin');
  expect(get(vs.current).yScale).toBe('log');

  vs.activate('frequency');
  vs.setXScale('log');
  vs.setYScale('lin');
  expect(get(vs.current).xScale).toBe('log');
  expect(get(vs.current).yScale).toBe('lin');

  // A different view is untouched (per-view, not global).
  vs.activate('tf');
  expect(get(vs.current).xScale).toBe('lin');
  expect(get(vs.current).yScale).toBe('log');
});

test('restore merges xScale/yScale defaults over a stale snapshot lacking them', () => {
  const vs = createViewState();
  vs.activate('frequency');
  vs.setXScale('log');
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  // Simulate an OLD snapshot from before R3: strip the new fields.
  for (const id of ['time', 'frequency', 'tf', 'sono']) {
    delete snap.views[id].xScale;
    delete snap.views[id].yScale;
  }
  const vs2 = createViewState();
  vs2.restore(snap);
  vs2.activate('frequency');
  // Missing fields fall back to the fresh() defaults, not undefined.
  expect(get(vs2.current).xScale).toBe('lin');
  expect(get(vs2.current).yScale).toBe('log');
});

test('xScale/yScale round-trip through serialize/restore', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setXScale('log');
  vs.setYScale('lin');
  const vs2 = createViewState();
  vs2.restore(JSON.parse(JSON.stringify(vs.serialize())));
  vs2.activate('tf');
  expect(get(vs2.current).xScale).toBe('log');
  expect(get(vs2.current).yScale).toBe('lin');
});

test('sono scales default lin freq / dB colour; setters scope to the sono view; no history', () => {
  const vs = createViewState();
  // Defaults reproduce today's behaviour: linear frequency y, dB heat colour.
  expect(get(vs.current).sonoFreqScale).toBe('lin');   // active is 'time' but the field exists on every slice
  expect(get(vs.current).sonoColour).toBe('db');

  vs.activate('sono');
  const before = get(vs.current).history.length;
  vs.setSonoFreqScale('log');
  vs.setSonoColour('lin');
  expect(get(vs.current).sonoFreqScale).toBe('log');
  expect(get(vs.current).sonoColour).toBe('lin');
  // Display modes, not navigable — they must NOT push zoom-history entries.
  expect(get(vs.current).history.length).toBe(before);

  // Scoped to 'sono' regardless of which view is active when called.
  vs.activate('frequency');
  vs.setSonoFreqScale('lin');
  vs.setSonoColour('db');
  vs.activate('sono');
  expect(get(vs.current).sonoFreqScale).toBe('lin');
  expect(get(vs.current).sonoColour).toBe('db');
  // The frequency slice's own sono fields stayed at defaults (never written).
  vs.activate('frequency');
  expect(get(vs.current).sonoFreqScale).toBe('lin');
  expect(get(vs.current).sonoColour).toBe('db');
});

test('sono scales round-trip through serialize/restore and default over a stale snapshot', () => {
  const vs = createViewState();
  vs.activate('sono');
  vs.setSonoFreqScale('log');
  vs.setSonoColour('lin');
  const vs2 = createViewState();
  vs2.restore(JSON.parse(JSON.stringify(vs.serialize())));
  vs2.activate('sono');
  expect(get(vs2.current).sonoFreqScale).toBe('log');
  expect(get(vs2.current).sonoColour).toBe('lin');

  // An OLD snapshot lacking the fields falls back to the fresh() defaults
  // (linear freq / dB colour) — never undefined, never log-y on load.
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  for (const id of ['time', 'frequency', 'tf', 'sono']) {
    delete snap.views[id].sonoFreqScale;
    delete snap.views[id].sonoColour;
  }
  const vs3 = createViewState();
  vs3.restore(snap);
  vs3.activate('sono');
  expect(get(vs3.current).sonoFreqScale).toBe('lin');
  expect(get(vs3.current).sonoColour).toBe('db');
});

// ---- round-5 axis-nav: Nyquist real/imag, Bode phase, coherence ----

test('aux-range defaults: nyquist auto, phase ±180 lock, coherence fixed', () => {
  const vs = createViewState();
  vs.activate('tf');
  const s = get(vs.current);
  expect(s.nyquistRange).toEqual({ x: null, y: null });
  expect(s.phaseRange).toEqual({ x: null, y: [-180, 180] });
  expect(s.coherenceAuto).toBe(false);
});

test('setNyquistRange records history and does NOT touch the primary range', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [100, 300], y: [-40, 10] });   // freq window + mag y
  vs.setNyquistRange({ x: [-2, 6], y: [-5, 5] });
  const s = get(vs.current);
  expect(s.nyquistRange).toEqual({ x: [-2, 6], y: [-5, 5] });
  expect(s.range).toEqual({ x: [100, 300], y: [-40, 10] });   // untouched
  expect(get(vs.sharedFreqRange)).toEqual([100, 300]);        // freq window intact
  // Undo reverses the Nyquist zoom back to auto, leaving the freq window put.
  vs.back('tf');
  expect(get(vs.current).nyquistRange).toEqual({ x: null, y: null });
  expect(get(vs.current).range.x).toEqual([100, 300]);
  vs.forward('tf');
  expect(get(vs.current).nyquistRange).toEqual({ x: [-2, 6], y: [-5, 5] });
});

test('setBodePhaseRange moves shared x + phase y in ONE undo step, keeping magnitude y', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [0, 500], y: [-60, 40] });     // mag pane range
  const h0 = get(vs.current).history.length;
  vs.setBodePhaseRange([80, 120], [-90, 90]);            // a phase-pane box-zoom
  const s = get(vs.current);
  expect(s.range).toEqual({ x: [80, 120], y: [-60, 40] });   // shared x moved, mag y kept
  expect(s.phaseRange).toEqual({ x: null, y: [-90, 90] });   // phase y set
  expect(get(vs.current).history.length).toBe(h0 + 1);       // exactly one entry
  // One undo reverts BOTH the shared x and the phase y together.
  vs.back('tf');
  expect(get(vs.current).range.x).toEqual([0, 500]);
  expect(get(vs.current).phaseRange.y).toEqual([-180, 180]);
});

test('setPhaseRange toggles the phase lock without disturbing the primary range', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [0, 500], y: [-60, 40] });
  vs.setPhaseRange({ x: null, y: null });               // auto-fit phase
  expect(get(vs.current).phaseRange).toEqual({ x: null, y: null });
  expect(get(vs.current).range).toEqual({ x: [0, 500], y: [-60, 40] });
  vs.setPhaseRange({ x: null, y: [-180, 180] });         // re-lock
  expect(get(vs.current).phaseRange.y).toEqual([-180, 180]);
});

test('setCoherenceAuto flips the flag WITHOUT recording history', () => {
  const vs = createViewState();
  vs.activate('tf');
  const h0 = get(vs.current).history.length;
  vs.setCoherenceAuto(true);
  expect(get(vs.current).coherenceAuto).toBe(true);
  expect(get(vs.current).history.length).toBe(h0);      // display mode, not navigation
  vs.setCoherenceAuto(false);
  expect(get(vs.current).coherenceAuto).toBe(false);
});

test('aux ranges + coherenceAuto round-trip through serialize/restore', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setNyquistRange({ x: [-1, 1], y: [-2, 2] });
  vs.setPhaseRange({ x: null, y: null });
  vs.setCoherenceAuto(true);
  const vs2 = createViewState();
  vs2.restore(JSON.parse(JSON.stringify(vs.serialize())));
  vs2.activate('tf');
  const s = get(vs2.current);
  expect(s.nyquistRange).toEqual({ x: [-1, 1], y: [-2, 2] });
  expect(s.phaseRange).toEqual({ x: null, y: null });
  expect(s.coherenceAuto).toBe(true);
});

test('restore coerces a pre-round-5 Range[] history into snapshots (undo still works)', () => {
  const vs = createViewState();
  vs.activate('tf');
  // Hand-craft an OLD-schema snapshot: history entries are bare Range objects.
  const oldSnap = {
    active: 'tf',
    views: {
      time: { range: { x: null, y: null }, history: [], future: [] },
      frequency: { range: { x: null, y: null }, history: [], future: [] },
      tf: {
        range: { x: [50, 150], y: [-30, 10] },
        history: [{ x: null, y: null }],   // pre-round-5 shape: a bare Range
        future: [],
      },
      sono: { range: { x: null, y: null }, history: [], future: [] },
    },
  };
  vs.restore(oldSnap);
  vs.activate('tf');
  expect(get(vs.current).range.x).toEqual([50, 150]);
  vs.back('tf');   // the coerced entry must restore its wrapped range
  expect(get(vs.current).range).toEqual({ x: null, y: null });
});

// ---- legend slice: compact dot-grid flag (post-release "many lines" legend) ----

test('legend.compact defaults false; setLegend persists it per view without touching placement', () => {
  const vs = createViewState();
  expect(get(vs.current).legend.compact).toBe(false);
  vs.activate('frequency');
  vs.setLegend('frequency', { ...get(vs.current).legend, compact: true });
  const l = get(vs.current).legend;
  expect(l.compact).toBe(true);
  // Placement/visibility fields ride along unchanged (se default, R7b).
  expect(l).toMatchObject({ visible: true, x: 0.98, y: 0.98, preset: 'se' });
  // Per-view, not global: another view stays full.
  vs.activate('time');
  expect(get(vs.current).legend.compact).toBe(false);
});

test('legend.compact round-trips through serialize/restore; stale snapshots default false', () => {
  const vs = createViewState();
  vs.setLegend('time', { visible: true, x: 0.7, y: 0.3, preset: null, compact: true });
  const vs2 = createViewState();
  vs2.restore(JSON.parse(JSON.stringify(vs.serialize())));
  expect(get(vs2.current).legend)
    .toEqual({ visible: true, x: 0.7, y: 0.3, preset: null, compact: true });

  // An OLD snapshot whose legend predates `compact` restores with the
  // default false while KEEPING its saved placement (nested merge —
  // the top-level fresh() merge alone would leave compact undefined).
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  for (const id of ['time', 'frequency', 'tf', 'sono']) delete snap.views[id].legend.compact;
  const vs3 = createViewState();
  vs3.restore(snap);
  const l = get(vs3.current).legend;
  expect(l.compact).toBe(false);
  expect(l).toMatchObject({ x: 0.7, y: 0.3, preset: null });  // placement preserved
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

// ── Frequency navigator (dev/plans/2026-07-11-freq-navigator-design.md) ────
test('freqScope: defaults null; set/clear pushes NO history (not undoable)', () => {
  const vs = createViewState();
  expect(get(vs.freqScope)).toBeNull();
  vs.setFreqScope([100, 500]);
  expect(get(vs.freqScope)).toEqual([100, 500]);
  vs.activate('tf');
  expect(get(vs.current).history.length).toBe(0);
  vs.setFreqScope(null);
  expect(get(vs.freqScope)).toBeNull();
});

test('navigator override: per-view, defaults null (auto)', () => {
  const vs = createViewState();
  vs.activate('tf');
  expect(get(vs.current).navigator).toBeNull();
  vs.setNavigator('tf', true);
  expect(get(vs.current).navigator).toBe(true);
  vs.activate('frequency');
  expect(get(vs.current).navigator).toBeNull();   // per-view, tf untouched elsewhere
});

test('freqScope + navigator survive a serialize/restore JSON round-trip', () => {
  const vs = createViewState();
  vs.setFreqScope([50, 2000]);
  vs.setNavigator('tf', true);
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  const vs2 = createViewState();
  vs2.restore(snap);
  expect(get(vs2.freqScope)).toEqual([50, 2000]);
  vs2.activate('tf');
  expect(get(vs2.current).navigator).toBe(true);
});

test('legacy snapshot (no freqScope / navigator fields) restores to defaults', () => {
  const vs = createViewState();
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  delete snap.freqScope;
  for (const id of ['time', 'frequency', 'tf', 'sono']) delete snap.views[id].navigator;
  const vs2 = createViewState();
  vs2.setFreqScope([1, 2]);          // must be OVERWRITTEN back to null by restore
  vs2.setNavigator('tf', false);
  vs2.restore(snap);
  expect(get(vs2.freqScope)).toBeNull();
  vs2.activate('tf');
  expect(get(vs2.current).navigator).toBeNull();
});

test('restore rejects a malformed freqScope (inverted / wrong shape → null)', () => {
  for (const bad of [[500, 100], [1, 1], ['a', 'b'], [1], 42, {}]) {
    const vs = createViewState();
    const snap = JSON.parse(JSON.stringify(vs.serialize()));
    snap.freqScope = bad;
    const vs2 = createViewState();
    vs2.restore(snap);
    expect(get(vs2.freqScope)).toBeNull();
  }
});
