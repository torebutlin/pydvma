import { derived, writable, get } from 'svelte/store';

/** The four plot views the GUI can display. */
export type ViewId = 'time' | 'frequency' | 'tf' | 'sono';
/** TF-view plot family (magnitude, phase, bode, real, imag, Nyquist). */
export type TfPlotType = 'mag' | 'phase' | 'bode' | 'real' | 'imag' | 'nyquist';
/** Axis ranges; `null` means "auto-fit to data" on that axis. */
export interface Range { x: [number, number] | null; y: [number, number] | null; }

/** Axis scale: linear or log10. See `ViewSlice.xScale`/`yScale`. */
export type AxisScale = 'lin' | 'log';

/**
 * A navigable-state snapshot pushed onto the undo/redo stacks. The tf view
 * is special: its Nyquist projection (Real/Imag axes) and its Bode phase
 * pane each carry their OWN range, distinct from the primary `range` (which
 * on the tf view is the frequency window + the magnitude y). Capturing all
 * three in one snapshot means a single undo step reverses whatever the user
 * last did — a brush drag of the freq window, a Nyquist real/imag zoom, or a
 * Bode-phase-pane box-zoom (which moves shared x AND phase y at once) — with
 * exactly one history entry. On every other view `nyquistRange`/`phaseRange`
 * stay at their `{x:null,y:null}` defaults, so this is inert there.
 */
export interface RangeSnapshot { range: Range; nyquistRange: Range; phaseRange: Range; }

/**
 * Per-view UI state slice: current axis range, zoom history (undo /
 * redo stacks), TF plot type (used by the tf view only; ignored
 * elsewhere), coherence overlay flag, legend placement, and the axis
 * scale toggles (R3).
 *
 * `xScale` = the FREQUENCY x-axis: `'log'` renders decade log10 on the
 * frequency/tf views (the time view's x is time and stays linear
 * regardless). `yScale` = the MAGNITUDE representation, a model change
 * not just an axis scale: `'log'` (default) → dB (`20·log10|H|`,
 * `10·log10` PSD); `'lin'` → linear `|H|` / raw PSD. Applies to the
 * magnitude views (FFT mag / TF mag / PSD); ignored on
 * phase/real/imag/Nyquist and the time view.
 *
 * The tf view carries two AUXILIARY ranges (round-5 axis-nav pass):
 * - `nyquistRange` — the Real/Imag display window of the Nyquist locus.
 *   On Nyquist the toolbar's x/y controls mean REAL/IMAG and act on THIS,
 *   NOT on `range` (whose `.x` remains the FREQUENCY window that the freq
 *   brush, Calc, Fit and the windowed locus all share). Null axis ⇒
 *   auto-fit the windowed locus.
 * - `phaseRange` — the Bode phase pane's own y-axis (x is shared with the
 *   magnitude pane via `range.x`, so only `.y` is meaningful). Default
 *   `[-180,180]` (the ±180° lock); null ⇒ auto-fit the phase data.
 * `coherenceAuto` toggles the coherence overlay's right axis between the
 * fixed `[0,1]` (default, `false`) and auto-fit (`true`).
 */
export interface ViewSlice {
  range: Range;
  history: RangeSnapshot[]; future: RangeSnapshot[];
  plotType: TfPlotType;              // used by tf only; ignored elsewhere
  coherence: boolean;
  legend: { visible: boolean; x: number; y: number; preset: string | null };
  xScale: AxisScale;                 // frequency axis lin↔log10 (freq/tf only)
  yScale: AxisScale;                 // magnitude dB (log, default) ↔ linear
  nyquistRange: Range;               // tf/Nyquist: Real/Imag display window
  phaseRange: Range;                 // tf/Bode: phase pane y-axis (default ±180)
  coherenceAuto: boolean;            // tf: coherence right axis auto ↔ fixed [0,1]
}

const fresh = (): ViewSlice => ({
  range: { x: null, y: null }, history: [], future: [],
  plotType: 'mag', coherence: true,
  // Default to the TOP-LEFT (nw): the zoom/nav toolbar occupies the
  // top-right, so an 'ne' default legend would sit under its buttons.
  legend: { visible: true, x: 0.02, y: 0.02, preset: 'nw' },
  // x linear; y log so magnitude renders in dB by default (unchanged
  // from the pre-R3 behaviour).
  xScale: 'lin', yScale: 'log',
  // Nyquist real/imag auto-fit; Bode phase locked to ±180°; coherence
  // right axis fixed to [0,1] — all the round-5 defaults.
  nyquistRange: { x: null, y: null },
  phaseRange: { x: null, y: [-180, 180] },
  coherenceAuto: false,
});

/** Pull the three navigable ranges of a slice into a history snapshot. */
const snapOf = (v: ViewSlice): RangeSnapshot =>
  ({ range: v.range, nyquistRange: v.nyquistRange, phaseRange: v.phaseRange });

