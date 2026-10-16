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
 * PRESENT-NULL CLEARS, ABSENT LEAVES ALONE.  A key whose value is `null` (a
 * MySettings attribute that is None) clears that setting: `pretrig_samples:
 * null` disarms the trigger, `pretrig_threshold: null` falls back to the
 * app's 5 %-of-full-scale default, `fs: null` returns to the app's default
 * rate.  A key that is absent (only possible in a hand-written
 * `pydvma-serve --settings` file — python's `/config` always carries every
 * MySettings field) leaves the app's value as it is.  This matters for
 * `Session.apply_settings`, which pushes a document into an app that is
 * already set up; at boot the app holds its defaults anyway, so clearing is
 * a no-op there.
 *
 * Two non-MySettings keys carry the analysis defaults for captures:
 * `analysis_window` and `tf_averaging` (see {@link ServeConfigPatch.analysis}).
 *
 * The same mapping serves both callers in `App.svelte`: the boot prefill
 * (`applyServeConfig`, from `/config`) and the settings a notebook pushes
 * into an open tab (`apply_settings` frames).  The reciprocal fetch is
 * {@link fetchServeConfig} in `provider.ts`.  Field names verified against
 * `pydvma/options.py`'s `MySettings.__init__` (fs, channels, stored_time,
 * device_driver/index, pretrig_*, VmaxNI, output_* , iepe_excit_current_A,
 * NI_mode).
 */
import type { AudioInputDevice, BridgeConfig } from './provider';
import { DEFAULT_SETTINGS, type AcquireSettings, type AcquireStatus } from '../stores/acquire';
import type { BlaPhase } from '../stores/bla';

/** Window names a served document may set as the capture default. */
export const SERVED_WINDOWS = ['none', 'hann', 'hamming'] as const;
/** TF averaging modes a served document may set as the capture default. */
export const SERVED_TF_AVERAGING = ['none', 'within', 'across'] as const;

/**
 * Analysis defaults for captures from a served document.  A key that is
 * absent leaves the current default alone; `null` clears it back to the
 * app's own (`'hann'`, `'within'`).
 */
export interface ServedAnalysisDefaults {
  window?: (typeof SERVED_WINDOWS)[number] | null;
  tfAveraging?: (typeof SERVED_TF_AVERAGING)[number] | null;
}

/** The store patches a served MySettings maps to (all partial). */
export interface ServeConfigPatch {
  settings: Partial<AcquireSettings>;
  /** A key present with `undefined` CLEARS that field (patchBridge spreads it). */
  bridge: Partial<BridgeConfig>;
  analysis: ServedAnalysisDefaults;
  /** What could not be applied, in words (e.g. a device this server lacks). */
  notes: string[];
}

/**
 * A number, or a numeric string, as a number; anything else (null, '', a
 * boolean, an object) as NaN.  Plain `Number()` would read null and '' as 0,
 * which made a cleared `pretrig_threshold` a threshold of 0 — a trigger that
 * fires on the noise floor.
 */
function num(v: unknown): number {
  if (typeof v === 'number') return v;
  if (typeof v === 'string' && v.trim() !== '') return Number(v);
  return NaN;
}
/** Finite positive number, else undefined. */
function posNum(v: unknown): number | undefined {
  const n = num(v);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}
/** Finite number (any sign), else undefined. */
function finNum(v: unknown): number | undefined {
  const n = num(v);
  return Number.isFinite(n) ? n : undefined;
}
/** Non-negative integer, else undefined. */
function nonNegInt(v: unknown): number | undefined {
  const n = num(v);
  return Number.isFinite(n) && n >= 0 ? Math.round(n) : undefined;
}
/** Read `key` from a plain-object config (never throws on a non-object). */
function get(o: Record<string, unknown>, key: string): unknown {
  return Object.prototype.hasOwnProperty.call(o, key) ? o[key] : undefined;
}
/**
 * True when `key` is PRESENT and null — "clear this setting".  Python's
 * `str(None)`, `'None'`, counts too: it is what an old hand-written settings
 * file holds for a field someone meant to leave unset.
 */
