/**
 * carriedCal.ts — calibrations carried forward to new recordings (opt-in).
 *
 * A measurement-mic workflow calibrates each channel once (a spec-sheet
 * sensitivity or a calibrator tone) and then makes many recordings. Ticking
 * "use for new recordings too" in the Calibrate dialog files each applied
 * channel's calibration (sensitivity, unit and how it was obtained) under the
 * calibrated set's DEVICE; every later capture from that device then arrives
 * already calibrated (`actions.addRecordedSet`), its provenance marked
 * `carried`. Nobody who leaves the tick alone sees any change.
 *
 * pydvma cannot read a gain knob, so a calibration carried to a recording
 * whose STATED gain, input mode or pad differs from the one it was made at is
 * applied with a warning ({@link carryWarnings}), never refused and never
 * silently trusted.
 *
 * Persisted per browser in `localStorage['pydvma.carriedCal.v1']`. Every
 * storage access is guarded: with storage blocked, full or absent (a private
 * window, the node test env) the store works in memory for the session.
 */
import { get, writable } from 'svelte/store';
import type { ChannelCalibration } from '../model/calibration';
import type { BridgeCaps } from '../audio/provider';
import type { AudioInputDevice } from '../audio/source';

/** localStorage key holding the carried calibrations (versioned). */
export const CARRIED_CAL_KEY = 'pydvma.carriedCal.v1';

/** One channel's calibration, kept for new recordings from its device. */
export type CarriedChannelCal = {
  /** Stored units per engineering unit (the dialog's sensitivity). */
  sensitivity: number;
  unit: string;
  /** How the calibration was obtained, as saved with the calibrated set. */
  provenance: ChannelCalibration;
};

/** Carried calibrations: device key → zero-based channel → entry. */
export type CarriedCalMap = Record<string, Record<number, CarriedChannelCal>>;

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** The page's localStorage, or null where it is absent or blocked. */
function defaultStorage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

const finite = (x: unknown): number | null =>
  typeof x === 'number' && Number.isFinite(x) ? x : null;
const text = (x: unknown): string | null => (typeof x === 'string' ? x : null);

/** A stored provenance coerced to the `ChannelCalibration` shape. */
function cleanProvenance(v: unknown, sensitivity: number, unit: string): ChannelCalibration | null {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
  const p = v as Record<string, unknown>;
  const r = p.reference && typeof p.reference === 'object' ? p.reference as Record<string, unknown> : null;
  const level = finite(r?.level);
  const freq = finite(r?.freq);
  const levelUnit = text(r?.level_unit);
  return {
    method: p.method === 'reference_tone' ? 'reference_tone' : 'sensitivity',
    date: text(p.date) ?? '',
    sensitivity,
    unit,
    reference: level !== null && freq !== null && levelUnit !== null
      ? { level, level_unit: levelUnit, freq } : null,
    gain_db: finite(p.gain_db),
    input_mode: text(p.input_mode),
    pad: typeof p.pad === 'boolean' ? p.pad : null,
    device: text(p.device),
    note: text(p.note) ?? '',
    carried: p.carried === true,
  };
}

/** A usable entry (finite positive sensitivity, a unit, a provenance), or null. */
function cleanEntry(v: unknown): CarriedChannelCal | null {
  if (!v || typeof v !== 'object' || Array.isArray(v)) return null;
  const e = v as Record<string, unknown>;
  const sensitivity = finite(e.sensitivity);
  const unit = text(e.unit);
  if (sensitivity === null || sensitivity <= 0 || !unit) return null;
  const provenance = cleanProvenance(e.provenance, sensitivity, unit);
  return provenance ? { sensitivity, unit, provenance } : null;
}

/** Whether `k` names a channel: a non-negative integer (or its string). */
function channelOf(k: string | number): number | null {
  const ch = Number(k);
  return Number.isInteger(ch) && ch >= 0 ? ch : null;
}

