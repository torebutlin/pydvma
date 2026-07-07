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
/**
 * Render-ready view: identity (`id`) plus current ordering (`index`) and
 * two whole-set state flags. `allOff` when every line is 'off' (card
 * struck-through / "out of stock"); `allFade` when every line is 'fade'
 * (title dimmed). Both are false for a mixed set or an all-'on' set.
 */
export interface SetView extends SetRecord { index: number; allOff: boolean; allFade: boolean; collapsed: boolean; }
/** One legend row. `setId` is the set's stable identity, not its position. */
export interface LegendEntry { setId: number; ch: number; label: string; color: string; state: TriState; }

/** The store object `createSelection()` returns (for component props). */
export type Selection = ReturnType<typeof createSelection>;

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
 * `allOff` (rendered struck-through). Off lines are dropped from
 * `legendEntries` (the PLOT-facing list) but KEPT in `legendRows` (the
 * LEGEND-facing list) so a line toggled off stays listed, struck-through,
 * and can be cycled back on.
 */
export function createSelection() {
  const sets = writable<SetRecord[]>([]);
  const states = writable<Map<string, TriState>>(new Map());
  const collapsed = writable<Set<number>>(new Set());
  /**
   * Custom per-channel labels (Task R5), a sparse Map keyed `"id:channel"`
   * — a missing key means "use the default" (`ch_${c}`). Renaming a line
   * writes here; a blank/whitespace label deletes the key (reset to
   * default). Keyed by set id like `states`, so a `removeSet` cleanup and
   * the never-reused id scheme keep labels from leaking between sets.
   * PERSISTED to `.dvma`: `getLabelsForSet` feeds `stampUiState`, which
   * writes them onto each item's `ui.channel_labels`; `loadDataset`
   * restores them on open (additive, backwards-compatible manifest key).
   */
  const labels = writable<Map<string, string>>(new Map());
  /** id of the currently soloed/highlighted set (initially 0). */
  const highlight = writable<number>(0);
  let nextId = 0;

  const key = (id: number, c: number) => `${id}:${c}`;
  const stateOf = (m: Map<string, TriState>, id: number, c: number) => m.get(key(id, c)) ?? 'on';
  const labelOf = (m: Map<string, string>, id: number, c: number) => m.get(key(id, c)) ?? `ch_${c}`;
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
     * Lookup function store: `$channelLabel(setId, ch)` -> display label
     * (Task R5). The custom label if one was set via `renameChannel`,
     * else the default `ch_${ch}`. This is the accessor the tray, the
     * legend and the TF out/in transform all read, so a rename shows up
     * everywhere consistently.
     */
    channelLabel: derived(labels, m => (id: number, c: number) => labelOf(m, id, c)),

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
      labels.update(m => {
        const n = new Map(m);
        for (let c = 0; c < removed.nChannels; c++) n.delete(key(id, c));
        return n;
      });
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
    /**
     * Give line (set `id`, channel `ch`) a custom label (Task R5). The
     * label is trimmed; a blank/whitespace label DELETES the custom entry
     * so the channel reverts to its default `ch_${ch}`. Unknown set id is
     * a no-op. Edits flow to the tray, the legend (`"<set> · <label>"`)
     * and — via `channelLabel` — the TF out/in labels. Same copy-on-write
     * discipline as the tri-state map: subscribers see one atomic update.
     */
    renameChannel(id: number, ch: number, label: string) {
      if (!findSet(id)) return;
      const trimmed = label.trim();
      labels.update(m => {
        const n = new Map(m);
        if (trimmed) n.set(key(id, ch), trimmed);
        else n.delete(key(id, ch));   // blank → reset to default
        return n;
      });
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
     * Cycle a whole set as a group (tray card-title / header click).
     *
     * Convention for the MIXED case: when the set's lines are NOT all in
     * the same tri-state, the first click coerces every line to 'on'
     * (rather than trying to advance each line independently or picking a
     * "majority" state). That gives the user a single predictable "reset
     * to fully shown" step from any tangle of per-line states. Once the
     * set is uniform, each further click advances all lines together
     * on → fade → off → on. So the observable sequence from a mixed set
     * is: mixed → on → fade → off → on → …  Unknown id is a no-op.
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
      $sets.map((set, index): SetView => {
        const st = Array.from({ length: set.nChannels }, (_, c) => stateOf($states, set.id, c));
        return {
          ...set, index, collapsed: $collapsed.has(set.id),
          allOff: st.every(v => v === 'off'),
          allFade: st.length > 0 && st.every(v => v === 'fade'),
        };
      })),

    /**
     * Tray-focus signal: `setId` when the tray is showing exactly ONE
     * set (every line of that set 'on', every line of every OTHER set
     * 'off') — i.e. a clean `solo` state — and `'all'` otherwise
     * (multiple sets visible, or a mixed/partial selection). This is the
     * signal the analysisSettings store's `analysisTarget` follows so the
     * "Dataset ▾" dropdown mirrors what the tray is showing. It reads the
     * displayed state, NOT the persisted `highlight`, so cycling a second
     * set back on (leaving a solo) correctly reads as `'all'`.
     */
    trayFocus: derived([sets, states], ([$sets, $states]): 'all' | number => {
      // 0 or 1 set: no meaningful solo distinction — read as 'all' so the
      // dataset dropdown shows "All sets" by default on a single-set load.
      if ($sets.length <= 1) return 'all';
      let soloed: number | null = null;
      for (const set of $sets) {
        const on = Array.from({ length: set.nChannels }, (_, c) => stateOf($states, set.id, c));
        const allOn = on.length > 0 && on.every(v => v === 'on');
        const allOff = on.every(v => v === 'off');
        if (allOn) {
          if (soloed !== null) return 'all';   // two fully-on sets → not a solo
          soloed = set.id;
        } else if (!allOff) {
          return 'all';                        // a partial/faded set → not a clean solo
        }
      }
      return soloed ?? 'all';
    }),

    /**
     * Read all custom channel labels for set `id` as a sparse
     * `Record<string, string>` keyed by channel index (stringified).
     * Returns `undefined` when the set has NO custom labels at all
     * (so callers can distinguish "no labels" from "empty object" and
     * skip serialisation). Used by `stampUiState` (Plan 2 persistence).
     */
    getLabelsForSet(id: number): Record<string, string> | undefined {
      const rec = findSet(id);
      if (!rec) return undefined;
      const m = get(labels);
      const out: Record<string, string> = {};
      let any = false;
      for (let c = 0; c < rec.nChannels; c++) {
        const lbl = m.get(key(id, c));
        if (lbl) { out[String(c)] = lbl; any = true; }
      }
      return any ? out : undefined;
    },

    legendEntries: derived([sets, states, labels], ([$sets, $states, $labels]) => {
      const out: LegendEntry[] = [];
      $sets.forEach(set => {
        const allOff = Array.from({ length: set.nChannels }, (_, c) => stateOf($states, set.id, c))
          .every(v => v === 'off');
        if (allOff) return;                                    // spec: omit from legend
        for (let c = 0; c < set.nChannels; c++) {
          const st = stateOf($states, set.id, c);
          if (st === 'off') continue;
          out.push({ setId: set.id, ch: c, state: st,
            label: `${set.name} · ${labelOf($labels, set.id, c)}`,
            color: set.colors[c] });
        }
      });
      return out;
    }),

    /**
     * Legend DISPLAY rows — like `legendEntries` but KEEPS every line,
     * including 'off' ones (and lines of a fully-off set), each tagged with
     * its current tri-state. This is what the plot Legend renders so an off
     * line stays listed (struck-through, like the tray) and can be clicked
     * back on — round-2 feedback: a line vanishing from the legend the
     * moment it went off was a dead end (no way to re-enable it there).
     *
     * `legendEntries` remains the PLOT-facing list (off dropped) that the
     * visible-line derivation consumes, so the two never disagree on what
     * is DRAWN; `legendRows` only governs what the legend LISTS.
     */
    legendRows: derived([sets, states, labels], ([$sets, $states, $labels]) => {
      const out: LegendEntry[] = [];
      $sets.forEach(set => {
        for (let c = 0; c < set.nChannels; c++) {
          out.push({ setId: set.id, ch: c, state: stateOf($states, set.id, c),
            label: `${set.name} · ${labelOf($labels, set.id, c)}`,
            color: set.colors[c] });
        }
      });
      return out;
    }),
  };
}
