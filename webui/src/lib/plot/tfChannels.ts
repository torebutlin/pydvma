/**
 * TF out/in channel mapping (Task R4). One place for the two facts the
 * plot model and the legend must agree on so a TF pane and its legend
 * never disagree:
 *
 *   1. `calculate_tf(time_data, ch_in)` DROPS the input channel, so
 *      `tf_data` is `(Nf, N−1)` — one OUTPUT column per non-input channel
 *      in ascending channel order. The column for a given source channel
 *      is therefore its position within `channels ∖ {chIn}`. For the
 *      standard contiguous `0..N−1` channel set that collapses to
 *      `ch > chIn ? ch − 1 : ch`; `tfColumn` handles the general (sparse)
 *      case too. The input channel itself has NO column (returns `null`)
 *      and must not be drawn.
 *
 *   2. Each output line is labelled `output/input` (e.g. `ch_1/ch_0`) so
 *      it stays unambiguous when different sets carry different channel
 *      arrangements. `tfLineLabel` builds that from a channel-label
 *      accessor (`ch_${n}` by default) — factored so R5's per-channel
 *      custom labels slot straight in.
 *
 * Pure, node-testable (`tests/plot/tfChannels.test.ts`), Svelte-free.
 */

/** Default channel label — `ch_0`, `ch_1`, … (R5 overrides this). */
export function defaultChannelLabel(ch: number): string {
  return `ch_${ch}`;
}

/**
 * Column of `tf_data` that holds output channel `ch`'s transfer function,
 * or `null` when `ch` has no column. `nChannels` is the SOURCE channel
 * count; a channel outside `[0, nChannels)` returns `null` (nothing to
 * draw).
 *
 * `chIn` selects the convention:
 *   - a NUMBER (a real measured input channel): `tf_data` is `(Nf, N−1)`
 *     because `calculate_tf` DROPS the input, so the input channel has no
 *     column (`null`) and the surviving outputs shift — for the contiguous
 *     `0..nChannels−1` set the position within `channels ∖ {chIn}` is
 *     exactly `ch > chIn ? ch − 1 : ch`.
 *   - `null` (an ORPHAN TF — a loaded TF-only file with no measured input,
 *     round-5 item 3): there is NOTHING to drop, so `tf_data` is `(Nf, N)`
 *     and every source channel maps to its OWN column (identity). This is
 *     the case for a JW-logger `.mat` whose `yspec` is a bare TF matrix —
 *     the columns ARE the lines, drawn per-column (no out/in relabel).
 */
export function tfColumn(ch: number, chIn: number | null, nChannels: number): number | null {
  if (ch < 0 || ch >= nChannels) return null;
  if (chIn === null) return ch;          // orphan TF: columns are the lines (identity)
  if (ch === chIn) return null;
  return ch > chIn ? ch - 1 : ch;
}

/**
 * `output/input` label for a TF line, e.g. `ch_1/ch_0`. `label` maps a
 * (setId, channel) pair to its display name (default `ch_${n}`); passing
 * a custom accessor (R5) relabels both halves consistently. `setId` is
 * threaded so R5's per-set custom channel labels resolve correctly.
 */
export function tfLineLabel(
  setId: number,
  chOut: number,
  chIn: number,
  label: (setId: number, ch: number) => string = (_setId, ch) => defaultChannelLabel(ch),
): string {
  return `${label(setId, chOut)}/${label(setId, chIn)}`;
}

/** Minimal legend-entry shape the TF transform reads and rewrites. */
export interface TfEntryLike { setId: number; ch: number; label: string; }

/**
 * Separator between the set-name prefix and the channel part of a legend
 * label (`"set · ch_0"`). The TF transform preserves the prefix (so lines
 * from different sets stay distinguishable) and rewrites only the channel
 * part to `out/in`. Kept in sync with `selection.legendEntries`.
 */
const LABEL_SEP = ' · ';

/**
 * View-aware TF transform (Task R4): rewrite raw per-channel legend
 * entries into the out/in form the TF pane draws, so the legend and the
 * plot NEVER disagree. Drops each set's input channel (no TF line) and
 * relabels every surviving line `output/input` (e.g. `ch_1/ch_0`),
 * preserving any `"set · "` prefix from the original label so multi-set
 * legends stay distinguishable (`"A · ch_1/ch_0"`).
 *
 * `chInFor(setId)` gives the input channel the set's TF was computed with
 * (from the tf slice); a set with no TF result yet (`undefined`) OR an
 * ORPHAN TF with no measured input (`null`, round-5 item 3) keeps its
 * entries UNCHANGED — pre-Calc lines still show, and an orphan TF lists its
 * columns per-channel (plain `ch_n` labels, no out/in relabel, nothing
 * dropped). `label` is the channel-label accessor (default `ch_${n}`; R5
 * supplies custom labels). Generic over the entry type so it works for both
 * the model's `VisibleLine` list and the `LegendEntry` list from a single
 * call site.
 */
export function tfTransformEntries<E extends TfEntryLike>(
  entries: E[],
  chInFor: (setId: number) => number | null | undefined,
  label: (setId: number, ch: number) => string = (_setId, ch) => defaultChannelLabel(ch),
): E[] {
  const out: E[] = [];
  for (const e of entries) {
    const chIn = chInFor(e.setId);
    // undefined = no TF yet; null = orphan TF (columns are the lines).
    // Both pass the raw per-channel entry through unchanged.
    if (chIn === undefined || chIn === null) { out.push(e); continue; }
    if (e.ch === chIn) continue;                          // input channel: no line
    const sep = e.label.lastIndexOf(LABEL_SEP);
    const prefix = sep >= 0 ? e.label.slice(0, sep + LABEL_SEP.length) : '';
    out.push({ ...e, label: prefix + tfLineLabel(e.setId, e.ch, chIn, label) });
  }
  return out;
}
