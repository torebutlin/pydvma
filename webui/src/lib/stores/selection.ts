import { derived, writable, get } from 'svelte/store';

export type TriState = 'on' | 'fade' | 'off';
const NEXT: Record<TriState, TriState> = { on: 'fade', fade: 'off', off: 'on' };

/**
 * Fixed 12-colour palette for plot lines.
 *
 * Colours are assigned once, at `addSet` time, by cumulative channel
 * offset (see `createSelection.addSet`) and stored on the set record —
 * they never shift as sets are cycled, soloed, reordered, or removed.
 * `LINE_PALETTE` + `lineColor(id, ch)` are the single source of truth
 * for line colours; the plot model (Task 12) must consume these rather
 * than deriving its own.
 */
export const LINE_PALETTE = [
  '#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2',
  '#be185d', '#4d7c0f', '#9333ea', '#0e7490', '#b91c1c', '#15803d'];

/** Input shape for `addSet` — what the caller knows about a dataset. */
export interface SetEntry { name: string; nChannels: number; durationS: number; timestamp: string; }
/** A set as stored: input fields plus stable `id` and owned line `colors`. */
export interface SetRecord extends SetEntry { id: number; colors: string[]; }
/** Render-ready view: identity (`id`) plus current ordering (`index`). */
export interface SetView extends SetRecord { index: number; allOff: boolean; collapsed: boolean; }
/** One legend row. `setId` is the set's stable identity, not its position. */
export interface LegendEntry { setId: number; ch: number; label: string; color: string; state: TriState; }

/**
 * Tri-state (on / fade / off) selection store for the sets-by-channels
 * matrix in the data-navigation panel.
 *
 * Every set gets a monotonic, never-reused `id` at `addSet` time; all
 * public methods address sets by id, so removing a set never disturbs
 * the states, colours, or collapse flags of the survivors. `index` (the
 * current position in the list) appears only on `SetView` for rendering
 * order — it is not an API handle.
 *
 * Line states live in a sparse Map keyed `"id:channel"` (private); a
 * missing key means 'on', so newly added sets default to fully visible
 * even after a global `none()`. Batch operations (whole-set cycle,
 * cross-set channel cycle, all/none/solo) mutate a copy of the Map so
 * subscribers see one atomic update. Sets with more than 4 channels
 * start collapsed in the UI; a set whose lines are all 'off' is flagged
 * `allOff` (rendered struck-through) and omitted from the legend.
 */
