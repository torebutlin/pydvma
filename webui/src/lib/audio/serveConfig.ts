/**
 * Launch-config prefill (round-6 Qt-parity): consume the `MySettings` JSON that
 * `pydvma-serve --settings file.json` publishes at `/config` and map it onto the
 * Setup / Acquire stores, so opening the browser UI through a configured server
 * starts with the maintainer's fs / channels / duration / device / pretrigger /
 * output already filled in — exactly as the old Qt logger consumed a
 * `MySettings`.  Until now the app used `/config` ONLY as a bridge-detection
 * signature (`provider.ts`); this module makes the app CONSUME it.
 *
 * PURE + node-testable: {@link mapServeConfig} takes the parsed config object
 * and the enumerated device list and returns store patches — it touches no
 * Svelte store, so a vitest can drive it with fake (incl. partial / garbage)
 * payloads.  Unknown / missing / malformed fields are skipped silently; only
 * recognised, well-typed values become patches.  The device is matched against
 * the enumerated list (`<driver>:<index>`, or `mock:0`) so a driver/index the
 * bridge does not actually expose is ignored rather than selecting a phantom.
 *
 * The maths of applying (once at boot, override defaults not later user edits)
 * lives in `App.svelte`; the reciprocal fetch is {@link fetchServeConfig} in
 * `provider.ts`.  Field names verified against `pydvma/options.py`'s
 * `MySettings.__init__` (fs, channels, stored_time, device_driver/index,
 * pretrig_*, VmaxNI, output_* , iepe_excit_current_A, NI_mode).
 */
import type { AudioInputDevice, BridgeConfig } from './provider';
import type { AcquireSettings } from '../stores/acquire';

/** The store patches a served MySettings maps to (both partial). */
export interface ServeConfigPatch {
  settings: Partial<AcquireSettings>;
  bridge: Partial<BridgeConfig>;
}

/** Finite positive number, else undefined. */
function posNum(v: unknown): number | undefined {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}
/** Finite number (any sign), else undefined. */
function finNum(v: unknown): number | undefined {
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}
/** Non-negative integer, else undefined. */
function nonNegInt(v: unknown): number | undefined {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined;
}
/** Read `key` from a plain-object config (never throws on a non-object). */
function get(o: Record<string, unknown>, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(o, key) ? o[key] : undefined;
}

/**
 * Build a `<driver>:<index>` deviceId from a MySettings driver/index pair and
 * return it ONLY when the enumerated `devices` list actually exposes it (so a
 * stale/foreign selection never picks a phantom device).  `mock` always maps to
 * `mock:0`; a missing index defaults to 0.
 */
function matchDeviceId(
  driver: unknown, index: unknown, devices: AudioInputDevice[],
): string | undefined {
  if (typeof driver !== 'string' || !driver) return undefined;
  const idx = driver === 'mock' ? 0 : (nonNegInt(index) ?? 0);
  const id = `${driver}:${idx}`;
  return devices.some((d) => d.deviceId === id) ? id : undefined;
}

/**
 * Map a served `MySettings` config object onto Acquire settings + bridge config
 * patches.  Returns `null` when `config` is not a usable object OR yields no
 * recognised field (so the caller can skip the toast).  `devices` is the
 * enumerated input-device list (from `acquire.devices`), used to resolve
 * `device_driver` + `device_index` to a real `deviceId`.
 *
 * Output stimulus: read from a nested `output: {type, amp, f1, f2, duration}`
 * object OR flat `output_type` / `output_amp` / `output_f1` / `output_f2` /
 * `output_duration` keys (the stimulus shape is NOT a core MySettings field, so
 * a launch config that wants to arm the output carries it as an extra key —
 * accepted here).  The output group is enabled when any stimulus field is
 * present; the AO device / channels / rail travel via the MySettings
 * `output_device_*` / `output_channels` / `output_VmaxNI` fields.
 */
