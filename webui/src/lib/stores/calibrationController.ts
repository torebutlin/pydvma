/**
 * App-scoped calibration controller (Wave-A Task A2).
 *
 * The Calibrate dialog lives in the tray (`Tray.svelte`), but the calibration
 * READ/WRITE plumbing lives in the analysis `actions` closure (it owns the
 * `dataset` items + derived slices). `Tray` is mounted by `App.svelte` with a
 * fixed prop set, and this task must not edit `App.svelte` (a parallel agent
 * owns it). This tiny store decouples the two layers: `createActions`
 * PUBLISHES its calibration API here on construction, and `Tray` SUBSCRIBES to
 * discover it — no prop threading through `App` required.
 *
 * There is exactly one `actions` instance per page (App creates it once), so
 * the singleton holds that app's API. `Tray` still accepts explicit
 * `getCalibration` / `applyCalibration` props which, when supplied, take
 * precedence — so a future idiomatic `App` prop-pass (or a component test) can
 * bypass this store entirely.
 */
import { writable } from 'svelte/store';

/** The calibration operations the tray needs — a subset of the actions API. */
export interface CalibrationController {
  /** Persisted per-channel factors + engineering units for a set. */
  getCalibration: (setId: number) => { factors: number[]; units: string[] };
  /** Persist a set's cal factors (plus optional per-channel units). */
  setCalFactors: (setId: number, factors: number[], units?: readonly string[]) => void;
}

/** Current app's calibration API, or `null` before any actions instance boots. */
export const calibrationController = writable<CalibrationController | null>(null);
