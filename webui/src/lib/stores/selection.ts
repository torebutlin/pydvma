import { derived, writable, get } from 'svelte/store';

export type TriState = 'on' | 'fade' | 'off';
const NEXT: Record<TriState, TriState> = { on: 'fade', fade: 'off', off: 'on' };
export const LINE_PALETTE = [
  '#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2',
  '#be185d', '#4d7c0f', '#9333ea', '#0e7490', '#b91c1c', '#15803d'];

export interface SetEntry { name: string; nChannels: number; durationS: number; timestamp: string; }
export interface SetView extends SetEntry { index: number; allOff: boolean; collapsed: boolean; }
export interface LegendEntry { set: number; ch: number; label: string; color: string; state: TriState; }

/**
 * Tri-state (on / fade / off) selection store for the sets-by-channels
 * matrix in the data-navigation panel.
 *
 * Line states live in a sparse Map keyed `"set:channel"`; a missing key
 * means 'on', so newly added sets default to fully visible. Batch
 * operations (whole-set cycle, cross-set channel cycle, all/none/solo)
 * mutate a copy of the Map so subscribers see one atomic update.
 * Sets with more than 4 channels start collapsed in the UI; a set whose
 * lines are all 'off' is flagged `allOff` (rendered struck-through) and
 * omitted from the legend.
 */
export function createSelection() {
  const sets = writable<SetEntry[]>([]);
  const states = writable<Map<string, TriState>>(new Map());
  const collapsed = writable<Set<number>>(new Set());
  const highlight = writable<number>(0);

  const key = (s: number, c: number) => `${s}:${c}`;
  const stateOf = (m: Map<string, TriState>, s: number, c: number) => m.get(key(s, c)) ?? 'on';

  function mutate(fn: (m: Map<string, TriState>) => void) {
    states.update(m => { const n = new Map(m); fn(n); return n; });
  }

  /** Isolate one set: every line in set `s` goes 'on', all others 'off'. */
  function solo(s: number) {
    const list = get(sets); highlight.set(s);
    mutate(m => list.forEach((set, i) => {
      for (let c = 0; c < set.nChannels; c++) m.set(key(i, c), i === s ? 'on' : 'off');
    }));
  }

  /** Move the solo highlight one set forward/back, wrapping at the ends. */
  function step(dir: 1 | -1) {
    const n = get(sets).length; if (!n) return;
    const next = ((get(highlight) + dir) % n + n) % n;
    solo(next);
  }

  return {
    sets, collapsed, highlight,
    /** lookup function store: $state('0:1') -> TriState */
    state: derived(states, m => (k: string) => {
      const [s, c] = k.split(':').map(Number); return stateOf(m, s, c);
    }),

    addSet(entry: SetEntry) {
      sets.update(l => [...l, entry]);
      if (entry.nChannels > 4) collapsed.update(c => new Set(c).add(get(sets).length - 1));
    },
    rename(setIdx: number, name: string) {
      sets.update(l => l.map((s, i) => (i === setIdx ? { ...s, name } : s)));
    },
    cycleLine(s: number, c: number) {
      mutate(m => m.set(key(s, c), NEXT[stateOf(m, s, c)]));
    },
    cycleSet(s: number) {
      const list = get(sets); if (!list[s]) return;
      mutate(m => {
        const vals = Array.from({ length: list[s].nChannels }, (_, c) => stateOf(m, s, c));
        const uniform = vals.every(v => v === vals[0]);
        const target: TriState = uniform ? NEXT[vals[0]] : 'on';   // mixed -> on first
        for (let c = 0; c < list[s].nChannels; c++) m.set(key(s, c), target);
      });
    },
    cycleChannel(ch: number) {
      const list = get(sets);
      mutate(m => {
        const vals = list.flatMap((set, s) => (ch < set.nChannels ? [stateOf(m, s, ch)] : []));
        const uniform = vals.length > 0 && vals.every(v => v === vals[0]);
        const target: TriState = uniform ? NEXT[vals[0]] : 'on';
        list.forEach((set, s) => { if (ch < set.nChannels) m.set(key(s, ch), target); });
      });
    },
    all() { mutate(m => m.clear()); },
    none() {
      const list = get(sets);
      mutate(m => list.forEach((set, s) => {
        for (let c = 0; c < set.nChannels; c++) m.set(key(s, c), 'off');
      }));
    },
    solo,
    step,
    toggleCollapse(s: number) {
      collapsed.update(c => { const n = new Set(c); n.has(s) ? n.delete(s) : n.add(s); return n; });
    },

    setsView: derived([sets, states, collapsed], ([$sets, $states, $collapsed]) =>
      $sets.map((set, index): SetView => ({
        ...set, index, collapsed: $collapsed.has(index),
        allOff: Array.from({ length: set.nChannels }, (_, c) => stateOf($states, index, c))
          .every(v => v === 'off'),
      }))),

    legendEntries: derived([sets, states], ([$sets, $states]) => {
      const out: LegendEntry[] = [];
      $sets.forEach((set, s) => {
        const allOff = Array.from({ length: set.nChannels }, (_, c) => stateOf($states, s, c))
          .every(v => v === 'off');
        if (allOff) return;                                    // spec: omit from legend
        for (let c = 0; c < set.nChannels; c++) {
          const st = stateOf($states, s, c);
          if (st === 'off') continue;
          out.push({ set: s, ch: c, state: st,
            label: `${set.name} · ch_${c}`,
            color: LINE_PALETTE[(s * 2 + c) % LINE_PALETTE.length] });
        }
      });
      return out;
    }),
  };
}