export function mapServeConfig(
  config: unknown, devices: AudioInputDevice[] = [],
): ServeConfigPatch | null {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return null;
  const c = config as Record<string, unknown>;
  const settings: Partial<AcquireSettings> = {};
  const bridge: Partial<BridgeConfig> = {};

  // ---- core input ----
  const fs = posNum(get(c, 'fs'));
  if (fs !== undefined) settings.sampleRate = fs;
  const channels = posNum(get(c, 'channels'));
  if (channels !== undefined) settings.channelCount = Math.round(channels);
  const dur = posNum(get(c, 'stored_time'));
  if (dur !== undefined) settings.durationS = dur;
  const deviceId = matchDeviceId(get(c, 'device_driver'), get(c, 'device_index'), devices);
  if (deviceId !== undefined) settings.deviceId = deviceId;

  // ---- pretrigger (arm when a sample count is present) ----
  const pretrig = get(c, 'pretrig_samples');
  if (pretrig !== null && pretrig !== undefined && pretrig !== 'None') {
    const n = nonNegInt(pretrig);
    if (n !== undefined) { bridge.pretrigSamples = n; bridge.pretrigArmed = true; }
  }
  const pth = finNum(get(c, 'pretrig_threshold'));
  if (pth !== undefined) bridge.pretrigThreshold = pth;
  const pch = nonNegInt(get(c, 'pretrig_channel'));
  if (pch !== undefined) bridge.pretrigChannel = pch;
  const pto = posNum(get(c, 'pretrig_timeout'));
  if (pto !== undefined) bridge.pretrigTimeout = pto;

  // ---- NI voltage rails + terminal config + IEPE ----
  const vmax = posNum(get(c, 'VmaxNI'));
  if (vmax !== undefined) bridge.vmaxNI = vmax;
  const oVmax = posNum(get(c, 'output_VmaxNI'));
  if (oVmax !== undefined) bridge.outputVmaxNI = oVmax;
  const niMode = get(c, 'NI_mode');
  if (typeof niMode === 'string' && niMode) bridge.niMode = niMode;
  const iepeRaw = get(c, 'iepe_excit_current_A');
  const iepe = finNum(Array.isArray(iepeRaw) ? iepeRaw[0] : iepeRaw);
  if (iepe !== undefined && iepe >= 0) bridge.iepeExcitCurrentA = iepe;
  const inSpec = get(c, 'input_channels_spec');
  if (typeof inSpec === 'string' && inSpec) bridge.inputChannelsSpec = inSpec;

  // ---- output stimulus (nested `output` object or flat output_* keys) ----
  const outObj = get(c, 'output');
  const out = (outObj && typeof outObj === 'object' && !Array.isArray(outObj))
    ? outObj as Record<string, unknown>
    : {};
  const outType = get(out, 'type') ?? get(c, 'output_type');
  const outAmp = get(out, 'amp') ?? get(c, 'output_amp');
  const outF1 = get(out, 'f1') ?? get(c, 'output_f1');
  const outF2 = get(out, 'f2') ?? get(c, 'output_f2');
  const outDur = get(out, 'duration') ?? get(c, 'output_duration');
  const hasStimulus = [outType, outAmp, outF1, outF2, outDur].some((v) => v !== undefined);
  if (hasStimulus) {
    bridge.outputEnabled = true;
    if (outType === 'sweep' || outType === 'uniform' || outType === 'gaussian') {
      bridge.outputType = outType;
    }
    const amp = finNum(outAmp);
    if (amp !== undefined) bridge.outputAmp = amp;
    const f1 = finNum(outF1);
    if (f1 !== undefined) bridge.outputF1 = f1;
    const f2 = finNum(outF2);
    if (f2 !== undefined) bridge.outputF2 = f2;
    const d = posNum(outDur);
    if (d !== undefined) bridge.outputDuration = d;
    const outDev = matchDeviceId(get(c, 'output_device_driver'), get(c, 'output_device_index'), devices);
    if (outDev !== undefined) bridge.outputDeviceId = outDev;
    const outCh = posNum(get(c, 'output_channels'));
    if (outCh !== undefined) bridge.outputChannels = Math.round(outCh);
  }

  const any = Object.keys(settings).length > 0 || Object.keys(bridge).length > 0;
  return any ? { settings, bridge } : null;
}
