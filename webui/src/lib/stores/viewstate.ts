import { derived, writable, get } from 'svelte/store';

/** The four plot views the GUI can display. */
export type ViewId = 'time' | 'frequency' | 'tf' | 'sono';
/** TF-view plot family (magnitude, phase, bode, real, imag, Nyquist). */
export type TfPlotType = 'mag' | 'phase' | 'bode' | 'real' | 'imag' | 'nyquist';
/** Axis ranges; `null` means "auto-fit to data" on that axis. */
export interface Range { x: [number, number] | null; y: [number, number] | null; }

/**
 * Per-view UI state slice: current axis range, zoom history (undo /
 * redo stacks), TF plot type (used by the tf view only; ignored
 * elsewhere), coherence overlay flag, and legend placement.
 */
export interface ViewSlice {
  range: Range;
  history: Range[]; future: Range[];
  plotType: TfPlotType;              // used by tf only; ignored elsewhere
  coherence: boolean;
  legend: { visible: boolean; x: number; y: number; preset: string | null };
}

const fresh = (): ViewSlice => ({
  range: { x: null, y: null }, history: [], future: [],
  plotType: 'mag', coherence: true,
  legend: { visible: true, x: 0.98, y: 0.02, preset: 'ne' },
});

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
   * Set view `id`'s axis range, pushing the previous range onto the
   * history stack (capped at 50 entries; oldest dropped) and clearing
   * the redo (`future`) stack. Continuous gestures (drag-pan, wheel
   * zoom) should coalesce into ONE setRange per gesture — that
   * debouncing is the plot interaction layer's job (Task 7), not this
   * store's.
   */
  function setRange(id: ViewId, range: Range) {
    patch(id, v => ({
      ...v, history: [...v.history, v.range].slice(-HISTORY_CAP), future: [], range,
    }));
  }

  /**
   * Step back through view `id`'s zoom history (no-op when empty).
   * Note the initial `{x: null, y: null}` auto-fit range is a valid
   * history entry — the guard is on `undefined` (empty stack), not on
   * null axis ranges.
   */
  function back(id: ViewId) {
    patch(id, v => {
      const prev = v.history.at(-1); if (prev === undefined) return v;
      return { ...v, history: v.history.slice(0, -1), future: [v.range, ...v.future], range: prev };
    });
  }

  /** Redo one zoom undone by `back` (no-op when the future stack is empty). */
  function forward(id: ViewId) {
    patch(id, v => {
      const next = v.future[0]; if (next === undefined) return v;
      return { ...v, future: v.future.slice(1), history: [...v.history, v.range], range: next };
    });
  }

  /** Reset view `id` to auto-fit (`null` = fit data); recorded in history. */
  function autoFit(id: ViewId) { setRange(id, { x: null, y: null }); }

  /** Set the ACTIVE view's TF plot type. */
  function setPlotType(t: TfPlotType) { patch(get(active), v => ({ ...v, plotType: t })); }

  /**
   * Set (not toggle) the ACTIVE view's coherence overlay flag. Scoping
   * to the active view is safe because this is only ever called from
   * the active view's context card.
   */
  function setCoherence(on: boolean) { patch(get(active), v => ({ ...v, coherence: on })); }

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
    for (const id of VIEW_IDS) merged[id] = { ...fresh(), ...(raw[id] as Partial<ViewSlice>) };
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
    setPlotType, setCoherence, setLegend,
    serialize, restore,
  };
}
