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
 * Column of `tf_data` (`(Nf, N−1)`, input dropped) that holds output
 * channel `ch`'s transfer function, or `null` when `ch` IS the input
 * channel (no line). `nChannels` is the SOURCE channel count; a channel
 * outside `[0, nChannels)` also returns `null` (nothing to draw).
 *
 * For the contiguous `0..nChannels−1` set the position within
 * `channels ∖ {chIn}` is exactly `ch > chIn ? ch − 1 : ch`.
 */
export function tfColumn(ch: number, chIn: number, nChannels: number): number | null {
  if (ch < 0 || ch >= nChannels) return null;
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
 * View-aware TF transform (Task R4): rewrite raw per-channel legend
 * entries into the out/in form the TF pane draws, so the legend and the
 * plot NEVER disagree. Drops each set's input channel (no TF line) and
 * relabels every surviving line `output/input` (e.g. `ch_1/ch_0`).
 *
 * `chInFor(setId)` gives the input channel the set's TF was computed with
 * (from the tf slice); a set with no TF result yet (`undefined`) keeps
 * its entries UNCHANGED so lines still show pre-Calc. `label` is the
 * channel-label accessor (default `ch_${n}`; R5 supplies custom labels).
 * Generic over the entry type so it works for both the model's
 * `VisibleLine` list and the `LegendEntry` list from a single call site.
 */
export function tfTransformEntries<E extends TfEntryLike>(
  entries: E[],
  chInFor: (setId: number) => number | undefined,
  label: (setId: number, ch: number) => string = (_setId, ch) => defaultChannelLabel(ch),
): E[] {
  const out: E[] = [];
  for (const e of entries) {
    const chIn = chInFor(e.setId);
    if (chIn === undefined) { out.push(e); continue; }   // no TF yet — pass through
    if (e.ch === chIn) continue;                          // input channel: no line
    out.push({ ...e, label: tfLineLabel(e.setId, e.ch, chIn, label) });
  }
  return out;
}
