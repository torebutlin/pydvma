/**
 * Small display-formatting helpers for compact UI read-outs.
 */

/**
 * Round `x` to `sig` significant figures and render it WITHOUT trailing
 * zeros: `1.999977 → "2"`, `0.20000 → "0.2"`, `1.23456 → "1.23"`. Used
 * for the tray card's logged-duration badge, where a raw time-axis span
 * such as `1.999977 s` should read a sensible `2 s` (round-2 feedback)
 * rather than the full float. Non-finite inputs pass through as their
 * `String` form; zero renders as `"0"`.
 */
export function sigFigs(x: number, sig = 3): string {
  if (!Number.isFinite(x)) return String(x);
  if (x === 0) return '0';
  return String(Number(x.toPrecision(sig)));
}
