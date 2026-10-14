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
 * The engineering-unit options the Calibrate dialog offers: the round-2
 * mockup's four (`round2-bench.html:694`) plus the displacement and velocity
 * rungs of the `m → m/s → m/s²` ladder, which a velocity-output pickup (3C6's
 * charge amp) and the x(iω) display transform both need. `'V'` = uncalibrated
 * (the channel stays in volts). A channel whose STORED unit is none of these
 * (e.g. `'g'`) is preserved by the dialog as an extra option rather than
 * silently rewritten — see `CalibrateDialog`.
 */
export const CAL_UNITS = ['V', 'm', 'm/s', 'm/s²', 'N', 'Pa'] as const;
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

/**
 * One transfer-function line's initial state for the Calibrate dialog's
 * "Transfer function" section: its display `label` (`ch_1/ch_0`), the factor
 * the channel calibration implies (`ratio`), any TF calibration already set
 * on it (`override`), and the unit the line currently reads in. Built by the
 * tray from `actions.getTfCalibration`.
 */
export interface TfCalRow {
  ch: number;
  label: string;
  ratio: number;
  override: TfCalLine | null;
  num: string;
  den: string;
  /** The unit the line reads in without a TF calibration — what ↺ restores. */
  chanNum: string;
  chanDen: string;
}

/**
 * Whether a set's samples are true VOLTS, judged from the capture settings
 * pydvma stored with it.
 *
 * `'V'` is the placeholder unit every uncalibrated channel wears
 * ({@link DEFAULT_UNIT}), so on its own it says nothing: a Web Audio capture
 * labelled `'V'` is really a normalised 0–1 fraction. The settings do know,
 * by exactly the rule the bridge uses for its live full-scale reference
 * (`serve._input_scale_fields`):
 *
 *   - `device_driver === 'nidaq'` — an NI AI task returns volts over its
 *     configured `±VmaxNI` range, always;
 *   - otherwise a soundcard's `VmaxSC`, which is the volts at full scale once
 *     the jack has been characterised and stays at its uncalibrated `1.0`
 *     placeholder until then.
 *
 * Reading it off the STORED settings (rather than off live acquisition state)
 * means a saved-and-reopened file, and a file written by python, answer the
 * same way — there is no extra field to persist and nothing to keep in sync.
 *
 * @param settings The item's `settings` block, as loaded.
 * @returns True only when the samples are known to be volts.
 */
export function capturedInVolts(settings: unknown): boolean {
  if (!settings || typeof settings !== 'object') return false;
  const s = settings as Record<string, unknown>;
  if (s.device_driver === 'nidaq') return true;
  const vmaxSc = Number(s.VmaxSC);
  return Number.isFinite(vmaxSc) && vmaxSc > 0 && vmaxSc !== 1;
}

/**
 * Parenthesise a COMPOUND unit so it composes unambiguously.
 *
 * A unit containing anything other than a letter or a digit is wrapped:
 * `'m/s²'` → `'(m/s²)'`, while `'N'` and `'Pa'` are left bare. Without it a
 * transfer function's unit string is ambiguous — `'m/s²/N'` reads equally as
 * `(m/s²)/N` (what it means) and `m/(s²·N)` (what it does not) — and anything
 * reading an exported file outside pydvma has to guess.
 *
 * Idempotent: a unit already enclosed in ONE matched outer pair comes back
 * unchanged, so composing twice does not nest.
 *
 * TWIN of `pydvma.analysis.wrap_unit`. Both sides must agree: python builds
 * the STORED `TfData.units` strings and the browser builds the same strings
 * for its CSV/Matlab export headers, and those files are byte-identical by
 * design. Pinned by the shared vectors in `UNIT_WRAP_VECTORS`.
 */
export function wrapUnit(u: string): string {
  if (!u) return u;
  if (isWrapped(u)) return u;
  return /[^\p{L}\p{N}]/u.test(u) ? `(${u})` : u;
}

/**
 * Whether `text` is already enclosed in ONE matched outer bracket pair.
 * `'(m/s²)'` is; `'(a)/(b)'` is not, despite starting `(` and ending `)` —
 * its outer pair does not span the whole string, and calling that wrapped
 * would leave an ambiguous ratio bare.
 */
function isWrapped(text: string): boolean {
  if (!text.startsWith('(') || !text.endsWith(')')) return false;
  let depth = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '(') depth += 1;
    else if (c === ')') {
      depth -= 1;
      if (depth === 0) return i === text.length - 1;
    }
  }
  return false;
}

/**
 * Split a stored transfer-function unit back into its numerator and
 * denominator, the inverse of {@link composeTfUnit}.
 *
 * The split is at the LAST `/` outside brackets, and one matched outer pair
 * is stripped from each side: `'(m/s²)/N'` → `m/s²` over `N`. pydvma before
 * 2.5 wrote no brackets (`'m/s²/N'`), which is strictly ambiguous; reading the
 * last slash as the ratio is right whenever the denominator is a single unit,
 * which for a transfer function — response over a force or a volt — it
 * practically always is. Anything that is not a ratio (`'N'`, an empty
 * string, a bracketed whole) gives `null`.
 *
 * Used to read a TF unit that python stored (a notebook's
 * `TfDataList.set_calibration_factor(..., units=...)`, or `analysis.calculate_tf`)
 * so the x(iω) display transform can still move the numerator along the
 * derivative ladder.
 */