/** A parsed stored map, keeping only the usable entries. */
function cleanMap(v: unknown): CarriedCalMap {
  const out: CarriedCalMap = {};
  if (!v || typeof v !== 'object' || Array.isArray(v)) return out;
  for (const [dev, chans] of Object.entries(v as Record<string, unknown>)) {
    if (!dev || !chans || typeof chans !== 'object' || Array.isArray(chans)) continue;
    const kept: Record<number, CarriedChannelCal> = {};
    for (const [k, e] of Object.entries(chans as Record<string, unknown>)) {
      const ch = channelOf(k);
      const entry = ch === null ? null : cleanEntry(e);
      if (ch !== null && entry) kept[ch] = entry;
    }
    if (Object.keys(kept).length) out[dev] = kept;
  }
  return out;
}

/**
 * Create a carried-calibration store persisted through `storage` (the page's
 * localStorage by default). Subscribe for the whole map; `set` files one
 * channel's entry under a device key, `clear` forgets one device (or all,
 * with no key), `forDevice` reads one device's entries. A storage that is
 * absent or throws on any call is ignored: the store keeps working in memory.
 *
 * @param storage Returns the storage to use, or null for none; may throw.
 */
export function createCarriedCal(storage: () => StorageLike | null | undefined = defaultStorage) {
  function load(): CarriedCalMap {
    try {
      const raw = storage()?.getItem(CARRIED_CAL_KEY);
      return raw ? cleanMap(JSON.parse(raw)) : {};
    } catch {
      return {};
    }
  }
  function persist(map: CarriedCalMap): void {
    try {
      const s = storage();
      if (!s) return;
      if (Object.keys(map).length) s.setItem(CARRIED_CAL_KEY, JSON.stringify(map));
      else s.removeItem(CARRIED_CAL_KEY);
    } catch {
      /* storage full or blocked: the in-memory copy still holds */
    }
  }

  const store = writable<CarriedCalMap>(load());

  /**
   * Keep `entry` for channel `ch` of new recordings from `deviceKey`,
   * replacing any earlier one. An empty key, a negative or fractional
   * channel, or an entry without a finite positive sensitivity, a unit and a
   * provenance is ignored rather than stored.
   */
  function set(deviceKey: string, ch: number, entry: CarriedChannelCal): void {
    const c = channelOf(ch);
    const clean = cleanEntry(entry);
    if (!deviceKey || c === null || !clean) return;
    const map = get(store);
    const next = { ...map, [deviceKey]: { ...(map[deviceKey] ?? {}), [c]: clean } };
    store.set(next);
    persist(next);
  }

  /** Forget the carried calibration of one device, or of every device. */
  function clear(deviceKey?: string): void {
    const map = get(store);
    let next: CarriedCalMap;
    if (deviceKey === undefined) next = {};
    else {
      if (!(deviceKey in map)) return;
      next = { ...map };
      delete next[deviceKey];
    }
    store.set(next);
    persist(next);
  }

  /** The channels carried for one device (an empty record when none). */
  function forDevice(deviceKey: string): Record<number, CarriedChannelCal> {
    return { ...(get(store)[deviceKey] ?? {}) };
  }

  return { subscribe: store.subscribe, set, clear, forDevice };
}

export type CarriedCalStore = ReturnType<typeof createCarriedCal>;

/** The app's carried calibrations (one per page, persisted per browser). */
export const carriedCal = createCarriedCal();

/**
 * The device key a set's calibration is carried under: the `device_name` its
 * capture recorded (the identity, since a device index moves whenever the
 * enumeration changes), else its `device_driver`, else `''` (no device known:
 * nothing is carried).
 *
 * @param settings The set's stored capture settings.
 */
export function deviceKeyFor(settings: unknown): string {
  const s = (settings && typeof settings === 'object' ? settings : {}) as Record<string, unknown>;
  if (typeof s.device_name === 'string' && s.device_name) return s.device_name;
  if (typeof s.device_driver === 'string' && s.device_driver) return s.device_driver;
  return '';
}

/**
 * The name of the input device a capture from `deviceId` comes from, stamped
 * on the capture's settings as `device_name`: on the bridge the server's
 * name for the device (`device_caps[deviceId].name`, or the default input's
 * for an unset device); in the browser the device's label, once permission
 * has made it a real one. `null` when unknown.
 *
 * @param caps The bridge's capability document, or null on the Web Audio path.
 * @param devices The enumerated input devices (browser labels).
 * @param deviceId The selected input device ('' = the default).
 */
