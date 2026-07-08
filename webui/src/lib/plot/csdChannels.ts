/**
 * CSD pair legend transform (round-5 item 7). The cross-spectrum view draws
 * exactly ONE line per set — the chosen pair `(i, j)` — carried on the Y
 * channel `j` (see `buildPlotModel`'s csd branch). This collapses the raw
 * per-channel legend entries to that single row and relabels it `S(x,y)` so the
 * legend and the plot agree, mirroring `tfTransformEntries` for the TF view.
 *
 * `pairFor(setId)` gives the set's `(i, j)` pair from its decoded `csd` slice,
 * or `undefined`/`null` for a set with NO CSD yet — those pass through
 * unchanged (their raw channel rows still show, pre-Calc). `label` is the
 * channel-label accessor (default `ch_${n}`; R5 supplies custom labels) so a
 * renamed channel reads e.g. `S(hammer,accel)`.
 *
 * Pure, node-testable (`tests/plot/csdChannels.test.ts`), Svelte-free.
 */
import { defaultChannelLabel, type TfEntryLike } from './tfChannels';

/** Separator between the set-name prefix and the channel part (`"set · ch_0"`). */
const LABEL_SEP = ' · ';

/**
 * Keep only each set's Y-channel row and relabel it `S(x,y)` (round-5 item 7).
 * A set with no CSD pair (`undefined`/`null`) passes every row through
 * unchanged. Preserves any `"set · "` prefix so multi-set legends stay
 * distinguishable, and carries through extra entry fields (colour/state).
 */
export function csdPairEntries<E extends TfEntryLike>(
  entries: E[],
  pairFor: (setId: number) => { i: number; j: number } | null | undefined,
  label: (setId: number, ch: number) => string = (_setId, ch) => defaultChannelLabel(ch),
): E[] {
  const out: E[] = [];
  for (const e of entries) {
    const pair = pairFor(e.setId);
    if (pair === undefined || pair === null) { out.push(e); continue; }  // no CSD yet
    if (e.ch !== pair.j) continue;                                       // keep only the pair's Y row
    const sep = e.label.lastIndexOf(LABEL_SEP);
    const prefix = sep >= 0 ? e.label.slice(0, sep + LABEL_SEP.length) : '';
    out.push({ ...e, label: `${prefix}S(${label(e.setId, pair.i)},${label(e.setId, pair.j)})` });
  }
  return out;
}