export function splitTfUnit(unit: unknown): { num: string; den: string } | null {
  if (typeof unit !== 'string') return null;
  const u = unit.trim();
  let depth = 0;
  let at = -1;
  for (let i = 0; i < u.length; i++) {
    const c = u[i];
    if (c === '(') depth += 1;
    else if (c === ')') depth -= 1;
    else if (c === '/' && depth === 0) at = i;
  }
  if (at < 0) return null;
  const unwrap = (t: string) => (isWrapped(t) ? t.slice(1, -1).trim() : t);
  const num = unwrap(u.slice(0, at).trim());
  const den = unwrap(u.slice(at + 1).trim());
  return num && den ? { num, den } : null;
}

/**
 * A transfer function's unit from its numerator and denominator, each
 * bracketed when compound: `('m/s²', 'N')` → `'(m/s²)/N'`. The same string
 * python's `analysis._tf_units_from_source` stores, so a TF the browser saves
 * reads identically in a notebook.
 */
export function composeTfUnit(num: string, den: string): string {
  return `${wrapUnit(num)}/${wrapUnit(den)}`;
}

/**
 * One calibrated transfer-function line: the multiplier applied to the
 * MEASURED ratio, and the unit of the result as numerator over denominator.
 *
 * The factor is a plain multiplier — "the factor by which the measured TF
 * must be multiplied to give the actual values" — not a sensitivity. The unit
 * is kept as a pair, not a string, so the x(iω) transform can move the
 * numerator along `m → m/s → m/s²`. An empty `num`/`den` means "no unit
 * stated": the axis then keeps its plain `|H|`.
 */
export interface TfCalLine {
  factor: number;
  num: string;
  den: string;
}

/**
 * A set's transfer-function calibration: a factor on the RATIO, for when the
 * TF can be calibrated but the two transducers cannot — 3C6's free mass,
 * where `|a/F| = 1/m` is known though neither the accelerometer's nor the
 * hammer's sensitivity is.
 *
 * When a line is set it REPLACES `cal[out]/cal[in]` (the ratio the channel
 * calibration implies) for that TF line — in the TF view, the modal fit,
 * Best Match and the saved `TfData` — while the time and spectrum views keep
 * the channel calibration: it calibrates the ratio, not either sensor.
 *
 * `lines` is indexed by SOURCE channel, like `calFactors`; the input
 * channel's slot is always `null` (it has no TF line). `chIn` records the
 * input the factors were set against: the same numbers against another input
 * would be a different ratio, so they do not apply there (`tfCalLine`).
 */
export interface TfCal {
  chIn: number | null;
  lines: (TfCalLine | null)[];
}

/**
 * Coerce a stored TF calibration into a clean {@link TfCal} for a set of
 * `nCh` source channels, or `null` when there is nothing usable in it.
 *
 * Accepts the persisted form (`{ ch_in, lines }`, see {@link tfCalToUi}) or
 * the in-memory one (`{ chIn, lines }`). A line survives only with a finite,
 * non-zero `factor`; missing units become `''`. `lines` is padded or
 * truncated to `nCh`, the input channel's slot is cleared, and an input
 * channel the set does not have voids the whole thing.
 */
export function normalizeTfCal(raw: unknown, nCh: number): TfCal | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const ci = r.ch_in !== undefined ? r.ch_in : r.chIn;
  let chIn: number | null;
  if (ci === null || ci === undefined) chIn = null;
  else if (typeof ci === 'number' && Number.isInteger(ci) && ci >= 0 && ci < nCh) chIn = ci;
  else return null;
  const src = Array.isArray(r.lines) ? r.lines : [];
  const lines: (TfCalLine | null)[] = new Array(Math.max(0, nCh)).fill(null);
  let any = false;
  for (let ch = 0; ch < lines.length; ch++) {
    if (ch === chIn) continue;
    const l = src[ch] as Record<string, unknown> | null | undefined;
    if (!l || typeof l !== 'object') continue;
    const factor = Number(l.factor);
    if (l.factor === null || l.factor === undefined || !Number.isFinite(factor) || factor === 0) continue;
    lines[ch] = {
      factor,
      num: typeof l.num === 'string' ? l.num : '',
      den: typeof l.den === 'string' ? l.den : '',
    };
    any = true;
  }
  return any ? { chIn, lines } : null;
}

/** The persisted (`.dvma` ui-state, snake_case) form of a {@link TfCal}. */
export function tfCalToUi(c: TfCal): {
  ch_in: number | null; lines: ({ factor: number; num: string; den: string } | null)[];
} {
  return {
    ch_in: c.chIn,
    lines: c.lines.map((l) => (l ? { factor: l.factor, num: l.num, den: l.den } : null)),
  };
}

/**
 * The TF calibration line that applies to source channel `ch` of a transfer
 * function whose input is `chIn`, or `null` — none set, or set against a
 * different input channel (whose ratio this is not).
 */
export function tfCalLine(
  c: TfCal | null | undefined, ch: number, chIn: number | null,
): TfCalLine | null {
  if (!c || c.chIn !== chIn) return null;
  return c.lines[ch] ?? null;
}
