/**
 * Does a channel look like an impulse response? (round-15 item 4)
 *
 * Clean Impulse zeroes the pre-impulse noise and windows the tail, which
 * only makes sense on a record whose energy is front-loaded — a hammer
 * tap. Offered on a 30 s random-noise capture it is a trap. The Time card
 * therefore shows the button only when the chosen input channel passes
 * this test: the fraction of the channel's energy in the SECOND half of
 * the record is at most `IMPULSE_TAIL_MAX`. Deliberately conservative
 * (a poor, ringing tap keeps its button): the lab's 6 s taps put 0–1 %
 * of their energy in the second half, its noise captures 46–55 %.
 */

/** Largest second-half energy fraction still treated as an impulse. */
export const IMPULSE_TAIL_MAX = 0.25;

/**
 * Fraction of channel `ch`'s energy that lies in the second half of the
 * record, for a flat row-major `(N, nCh)` sample buffer (pydvma's layout:
 * sample-major, channels interleaved). `null` when there is no such
 * channel or the channel is silent (no energy to apportion).
 */
export function impulseTailFraction(
  data: ArrayLike<number>, nCh: number, ch: number,
): number | null {
  if (!(nCh >= 1) || !(ch >= 0) || ch >= nCh) return null;
  const n = Math.floor(data.length / nCh);
  if (n < 2) return null;
  const half = Math.floor(n / 2);
  let head = 0, tail = 0;
  for (let i = 0; i < n; i++) {
    const v = data[i * nCh + ch];
    const e = v * v;
    if (i < half) head += e; else tail += e;
  }
  const total = head + tail;
  if (!(total > 0) || !Number.isFinite(total)) return null;
  return tail / total;
}

/** True when `fraction` (from `impulseTailFraction`) passes the gate. */
export function looksLikeImpulse(fraction: number | null): boolean {
  return fraction !== null && fraction <= IMPULSE_TAIL_MAX;
}
