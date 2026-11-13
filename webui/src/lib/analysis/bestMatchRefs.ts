/**
 * The transfer-function lines Best Match can take as its reference, named
 * the way the tray names their data cards.
 *
 * Best Match rescales every TF onto ONE reference line. The reference is
 * picked by card, as it appears in the tray: a card with a single TF line is
 * named by the card alone (`hammer_input_6.0s`), and a card with several
 * names each line as the TF legend does (`rig · ch_2/ch_0`). The TF card's
 * "ref TF" picker and `actions.calcBestMatch`'s prompt and toast all use
 * these names, so what is picked is what is reported.
 */
import { tfLineLabel } from '../plot/tfChannels';

/** One TF line offered as a Best Match reference. */
export interface BestMatchRef {
  /** Stable `${setId}:${ch}` key for a `<select>` value. */
  key: string;
  setId: number;
  /** SOURCE channel of the line (its output channel; the column for an orphan). */
  ch: number;
  /** Display name: the card's, plus the line when the card has several. */
  label: string;
}

/** What `bestMatchRefs` needs to know about a set's computed TF. */
export interface TfShape {
  /** Input channel the TF was computed with; `null` for an orphan TF. */
  chIn: number | null | undefined;
  /** Number of TF columns (lines). */
  nCols: number;
}

/**
 * Source channel of each TF column, in column order. A measured TF dropped
 * its input channel `chIn`, so the columns are the other channels in order;
 * an ORPHAN TF (`chIn` null, a TF-only file) has no input, and its columns
 * are the channels.
 */
export function tfLineChannels(chIn: number | null, nCols: number): number[] {
  return Array.from({ length: nCols }, (_, col) =>
    chIn === null ? col : (col < chIn ? col : col + 1));
}

/**
 * Display name of one TF line for Best Match: the card name when the card has
 * one TF line (`nLines` 1), else `card · out/in` (`card · ch_n` for an orphan).
 * `label` is the tray's channel-label accessor.
 */
export function tfLineName(
  name: string, ch: number, chIn: number | null, nLines: number,
  label: (setId: number, ch: number) => string, setId = 0,
): string {
  if (nLines <= 1) return name;
  const line = chIn === null ? label(setId, ch) : tfLineLabel(setId, ch, chIn, label);
  return `${name} · ${line}`;
}

/**
 * Every TF line of `sets`, in the order given (the tray's), as Best Match
 * reference options. A set without a computed TF, or with no TF columns, is
 * left out. `tfOf(setId)` reports the set's TF shape; an undefined `chIn`
 * reads as input channel 0, as elsewhere in the TF path.
 */
export function bestMatchRefs(
  sets: readonly { id: number; name: string }[],
  tfOf: (setId: number) => TfShape | undefined,
  label: (setId: number, ch: number) => string,
): BestMatchRef[] {
  const out: BestMatchRef[] = [];
  for (const s of sets) {
    const tf = tfOf(s.id);
    if (!tf || tf.nCols <= 0) continue;
    const chIn = tf.chIn === undefined ? 0 : tf.chIn;
    for (const ch of tfLineChannels(chIn, tf.nCols)) {
      out.push({
        key: `${s.id}:${ch}`, setId: s.id, ch,
        label: tfLineName(s.name, ch, chIn, tf.nCols, label, s.id),
      });
    }
  }
  return out;
}
