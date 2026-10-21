// Where an AUTOMATIC log frequency axis starts. A log axis cannot reach 0 Hz,
// and the first positive bin of a long record is a fraction of a hertz, so
// "first bin" spent most of the axis on decades nobody looks at (a 30 s
// record at 3 kHz opened at 0.03 Hz). Instead every log frequency axis opens
// LOG_FREQ_DECADES below its top, never below the data's own first positive
// frequency. A deterministic rule, rather than one read from the spectrum's
// content, so the same capture always opens the same way.

/**
 * Decades an automatic log frequency axis spans below its top. The twin of
 * `pydvma.analysis.LOG_FREQ_DECADES`, which sets the CWT's automatic band by
 * the same rule, so a CWT sonogram's computed rows and its axis agree.
 * Three decades: 24 Hz to 24 kHz at fs = 48 kHz, 1.5 Hz to 1.5 kHz at 3 kHz.
 */
export const LOG_FREQ_DECADES = 3;

/**
 * Lower bound of an automatic log frequency axis whose top is `top` (Hz):
 * `top / 10**LOG_FREQ_DECADES`, raised to `firstPositive` (the data's lowest
 * positive frequency) when that is higher, since below it there is nothing
 * to draw. Returns `firstPositive` unchanged when `top` is not positive, and
 * a tiny positive number when neither is usable, so a log scale never sees 0.
 */
export function logFreqFloor(top: number, firstPositive: number | undefined): number {
  const decadeFloor = top > 0 && Number.isFinite(top) ? top / 10 ** LOG_FREQ_DECADES : 0;
  const first = firstPositive !== undefined && firstPositive > 0 ? firstPositive : 0;
  const lo = Math.max(decadeFloor, first);
  return lo > 0 ? lo : 1e-6;
}

/**
 * Smallest finite POSITIVE x value across `lines`, or `undefined` when none
 * exists: the lowest frequency a log axis can actually draw.
 */
export function minPositiveX(lines: readonly { x: ArrayLike<number> }[]): number | undefined {
  let lo = Infinity;
  for (const l of lines) {
    for (let i = 0; i < l.x.length; i++) {
      const v = l.x[i];
      if (Number.isFinite(v) && v > 0 && v < lo) lo = v;
    }
  }
  return lo === Infinity ? undefined : lo;
}
