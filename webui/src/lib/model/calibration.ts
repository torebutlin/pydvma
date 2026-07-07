/**
 * Calibration helpers (Wave-A Task A2) — pure, node-testable maths + coercion
 * for per-channel calibration. NO Svelte / store / worker imports.
 *
 * ── The sensitivity ↔ cal-factor convention (verified against pydvma) ──
 *
 * pydvma keeps recorded `time_data` **in volts** and converts to engineering
 * units at DISPLAY / fit time by multiplying each channel by a stored
 * `channel_cal_factors[ch]` (see `datastructure.TimeData` docstring;
 * `plotting.py` does `time_data[:,ch] * channel_cal_factors[ch]`, mirrored by
 * the webui plot seam in `plot/model.ts`). The user, however, thinks in
 * **sensitivity**: the transducer's volts-per-engineering-unit rating
 * (V/g for an accelerometer, V/N for a force probe, V/Pa for a mic — see
 * `MySettings.channel_sensitivities`, `options.py:139`). Acquisition converts
 * one to the other by RECIPROCAL:
 *
 *     channel_cal_factors[ch] = 1 / sensitivity[ch]        (acquisition.py:236)
 *
 * e.g. a 100 mV/g accelerometer (sensitivity 0.1 V/g) stores a cal factor of
 * 10, so a 0.5 V sample plots as 5 g. This module implements the SAME
 * convention: the dialog collects a **sensitivity** (what the user reads off
 * the transducer) and we persist `1/sensitivity` as `channel_cal_factors`, the
 * field both codecs already round-trip and Python's `container.load` restores.
 *
 * A default/uncalibrated channel has sensitivity 1 → factor 1 → identity, so
 * absent calibration leaves the plotted volts unchanged.
 */

/**
 * The engineering-unit options the Calibrate dialog offers, EXACTLY as the
 * round-2 mockup shows them (`round2-bench.html:694`). `'V'` = uncalibrated
 * (the channel stays in volts). A channel whose STORED unit is none of these
 * (e.g. `'m/s'` from a legacy capture) is preserved by the dialog as an extra
 * option rather than silently rewritten — see `CalibrateDialog`.
 */
export const CAL_UNITS = ['V', 'm/s²', 'N', 'Pa'] as const;
export type CalUnit = (typeof CAL_UNITS)[number];

/** Fallback engineering unit for an uncalibrated channel (volts). */
export const DEFAULT_UNIT = 'V';

/**
 * Convert a user-entered **sensitivity** (volts per engineering unit) into the
 * stored **cal factor** (`1/sensitivity`), the pydvma capture convention. A
 * non-finite or zero sensitivity is treated as uncalibrated (factor `1`), never
 * ±Infinity — a 0 V/unit rating is meaningless and would blow up the display.
 */
export function sensitivityToFactor(sensitivity: number): number {
  return Number.isFinite(sensitivity) && sensitivity !== 0 ? 1 / sensitivity : 1;
}

/**
 * Inverse of {@link sensitivityToFactor}: recover the sensitivity a stored cal
 * factor implies (`1/factor`), used to seed the dialog input from persisted
 * `channel_cal_factors`. A non-finite or zero factor shows as sensitivity `1`
 * (uncalibrated). `1/(1/s) === s` so a dialog round-trip is lossless.
 */
export function factorToSensitivity(factor: number): number {
  return Number.isFinite(factor) && factor !== 0 ? 1 / factor : 1;
}

/**
 * Coerce an arbitrary stored `channel_cal_factors` value into a clean
 * `number[]` of EXACTLY `nCh` entries — the invariant the display seam and
 * `.dvma` persistence both rely on. Shorter inputs are padded with `1`
 * (identity), longer ones truncated; any non-finite or zero slot becomes `1`.
 * Accepts a plain array, a typed array, or `undefined`/`null` (all-ones).
 */
export function normalizeFactors(factors: unknown, nCh: number): number[] {
  const arr = factors as ArrayLike<number> | null | undefined;
  const out: number[] = new Array(Math.max(0, nCh));
  for (let i = 0; i < out.length; i++) {
    const v = arr && i < arr.length ? Number(arr[i]) : NaN;
    out[i] = Number.isFinite(v) && v !== 0 ? v : 1;
  }
  return out;
}

/**
 * Coerce a stored `units` meta value into a `string[]` of EXACTLY `nCh`
 * entries. Missing / non-string slots fall back to {@link DEFAULT_UNIT}
 * (`'V'`). Accepts a plain array or `undefined`/`null` (all-default). Existing
 * non-standard units (e.g. `'m/s'`) are carried through verbatim so the dialog
 * never destroys a unit it can't offer as a preset.
 */
export function normalizeUnits(units: unknown, nCh: number): string[] {
  const arr = Array.isArray(units) ? units : null;
  const out: string[] = new Array(Math.max(0, nCh));
  for (let i = 0; i < out.length; i++) {
    const v = arr ? arr[i] : undefined;
    out[i] = typeof v === 'string' && v.length > 0 ? v : DEFAULT_UNIT;
  }
  return out;
}

/** True when every factor is exactly 1 (identity — nothing to persist/apply). */
export function isIdentity(factors: readonly number[]): boolean {
  return factors.every((f) => f === 1);
}

/**
 * One channel's initial state for the Calibrate dialog: its display `label`
 * (custom relabels respected), the `sensitivity` (V/unit) the stored cal
 * factor implies, and the current engineering `unit`. Lives here (not in the
 * component) so both the dialog and the tray can import it without a
 * type-export from a `.svelte` module.
 */
export interface CalRow {
  ch: number;
  label: string;
  sensitivity: number;
  unit: string;
}
