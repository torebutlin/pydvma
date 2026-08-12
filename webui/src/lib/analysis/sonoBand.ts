// Pure rules behind the Sonogram card's CWT controls: the frequency-range
// boxes and the frequency axis each transform picks. Kept out of the component
// so both are unit-testable (the vitest run is DOM-free, so a .svelte file
// cannot be mounted) and so the rules are stated in exactly one place.
import type { AxisScale } from '../stores/viewstate';

/** Which of the two CWT band boxes an edit came from. */
export type SonoBandKey = 'fMin' | 'fMax';

/** The two band bounds as stored in a set's sono settings (null = automatic). */
export interface SonoBand { fMin: number | null; fMax: number | null; }

/**
 * Outcome of one band-box edit: the patch to apply, or a rejection.
 *
 * `patch` is `null` when the edit must NOT be stored; `error` then carries the
 * reason to show beside the boxes (empty string when the edit is accepted, or
 * when it is an unusable no-op with nothing worth saying).
 */
export interface SonoBandEdit {
  patch: Partial<SonoBand> | null;
  error: string;
}

/**
 * Validate one CWT frequency-range box against the band's OTHER side.
 *
 * The two boxes are independent, and a LONE bound is meaningful — the engine
 * fills the missing side with its automatic value — so an entry is judged only
 * against what is actually there:
 *
 * - blank clears that side back to automatic;
 * - a non-positive entry is refused (frequencies are positive; 0 Hz is not a
 *   wavelet centre frequency);
 * - a reversed pair is REFUSED rather than swapped or silently ignored. The
 *   engine used to substitute `f_max = 2*f_min` for a reversed band, so a
 *   typo produced a confident analysis of a band nobody asked for;
 * - a non-finite entry is a no-op (a number input cannot produce one, but `+`
 *   coercion in the caller can).
 *
 * Returns the patch to store, or `{patch: null, error}` to reject the edit.
 */
export function editSonoBand(which: SonoBandKey, raw: string, current: SonoBand): SonoBandEdit {
  const text = raw.trim();
  if (text === '') return { patch: { [which]: null }, error: '' };
  const v = Number(text);
  if (!Number.isFinite(v)) return { patch: null, error: '' };
  if (v <= 0) return { patch: null, error: 'frequency must be above 0 Hz' };
  const other = which === 'fMin' ? current.fMax : current.fMin;
  if (other !== null) {
    const lo = which === 'fMin' ? v : other;
    const hi = which === 'fMin' ? other : v;
    if (lo >= hi) return { patch: null, error: 'min must be below max' };
  }
  return { patch: { [which]: v }, error: '' };
}

/**
 * The frequency axis a sonogram method wants by default.
 *
 * The CWT is computed on a LOG (constant-Q) frequency ladder and returned on
 * that native grid, so a linear axis crushes most of its rows into the bottom
 * of the plot and throws away exactly the low-frequency detail the wavelet was
 * chosen for — the CWT image looks blocky next to a smooth STFT one. The STFT's
 * uniform bins want the linear axis they have always had.
 *
 * SonoCard applies this on each method TOGGLE (see its `onMethod`), which is
 * the whole rule: a manual choice from the plot toolbar afterwards stands
 * until the next toggle.
 */
export function sonoFreqScaleFor(method: 'stft' | 'cwt'): AxisScale {
  return method === 'cwt' ? 'log' : 'lin';
}