/**
 * Coerce a serialized history/future entry to a `RangeSnapshot`. Accepts both
 * the current shape (`{range, nyquistRange, phaseRange}`) and the pre-round-5
 * shape (a bare `Range` `{x, y}`), wrapping the latter so an autosaved session
 * from before this change keeps a working undo stack. Anything else → `null`
 * (dropped).
 */
function toSnapshot(e: unknown): RangeSnapshot | null {
  if (!e || typeof e !== 'object') return null;
  const o = e as Record<string, unknown>;
  const none: Range = { x: null, y: null };
  if (o.range && typeof o.range === 'object') {
    return {
      range: o.range as Range,
      nyquistRange: (o.nyquistRange as Range) ?? none,
      phaseRange: (o.phaseRange as Range) ?? none,
    };
  }
  if ('x' in o && 'y' in o) return { range: o as unknown as Range, nyquistRange: none, phaseRange: none };
  return null;
}

/** The store object `createViewState()` returns (for component props). */
export type ViewState = ReturnType<typeof createViewState>;

const VIEW_IDS = ['time', 'frequency', 'tf', 'sono'] as const;
/** Max zoom-history entries kept per view; oldest are dropped. */
const HISTORY_CAP = 50;

/**
 * Serialisable view-state store (design spec §11): one `ViewSlice` per
 * view, an active-view pointer, per-view zoom history, and a shared
 * frequency x-range derived for the Nyquist fmin/fmax controls.
 *
 * Every method is a plain closure over the internal stores (no `this`),
 * so the returned object is safe to destructure. `current` is a derived
 * slice of whichever view is active (default `'time'`); `serialize()` /
 * `restore()` round-trip the whole state through plain JSON.
 */
