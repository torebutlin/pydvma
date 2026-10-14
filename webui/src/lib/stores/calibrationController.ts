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
import type { TfCalibrationInfo } from '../analysis/actions';
import type { TfCalLine } from '../model/calibration';

/** The calibration operations the tray needs — a subset of the actions API. */
export interface CalibrationController {
  /** Persisted per-channel factors + engineering units for a set.
   *  `sourceIsVolts` says what the stored samples ARE, so the Calibrate
   *  dialog can name the sensitivity's numerator (V/unit vs FS/unit). */
  getCalibration: (setId: number) => {
    factors: number[]; units: string[]; sourceIsVolts?: boolean;
  };
  /** Persist a set's cal factors (plus optional per-channel units). */
  setCalFactors: (setId: number, factors: number[], units?: readonly string[]) => void;
  /** A set's transfer-function calibration (one row per TF line), or `null`
   *  when it has no TF. Optional so a channels-only host keeps working. */
  getTfCalibration?: (setId: number) => TfCalibrationInfo | null;
  /** Set a set's transfer-function calibration, indexed by SOURCE channel;
   *  a `null` line means "use the channel calibration". */
  setTfCalibration?: (setId: number, lines: readonly (TfCalLine | null)[]) => void;
}

/** Current app's calibration API, or `null` before any actions instance boots. */
export const calibrationController = writable<CalibrationController | null>(null);