export function captureDeviceName(
  caps: BridgeCaps | null, devices: readonly AudioInputDevice[], deviceId: string,
): string | null {
  if (caps) {
    const n = deviceId ? caps.device_caps?.[deviceId]?.name : caps.default_input?.name;
    return typeof n === 'string' && n ? n : null;
  }
  const d = devices.find((x) => x.deviceId === (deviceId || 'default'));
  return d && d.hasLabel && d.label ? d.label : null;
}

/**
 * The device key a capture from the selected device will be filed under, so
 * Setup can say what will be carried: {@link captureDeviceName}, else the
 * driver the capture records (`web_audio` in the browser, the `<driver>` of a
 * bridge `<driver>:<index>` id).
 *
 * @param caps The bridge's capability document, or null on the Web Audio path.
 * @param devices The enumerated input devices.
 * @param deviceId The selected input device ('' = the default).
 */
export function selectedDeviceKey(
  caps: BridgeCaps | null, devices: readonly AudioInputDevice[], deviceId: string,
): string {
  const name = captureDeviceName(caps, devices, deviceId);
  if (name) return name;
  if (!caps) return 'web_audio';
  if (!deviceId) return caps.default_input?.driver ?? '';
  return deviceId.split(':')[0];
}

const fmtDb = (g: number) => String(Math.round(g * 100) / 100);

/**
 * Why a calibration carried to a new recording may not hold: one message for
 * each of the stated gain, input mode and pad that differs between the
 * calibration (`entry.provenance`) and the new recording (`now`, from
 * `provenanceFromSet`), e.g. `"channel 1: calibrated at gain 60 dB, this
 * recording states 50 dB"`. A gain unstated at either end cannot be compared,
 * which is said too (`"channel 1: gain not stated, so pydvma cannot tell
 * whether it moved"`). An empty list when everything matches.
 *
 * @param entry The carried calibration.
 * @param now The new recording's stated gain, mode and pad for this channel.
 * @param ch Zero-based channel, for the message.
 */
export function carryWarnings(
  entry: CarriedChannelCal,
  now: Pick<ChannelCalibration, 'gain_db' | 'input_mode' | 'pad'>,
  ch: number,
): string[] {
  const c = `channel ${ch + 1}`;
  const was = entry.provenance;
  const out: string[] = [];
  if (was.gain_db === null || now.gain_db === null) {
    out.push(`${c}: gain not stated, so pydvma cannot tell whether it moved`);
  } else if (Math.abs(was.gain_db - now.gain_db) > 1e-9) {
    out.push(`${c}: calibrated at gain ${fmtDb(was.gain_db)} dB, this recording states ${fmtDb(now.gain_db)} dB`);
  }
  if (was.input_mode !== now.input_mode) {
    const before = was.input_mode === null ? 'with no input mode stated' : `in ${was.input_mode} mode`;
    const after = now.input_mode === null ? 'none' : now.input_mode;
    out.push(`${c}: calibrated ${before}, this recording states ${after}`);
  }
  if (was.pad !== now.pad) {
    const before = was.pad === null ? 'not stated' : was.pad ? 'on' : 'off';
    const after = now.pad === null ? 'does not state it' : `states it ${now.pad ? 'on' : 'off'}`;
    out.push(`${c}: calibrated with the pad ${before}, this recording ${after}`);
  }
  return out;
}

/**
 * Setup's one-line summary of what a device carries, e.g. `"calibration
 * carried for channels 1, 2 (Pa)"` (channels one-based, units in channel
 * order without repeats), or null when it carries nothing.
 *
 * @param entries One device's carried channels (`carriedCal.forDevice`).
 */
export function carriedNote(entries: Record<number, CarriedChannelCal>): string | null {
  const chans = Object.keys(entries).map(Number).filter((c) => channelOf(c) !== null).sort((a, b) => a - b);
  if (!chans.length) return null;
  const units = [...new Set(chans.map((c) => entries[c].unit))];
  const word = chans.length === 1 ? 'channel' : 'channels';
  return `calibration carried for ${word} ${chans.map((c) => c + 1).join(', ')} (${units.join(', ')})`;
}