export function createViewState() {
  const views = writable<Record<ViewId, ViewSlice>>({
    time: fresh(), frequency: fresh(), tf: fresh(), sono: fresh(),
  });
  const active = writable<ViewId>('time');

  const patch = (id: ViewId, fn: (v: ViewSlice) => ViewSlice) =>
    views.update(all => ({ ...all, [id]: fn(all[id]) }));

  /** Switch the active view; `current` follows it. */
  function activate(id: ViewId) { active.set(id); }

  /**
   * Commit a navigable-state change to view `id`: apply `changes` (a partial
   * of the three ranges, computed from the pre-state slice) and push a
   * snapshot of the PREVIOUS state onto the history stack (capped at 50
   * entries; oldest dropped), clearing the redo (`future`) stack. This is the
   * single write path for every range mutation — primary `range`, Nyquist
   * `nyquistRange`, Bode `phaseRange`, or a combined Bode gesture — so each
   * user action lands as exactly ONE undo step. Continuous gestures (drag-pan,
   * wheel zoom, brush drag) coalesce into one commit per gesture upstream (the
   * plot interaction layer's job), not here.
   */
  function commit(id: ViewId, changes: (v: ViewSlice) => Partial<RangeSnapshot>) {
    patch(id, v => ({
      ...v, history: [...v.history, snapOf(v)].slice(-HISTORY_CAP), future: [], ...changes(v),
    }));
  }

  /** Set view `id`'s primary axis range (frequency window + magnitude y). */
  function setRange(id: ViewId, range: Range) { commit(id, () => ({ range })); }

  /**
   * Set the tf view's Nyquist Real/Imag display window (round-5 item 4). Only
   * meaningful when the tf plotType is `'nyquist'`; recorded in history so the
   * toolbar's undo/redo covers real/imag zooms. Null axis ⇒ auto-fit the
   * windowed locus.
   */
  function setNyquistRange(range: Range) { commit('tf', () => ({ nyquistRange: range })); }

  /**
   * Set the tf view's Bode phase-pane y-axis (round-5 item 5). `x` is ignored
   * (the phase pane shares the magnitude pane's frequency x via `range.x`);
   * only `.y` matters — `[-180,180]` locks, `null` auto-fits. Recorded in
   * history.
   */
  function setPhaseRange(range: Range) { commit('tf', () => ({ phaseRange: range })); }

  /**
   * Commit a Bode PHASE-PANE gesture (box-zoom / pan) as ONE undo step: the
   * shared frequency x moves BOTH panes (written to `range.x`, magnitude y
   * preserved) while `y` targets only the phase pane (`phaseRange.y`). Routed
   * here from the phase pane's `PlotSurface` so a phase-pane drag never
   * clobbers the magnitude pane's y (round-5 item 5 gesture-routing fix).
   */
  function setBodePhaseRange(x: Range['x'], y: Range['y']) {
    commit('tf', v => ({ range: { x, y: v.range.y }, phaseRange: { x: null, y } }));
  }

  /**
   * Step back through view `id`'s zoom history (no-op when empty). Restores the
   * WHOLE snapshot (primary + Nyquist + phase ranges), so undo reverses
   * whatever the last committed change touched. The initial all-null snapshot
   * is a valid history entry — the guard is on `undefined` (empty stack), not
   * on null axis ranges.
   */
  function back(id: ViewId) {
    patch(id, v => {
      const prev = v.history.at(-1); if (prev === undefined) return v;
      return { ...v, history: v.history.slice(0, -1), future: [snapOf(v), ...v.future], ...prev };
    });
  }

  /** Redo one change undone by `back` (no-op when the future stack is empty). */
  function forward(id: ViewId) {
    patch(id, v => {
      const next = v.future[0]; if (next === undefined) return v;
      return { ...v, future: v.future.slice(1), history: [...v.history, snapOf(v)], ...next };
    });
  }

  /** Reset view `id`'s primary range to auto-fit (`null` = fit data); recorded in history. */
  function autoFit(id: ViewId) { setRange(id, { x: null, y: null }); }

  /** Set the ACTIVE view's TF plot type. */
  function setPlotType(t: TfPlotType) { patch(get(active), v => ({ ...v, plotType: t })); }

  /**
   * Set (not toggle) the ACTIVE view's coherence overlay flag. Scoping
   * to the active view is safe because this is only ever called from
   * the active view's context card.
   */
  function setCoherence(on: boolean) { patch(get(active), v => ({ ...v, coherence: on })); }

  /**
   * Set the ACTIVE view's frequency x-axis scale (`'lin'`/`'log'`).
   * Scoped to the active view (like `setPlotType`) because it is only
   * ever driven from the active view's toolbar/card.
   */
  function setXScale(s: AxisScale) { patch(get(active), v => ({ ...v, xScale: s })); }

  /** Set the ACTIVE view's magnitude scale (`'log'` = dB, `'lin'` = |H|). */
  function setYScale(s: AxisScale) { patch(get(active), v => ({ ...v, yScale: s })); }

  /**
   * Set (not toggle) the tf view's coherence right-axis mode (round-5 item 6):
   * `false` ⇒ the fixed `[0,1]` axis (default), `true` ⇒ auto-fit the coherence
   * data. A display mode like `xScale`/`yScale`, so NOT recorded in history.
   */
  function setCoherenceAuto(on: boolean) { patch('tf', v => ({ ...v, coherenceAuto: on })); }

  /** Set view `id`'s legend placement/visibility. */
  function setLegend(id: ViewId, legend: ViewSlice['legend']) { patch(id, v => ({ ...v, legend })); }

  /** Snapshot the whole state as plain JSON-safe data (spec §11). */
  function serialize() { return { views: get(views), active: get(active) }; }

  /**
   * Restore a snapshot produced by `serialize` (accepts JSON
   * round-trips). Invalid snapshots — anything without all four view
   * slices present as objects — are IGNORED entirely; state is never
   * partially applied. Each slice is merged over `fresh()` defaults so
   * stale-schema snapshots missing newer fields get those defaults; an
   * unrecognised `active` view is coerced to 'time'.
   */
  function restore(snap: unknown) {
    const s = snap as { views?: Record<string, unknown>; active?: unknown } | null;
    const raw = s?.views;
    if (typeof raw !== 'object' || raw === null) return;
    if (!VIEW_IDS.every(id => typeof raw[id] === 'object' && raw[id] !== null)) return;
    const merged = {} as Record<ViewId, ViewSlice>;
    for (const id of VIEW_IDS) {
      const slice = { ...fresh(), ...(raw[id] as Partial<ViewSlice>) };
      // History/future may arrive in the pre-round-5 `Range[]` shape (or with
      // malformed entries); coerce each to a valid RangeSnapshot and drop the
      // rest so back()/forward() never restore an undefined range.
      slice.history = (Array.isArray(slice.history) ? slice.history : [])
        .map(toSnapshot).filter((s): s is RangeSnapshot => s !== null);
      slice.future = (Array.isArray(slice.future) ? slice.future : [])
        .map(toSnapshot).filter((s): s is RangeSnapshot => s !== null);
      merged[id] = slice;
    }
    views.set(merged);
    active.set((VIEW_IDS as readonly string[]).includes(s!.active as string)
      ? (s!.active as ViewId) : 'time');
  }

  return {
    active,
    /** Slice of the currently active view. */
    current: derived([views, active], ([$v, $a]) => $v[$a]),
    /** Frequency x-range shared across the TF family (tf wins over frequency). */
    sharedFreqRange: derived(views, $v => $v.tf.range.x ?? $v.frequency.range.x),

    activate, setRange, back, forward, autoFit,
    setNyquistRange, setPhaseRange, setBodePhaseRange, setCoherenceAuto,
    setPlotType, setCoherence, setXScale, setYScale, setLegend,
    serialize, restore,
  };
}