function cleared(o: Record<string, unknown>, key: string): boolean {
  const v = get(o, key);
  return Object.prototype.hasOwnProperty.call(o, key) && (v === null || v === 'None');
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
 * `device_driver` + `device_index` to a real `deviceId`; a device the list
 * lacks is left out of the patch and named in `notes`.
 *
 * A present `null` clears (see the module docstring): a cleared Setup field
 * returns to {@link DEFAULT_SETTINGS}, a cleared bridge field is patched to
 * `undefined` so the app's own default applies, a cleared `device_driver`
 * selects the Default row, and a cleared `pretrig_samples` disarms.
 *
 * Output stimulus: read from a nested `output: {type, amp, f1, f2, duration}`
 * object OR flat `output_type` / `output_amp` / `output_f1` / `output_f2` /
 * `output_duration` keys (the stimulus shape is NOT a core MySettings field, so
 * a launch config that wants to arm the output carries it as an extra key —
 * accepted here).  The output group is enabled when any stimulus field has a
 * value, and `output: null` disables it; the AO device / channels / rail travel
 * via the MySettings `output_device_*` / `output_channels` / `output_VmaxNI`
 * fields.
 */
export function mapServeConfig(
  config: unknown, devices: AudioInputDevice[] = [],
): ServeConfigPatch | null {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return null;
  const c = config as Record<string, unknown>;
  const settings: Partial<AcquireSettings> = {};
  const bridge: Partial<BridgeConfig> = {};
  const analysis: ServedAnalysisDefaults = {};
  const notes: string[] = [];

  // ---- core input ----
  const fs = posNum(get(c, 'fs'));
  if (fs !== undefined) settings.sampleRate = fs;
  else if (cleared(c, 'fs')) settings.sampleRate = DEFAULT_SETTINGS.sampleRate;
  const channels = posNum(get(c, 'channels'));
  if (channels !== undefined) settings.channelCount = Math.round(channels);
  else if (cleared(c, 'channels')) settings.channelCount = DEFAULT_SETTINGS.channelCount;
  const dur = posNum(get(c, 'stored_time'));
  if (dur !== undefined) settings.durationS = dur;
  else if (cleared(c, 'stored_time')) settings.durationS = DEFAULT_SETTINGS.durationS;
  if (cleared(c, 'device_driver')) {
    settings.deviceId = DEFAULT_SETTINGS.deviceId;
  } else {
    const deviceId = matchDeviceId(get(c, 'device_driver'), get(c, 'device_index'), devices);
    if (deviceId !== undefined) settings.deviceId = deviceId;
    else if (typeof get(c, 'device_driver') === 'string' && devices.length) {
      notes.push(`${describeDevice(get(c, 'device_driver'), get(c, 'device_index'))} is not `
        + 'listed by this server, so Setup kept its input device.');
    }
  }

  // ---- pretrigger (arm when a sample count is present) ----
  // These land in exactly the `BridgeConfig` fields Setup's trigger group and
  // the Acquire arm switch read and write, so a served config shows up as a
  // filled-in, ARMED trigger rather than as settings nothing acts on. A null
  // count DISARMS: going from hammer settings back to noise must be safe.
  if (cleared(c, 'pretrig_samples')) {
    bridge.pretrigSamples = null;
    bridge.pretrigArmed = false;
  } else {
    const n = nonNegInt(get(c, 'pretrig_samples'));
    if (n !== undefined) { bridge.pretrigSamples = n; bridge.pretrigArmed = true; }
  }
  // A prefilled threshold is authoritative — the client only substitutes its
  // full-scale-derived default when NOBODY has stated one, which is what a
  // null asks for. Negative is not a level (the recorder compares |x|), so it
  // is ignored rather than sent.
  const pth = finNum(get(c, 'pretrig_threshold'));
  if (pth !== undefined && pth >= 0) bridge.pretrigThreshold = pth;
  else if (cleared(c, 'pretrig_threshold')) bridge.pretrigThreshold = undefined;
  const pch = nonNegInt(get(c, 'pretrig_channel'));
  if (pch !== undefined) bridge.pretrigChannel = pch;
  else if (cleared(c, 'pretrig_channel')) bridge.pretrigChannel = undefined;
  const pto = posNum(get(c, 'pretrig_timeout'));
  if (pto !== undefined) bridge.pretrigTimeout = pto;
  else if (cleared(c, 'pretrig_timeout')) bridge.pretrigTimeout = undefined;

  // ---- NI voltage rails + terminal config + IEPE ----
  const vmax = posNum(get(c, 'VmaxNI'));
  if (vmax !== undefined) bridge.vmaxNI = vmax;
  else if (cleared(c, 'VmaxNI')) bridge.vmaxNI = undefined;
  const oVmax = posNum(get(c, 'output_VmaxNI'));
  if (oVmax !== undefined) bridge.outputVmaxNI = oVmax;
  else if (cleared(c, 'output_VmaxNI')) bridge.outputVmaxNI = undefined;
  const niMode = get(c, 'NI_mode');
  if (typeof niMode === 'string' && niMode && niMode !== 'None') bridge.niMode = niMode;
  else if (cleared(c, 'NI_mode')) bridge.niMode = undefined;
  const iepeRaw = get(c, 'iepe_excit_current_A');
  const iepeFirst = Array.isArray(iepeRaw) ? iepeRaw[0] : iepeRaw;
  const iepe = finNum(iepeFirst);
  if (iepe !== undefined && iepe >= 0) bridge.iepeExcitCurrentA = iepe;
  else if (cleared(c, 'iepe_excit_current_A') || (Array.isArray(iepeRaw) && iepeFirst === null)) {
    bridge.iepeExcitCurrentA = undefined;
  }
  const inSpec = get(c, 'input_channels_spec');
  if (typeof inSpec === 'string' && inSpec && inSpec !== 'None') bridge.inputChannelsSpec = inSpec;
  else if (cleared(c, 'input_channels_spec')) bridge.inputChannelsSpec = undefined;

  // ---- output stimulus (nested `output` object or flat output_* keys) ----
  const outObj = get(c, 'output');
  const out = (outObj && typeof outObj === 'object' && !Array.isArray(outObj))
    ? outObj as Record<string, unknown>
    : {};
  const pick = (nested: string, flat: string): unknown => {
    const v = get(out, nested);
    return v !== undefined ? v : get(c, flat);
  };
  const outType = pick('type', 'output_type');
  const outAmp = pick('amp', 'output_amp');
  const outF1 = pick('f1', 'output_f1');
  const outF2 = pick('f2', 'output_f2');
  const outDur = pick('duration', 'output_duration');
  const stimulus = [outType, outAmp, outF1, outF2, outDur];
  if (cleared(c, 'output')) {
    bridge.outputEnabled = false;
  } else if (stimulus.some((v) => v !== undefined)) {
    // A null field clears to the card's default; only a real value enables.
    if (stimulus.some((v) => v !== undefined && v !== null)) bridge.outputEnabled = true;
    if (outType === 'sweep' || outType === 'uniform' || outType === 'gaussian') {
      bridge.outputType = outType;
    } else if (outType === null) bridge.outputType = undefined;
    const amp = finNum(outAmp);
    if (amp !== undefined) bridge.outputAmp = amp;
    else if (outAmp === null) bridge.outputAmp = undefined;
    const f1 = finNum(outF1);
    if (f1 !== undefined) bridge.outputF1 = f1;
    else if (outF1 === null) bridge.outputF1 = undefined;
    const f2 = finNum(outF2);
    if (f2 !== undefined) bridge.outputF2 = f2;
    else if (outF2 === null) bridge.outputF2 = undefined;
    const d = posNum(outDur);
    if (d !== undefined) bridge.outputDuration = d;
    else if (outDur === null) bridge.outputDuration = undefined;
    const outDev = matchDeviceId(get(c, 'output_device_driver'), get(c, 'output_device_index'), devices);
    if (outDev !== undefined) bridge.outputDeviceId = outDev;
    const outCh = posNum(get(c, 'output_channels'));
    if (outCh !== undefined) bridge.outputChannels = Math.round(outCh);
  }

  // ---- analysis defaults for captures (not MySettings fields) ----
  const win = get(c, 'analysis_window');
  if (typeof win === 'string' && (SERVED_WINDOWS as readonly string[]).includes(win)) {
    analysis.window = win as ServedAnalysisDefaults['window'];
  } else if (cleared(c, 'analysis_window')) analysis.window = null;
  const avg = get(c, 'tf_averaging');
  if (typeof avg === 'string' && (SERVED_TF_AVERAGING as readonly string[]).includes(avg)) {
    analysis.tfAveraging = avg as ServedAnalysisDefaults['tfAveraging'];
  } else if (cleared(c, 'tf_averaging')) analysis.tfAveraging = null;

  const any = Object.keys(settings).length > 0 || Object.keys(bridge).length > 0
    || Object.keys(analysis).length > 0;
  return any ? { settings, bridge, analysis, notes } : null;
}

/** `nidaq device 1`, `soundcard device 0`, `mock` — for a note. */
function describeDevice(driver: unknown, index: unknown): string {
  if (driver === 'mock') return 'the mock device';
  const idx = nonNegInt(index) ?? 0;
  return `${String(driver)} device ${idx}`;
}

/**
 * A short description of what a served document changed, for the toast:
 * `3000 Hz · 2 ch · 6 s · trigger armed · window none`.  Empty when the
 * patch touches none of the headline fields.
 */
export function describeServePatch(patch: ServeConfigPatch): string {
  const parts: string[] = [];
  const s = patch.settings;
  if (s.sampleRate !== undefined) parts.push(`${s.sampleRate} Hz`);
  if (s.channelCount !== undefined) parts.push(`${s.channelCount} ch`);
  if (s.durationS !== undefined) parts.push(`${s.durationS} s`);
  if (patch.bridge.pretrigArmed === true) parts.push('trigger armed');
  else if (patch.bridge.pretrigArmed === false) parts.push('trigger off');
  if (patch.analysis.window !== undefined) parts.push(`window ${patch.analysis.window ?? 'default'}`);
  if (patch.analysis.tfAveraging !== undefined) {
    parts.push(`TF averaging ${patch.analysis.tfAveraging ?? 'default'}`);
  }
  return parts.join(' · ');
}

/**
 * Why this tab cannot take pushed settings right now, or `null` when it can.
 * The server already refuses while a `log` is in flight on its side; this
 * covers what only the tab can see — a capture it has started, and a Nonlin
 * run, which is many captures with gaps between them where the server sees
 * nothing running.
 */
export function pushedSettingsRefusal(
  state: { acquireStatus: AcquireStatus; blaPhase: BlaPhase },
): string | null {
  if (state.acquireStatus === 'recording') {
    return 'a capture is in progress in the app (logging, or armed and waiting for its trigger)';
  }
  if (state.blaPhase === 'running' || state.blaPhase === 'analysing') {
    return 'a Nonlin run is in progress in the app';
  }
  return null;
}