export function createSelection() {
  const sets = writable<SetRecord[]>([]);
  const states = writable<Map<string, TriState>>(new Map());
  const collapsed = writable<Set<number>>(new Set());
  /** id of the currently soloed/highlighted set (initially 0). */
  const highlight = writable<number>(0);
  let nextId = 0;

  const key = (id: number, c: number) => `${id}:${c}`;
  const stateOf = (m: Map<string, TriState>, id: number, c: number) => m.get(key(id, c)) ?? 'on';
  const findSet = (id: number) => get(sets).find(s => s.id === id);

  function mutate(fn: (m: Map<string, TriState>) => void) {
    states.update(m => { const n = new Map(m); fn(n); return n; });
  }

  /**
   * Isolate one set: every line in set `id` goes 'on', all others 'off'.
   * Unknown id is a no-op (highlight is left untouched).
   */
  function solo(id: number) {
    const list = get(sets);
    if (!list.some(s => s.id === id)) return;
    highlight.set(id);
    mutate(m => list.forEach(set => {
      for (let c = 0; c < set.nChannels; c++) m.set(key(set.id, c), set.id === id ? 'on' : 'off');
    }));
  }

  /**
   * Move the solo one set forward/back in the CURRENT display order,
   * wrapping at the ends. The highlight itself is stored as a set id,
   * so it survives removals; if the highlighted set no longer exists,
   * stepping restarts from the first set.
   */
  function step(dir: 1 | -1) {
    const list = get(sets); const n = list.length; if (!n) return;
    const at = list.findIndex(s => s.id === get(highlight));
    const from = at === -1 ? 0 : at;
    solo(list[((from + dir) % n + n) % n].id);
  }

  return {
    sets, collapsed, highlight,
    /** Lookup function store: `$state(setId, ch)` -> TriState. */
    state: derived(states, m => (id: number, c: number) => stateOf(m, id, c)),

    /**
     * Register a dataset and return its stable id. Line colours are
     * assigned here — `LINE_PALETTE[(start + ch) % 12]` where `start`
     * is the total channel count of the sets present at add time — and
     * stored on the record, so they never change afterwards. New lines
     * default to 'on' (sparse-map default), even after a prior `none()`.
     * Sets with more than 4 channels start collapsed.
     */
    addSet(entry: SetEntry): number {
      const id = nextId++;
      const start = get(sets).reduce((acc, s) => acc + s.nChannels, 0);
      const colors = Array.from({ length: entry.nChannels },
        (_, c) => LINE_PALETTE[(start + c) % LINE_PALETTE.length]);
      sets.update(l => [...l, { ...entry, id, colors }]);
      if (entry.nChannels > 4) collapsed.update(cs => new Set(cs).add(id));
      return id;
    },
    /**
     * Remove a set by id. Because states, colours, and collapse flags
     * are keyed by id, the surviving sets are left byte-for-byte intact;
     * only the removed set's entries are dropped. If the removed set was
     * highlighted, the highlight moves to the set now occupying its slot
     * (or the last set, or -1 when none remain).
     */
    removeSet(id: number) {
      const list = get(sets);
      const idx = list.findIndex(s => s.id === id);
      if (idx === -1) return;
      const removed = list[idx];
      sets.set(list.filter(s => s.id !== id));
      mutate(m => { for (let c = 0; c < removed.nChannels; c++) m.delete(key(id, c)); });
      collapsed.update(cs => { const n = new Set(cs); n.delete(id); return n; });
      if (get(highlight) === id) {
        const rest = get(sets);
        highlight.set(rest.length ? rest[Math.min(idx, rest.length - 1)].id : -1);
      }
    },
    /** Rename set `id` (label edits propagate to the legend). */
    rename(id: number, name: string) {
      sets.update(l => l.map(s => (s.id === id ? { ...s, name } : s)));
    },
    /** Line colour for (set id, channel) — the single source of truth
     *  the plot model must consume. Undefined for unknown id/channel. */
    lineColor(id: number, ch: number): string | undefined {
      return findSet(id)?.colors[ch];
    },
    /** Cycle one line on -> fade -> off -> on. Unknown id is a no-op. */
    cycleLine(id: number, c: number) {
      if (!findSet(id)) return;
      mutate(m => m.set(key(id, c), NEXT[stateOf(m, id, c)]));
    },
    /**
     * Cycle a whole set (card-header click). If the set's lines are
     * uniform they all advance one step together; if MIXED they first
     * snap to uniform 'on' — so a click always produces a coherent set.
     */
    cycleSet(id: number) {
      const rec = findSet(id); if (!rec) return;
      mutate(m => {
        const vals = Array.from({ length: rec.nChannels }, (_, c) => stateOf(m, id, c));
        const uniform = vals.length > 0 && vals.every(v => v === vals[0]);
        const target: TriState = uniform ? NEXT[vals[0]] : 'on';   // mixed -> on first
        for (let c = 0; c < rec.nChannels; c++) m.set(key(id, c), target);
      });
    },
    /**
     * Cycle channel `ch` across ALL sets (chip click), collapsed ones
     * included. Sets with fewer than `ch + 1` channels are skipped —
     * they neither receive the new state nor vote in the uniformity
     * check. Mixed states across sets snap to uniform 'on' first.
     */
    cycleChannel(ch: number) {
      const list = get(sets);
      mutate(m => {
        const vals = list.flatMap(set => (ch < set.nChannels ? [stateOf(m, set.id, ch)] : []));
        const uniform = vals.length > 0 && vals.every(v => v === vals[0]);
        const target: TriState = uniform ? NEXT[vals[0]] : 'on';
        list.forEach(set => { if (ch < set.nChannels) m.set(key(set.id, ch), target); });
      });
    },
    /** Every line 'on' (clears the sparse map back to its default). */
    all() { mutate(m => m.clear()); },
    /** Every line of every CURRENT set 'off'; later-added sets still default 'on'. */
    none() {
      const list = get(sets);
      mutate(m => list.forEach(set => {
        for (let c = 0; c < set.nChannels; c++) m.set(key(set.id, c), 'off');
      }));
    },
    solo,
    step,
    /** Toggle the collapsed flag for set `id`. */
    toggleCollapse(id: number) {
      collapsed.update(cs => {
        const n = new Set(cs);
        if (n.has(id)) { n.delete(id); } else { n.add(id); }
        return n;
      });
    },

    setsView: derived([sets, states, collapsed], ([$sets, $states, $collapsed]) =>
      $sets.map((set, index): SetView => ({
        ...set, index, collapsed: $collapsed.has(set.id),
        allOff: Array.from({ length: set.nChannels }, (_, c) => stateOf($states, set.id, c))
          .every(v => v === 'off'),
      }))),

    legendEntries: derived([sets, states], ([$sets, $states]) => {
      const out: LegendEntry[] = [];
      $sets.forEach(set => {
        const allOff = Array.from({ length: set.nChannels }, (_, c) => stateOf($states, set.id, c))
          .every(v => v === 'off');
        if (allOff) return;                                    // spec: omit from legend
        for (let c = 0; c < set.nChannels; c++) {
          const st = stateOf($states, set.id, c);
          if (st === 'off') continue;
          out.push({ setId: set.id, ch: c, state: st,
            label: `${set.name} · ch_${c}`,
            color: set.colors[c] });
        }
      });
      return out;
    }),
  };
}
