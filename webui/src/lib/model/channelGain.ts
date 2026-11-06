/**
 * Pure helpers behind Setup's per-channel gain rows, for an interface with a
 * preamp per input (the Audient iD44): which channels get a row, what each
 * row offers, the full scale a row implies, how to word the optical and
 * loopback channel ranges, and when to move to the interface's preferred rate.
 * Node-testable; no stores, no DOM.
 */
import {
  derivedFullScaleVolts,
  type BridgeConfig,
  type DeviceCapsEntry,
  type InputMode,
} from '../audio/provider';

/** One analogue input's row in Setup. `ch` is zero-based. */
export interface ChannelGainRow {
  ch: number;
  role: string;
  /** Modes this channel has (`input_modes` minus modes other channels only have). */
  modes: InputMode[];
  /** `[min, max]` gain in dB per mode this channel has. */
  gainRange: Record<string, [number, number]>;
  /** Whether the interface's pad can be engaged on this channel. */
  padAvailable: boolean;
}

/**
 * Rows for the ANALOGUE channels among the first `channelCount`: optical
 * (ADAT) and loopback inputs carry no preamp and get none. `roles` is the
 * device's `channel_roles`; a channel past its end counts as analogue only
 * when no roles are published at all.
 */
export function channelRows(
  caps: DeviceCapsEntry,
  channelCount: number,
  roles: string[],
): ChannelGainRow[] {
  const rows: ChannelGainRow[] = [];
  const all = (caps.input_modes ?? []) as InputMode[];
  for (let ch = 0; ch < channelCount; ch++) {
    const role = roles.length ? roles[ch] : 'analogue';
    if (role !== 'analogue') continue;
    const modes = all.filter((m) => {
      const only = caps.mode_channels?.[m];
      return !Array.isArray(only) || only.includes(ch);
    });
    const gainRange: Record<string, [number, number]> = {};
    for (const m of modes) {
      const r = caps.gain_range_db?.[m];
      if (r) gainRange[m] = r;
    }
    const padOk = typeof caps.pad_db === 'number' && caps.pad_db > 0;
    rows.push({ ch, role, modes, gainRange, padAvailable: padOk });
  }
  return rows;
}

/**
 * Full scale in volts peak for one row at a stated gain, mode and pad, or
 * `null` with no gain. The arithmetic is {@link derivedFullScaleVolts}'s
 * (the server's `dBu - (gain - min_gain) + pad`), not a second copy.
 */
export function rowFullScaleVolts(
  caps: DeviceCapsEntry,
  row: ChannelGainRow,
  gainDb: number | null,
  mode: InputMode,
  pad: boolean,
): number | null {
  if (!row.modes.includes(mode)) return null;
  return derivedFullScaleVolts(caps, gainDb, mode, pad && row.padAvailable);
}

/**
 * The 1-based inclusive range of channels with `role` among the first
 * `channelCount`, or `null` when there are none. Assumes the role's
 * channels are contiguous (they are on every profiled interface).
 */
export function roleRange(
  roles: string[],
  role: string,
  channelCount: number,
): [number, number] | null {
  let first = -1;
  let last = -1;
  for (let i = 0; i < Math.min(roles.length, channelCount); i++) {
    if (roles[i] !== role) continue;
    if (first < 0) first = i;
    last = i;
  }
  return first < 0 ? null : [first + 1, last + 1];
}

/** The optical (ADAT) input range, 1-based inclusive; see {@link roleRange}. */
export function opticalRange(roles: string[], channelCount: number): [number, number] | null {
  return roleRange(roles, 'optical', channelCount);
}

/** "channel 5" or "channels 5–20" for a 1-based inclusive range. */
export function rangeText([a, b]: [number, number]): string {
  return a === b ? `channel ${a}` : `channels ${a}–${b}`;
}

/**
 * Whether choosing this device should move the sample rate to its preferred
 * one: the device states one, the current rate is not it, the hardware can run
 * it, and no digital low-pass is on (that chain captures at the device maximum
 * and resamples, so the stated rate is deliberate).
 */
export function shouldUsePreferredFs(
  caps: DeviceCapsEntry | null | undefined,
  fs: number,
  hardwareRates: number[],
  lpfOn: boolean,
): boolean {
  const pref = caps?.preferred_fs;
  if (typeof pref !== 'number' || !(pref > 0) || lpfOn) return false;
  return fs !== pref && hardwareRates.includes(pref);
}

/**
 * The bridge-config patch that drops per-channel (list) gain, mode and pad
 * once the selected device has no gain per channel: a stale iD44 list sent to
 * a 2i2 makes the server refuse ("has no input pad"). Lists are kept only
 * while `per_channel_gain`; an empty object means nothing to reset.
 */
export function staleChannelSettingsReset(
  caps: DeviceCapsEntry | null | undefined,
  cfg: BridgeConfig,
): Partial<BridgeConfig> {
  if (caps?.per_channel_gain === true) return {};
  const patch: Partial<BridgeConfig> = {};
  if (Array.isArray(cfg.inputGainDb)) patch.inputGainDb = undefined;
  if (Array.isArray(cfg.inputMode)) patch.inputMode = undefined;
  if (Array.isArray(cfg.inputPad)) patch.inputPad = undefined;
  return patch;
}
