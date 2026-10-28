/**
 * The frequency band a typed edge asks for — the frequency navigator's
 * numeric min/max fields.
 *
 * The typed value is clamped to the strip's domain. When it lands beyond the
 * OTHER edge (a minimum typed above the current maximum, say, to move the
 * band up to the next peak), the band MOVES there and keeps its width — its
 * ratio on a log axis — rather than being refused: typing 290 into the
 * minimum of a 100–140 Hz band gives 290–330 Hz.
 *
 * Refusing it used to leave the typed number standing in the field while the
 * band stayed where it was, so a second edit committed against the hidden old
 * edge: the fields read "290 – 330" over a 100–330 Hz band, and a Fit there
 * found the 120 Hz peak (4C6 lab test, 2026-10-27).
 *
 * @param edge Which field was typed into.
 * @param raw The field's text.
 * @param band The current band `[lo, hi]`.
 * @param domain The strip's `[fmin, fmax]`.
 * @param log Whether the strip's frequency axis is logarithmic.
 * @returns The new band, or null when the text is not a number, the band
 *   would not change, or no band of positive width fits (an edge typed at the
 *   domain's far end) — the caller then shows the current band again.
 */
export function typedBand(
  edge: 'lo' | 'hi',
  raw: string,
  band: readonly [number, number],
  domain: readonly [number, number],
  log = false,
): [number, number] | null {
  const typed = parseFloat(raw);
  if (!Number.isFinite(typed)) return null;
  const [fmin, fmax] = domain;
  const v = Math.min(Math.max(typed, fmin), fmax);
  const [lo0, hi0] = band;
  const ratio = log && lo0 > 0 ? hi0 / lo0 : null;
  let lo: number;
  let hi: number;
  if (edge === 'lo') {
    lo = v;
    hi = hi0 > v ? hi0 : Math.min(fmax, ratio && v > 0 ? v * ratio : v + (hi0 - lo0));
  } else {
    hi = v;
    lo = lo0 < v ? lo0 : Math.max(fmin, ratio ? v / ratio : v - (hi0 - lo0));
  }
  if (!(hi > lo)) return null;
  if (lo === lo0 && hi === hi0) return null;
  return [lo, hi];
}
