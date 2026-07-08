/**
 * SourceProvider seam (Wave B — the `pydvma serve` bridge).
 *
 * The acquisition stores (`acquire.ts`, `monitor.ts`) used to import the
 * Web Audio functions from `source.ts` DIRECTLY, hard-wiring the browser
 * soundcard path.  Wave B adds a second acquisition backend — a local
 * `pydvma serve` process reached over a WebSocket — that can drive REAL
 * measurement hardware (soundcard, NI-DAQ) on the user's machine.
 *
 * To let one UI drive either backend, both are hidden behind this small
 * `SourceProvider` interface, whose surface is EXACTLY the four functions
 * the stores need from `source.ts`:
 *
 *   - `capabilities()`     — bridge feature/device report (null for Web Audio)
 *   - `enumerateInputDevices()`
 *   - `startRecording(cfg)`
 *   - `startMonitor(cfg, ondata)`
 *
 * `WebAudioProvider` wraps `source.ts` verbatim (the default, so nothing
 * else changes when no bridge is present).  `BridgeProvider` (bridge.ts)
 * implements the same surface over one WebSocket.  The stores take a
 * provider (defaulting to Web Audio); tests inject a fake provider.
 *
 * The `source.ts` types (`RecordConfig`, `Recording`, `MonitorHandle`, …)
 * are FROZEN and re-exported here so both providers — and every consumer —
 * share one vocabulary.
 */
import {
  enumerateInputDevices as webEnumerateInputDevices,
  startRecording as webStartRecording,
  startMonitor as webStartMonitor,
  type AudioInputDevice,
  type RecordConfig,
  type MonitorCallback,
  type MonitorHandle,
  type RecordingHandle,
} from './source';

// Re-export the frozen source types so consumers can import them from the
// provider seam without reaching into source.ts.
export type {
  AudioInputDevice,
  RecordConfig,
  Recording,
  RecordingHandle,
  MonitorChunk,
  MonitorCallback,
  MonitorHandle,
} from './source';

// ---- bridge capability / config types ----

/** One NI device as enumerated by `pydvma._ni_backend.enumerate_devices`. */
export interface NiDeviceEntry {
  name: string;
  product_type: string;
  is_chassis: boolean;
  ai_channel_count: number;
  ao_channel_count: number;
  module_names: string[];
  module_ai_counts: Record<string, number>;
  module_ao_counts: Record<string, number>;
}

/**
 * A per-device capability object as advertised by the server in
 * {@link BridgeCaps.device_caps}, keyed by `deviceId` (`<driver>:<index>`,
 * e.g. `'nidaq:0'`).  The server's objects are richer than this (driver /
 * index / name / candidate_rates / ai_max_rate / iepe_* / terminal_configs
 * …) and passed through verbatim; the fields declared here are the ones the
 * UI reads.  The primary source of the fs ladder and channel counts is the
 * top-level {@link BridgeCaps.fs_ladders} / {@link BridgeCaps.max_channels}
 * maps — see {@link deviceCapsFor}, which returns a NORMALIZED entry built
 * from all three maps.  All fields optional/additive.
 */
export interface DeviceCapsEntry {
  /** Discrete allowed sample rates in Hz (server `fs_ladders[deviceId]`). */
  fs_ladder?: number[];
  /** Maximum continuous sample rate in Hz (when no discrete ladder is given). */
  max_fs?: number;
  /** Maximum input (AI) channel count (`max_channels[deviceId].input`). */
  max_channels?: number;
  /** Whether THIS device can drive analog output (`device_caps[deviceId].ao`). */
  ao?: boolean;
  /**
   * Largest symmetric analog-INPUT voltage range in volts, from the server's
   * `device_caps[deviceId].ai_vmax` (NI only; `_ni_backend.device_capabilities`).
   * The UI clamps `VmaxNI` to this so a requested input range never exceeds
   * the hardware rail.  Absent on mock/soundcard (unreported).
   */
  ai_vmax?: number;
  /**
   * Largest symmetric analog-OUTPUT voltage range in volts, from the server's
   * `device_caps[deviceId].ao_vmax`.  The UI clamps `output_VmaxNI` and the
   * output-amplitude field to this — the NI 9260 rail is ±4.2426 V, BELOW the
   * pydvma default `output_VmaxNI = 5.0`, which would silently saturate output.
   * Absent on mock/soundcard.
   */
  ao_vmax?: number;
  /**
   * Human-readable device name (server `device_caps[deviceId].name`).  Used
   * as the label of the Acquire output-device select (see {@link outputDevices}).
   */
  name?: string;
}

/** Per-device input/output channel counts (`max_channels[deviceId]`). */
export interface DeviceChannelCounts {
  input: number;
  output: number;
}

/**
 * The `capabilities` document a `pydvma serve` bridge advertises on
 * `hello` (see `pydvma/serve.py` `build_capabilities`).  `null` is the
 * Web-Audio "there is no bridge" answer.
 *
 * Wave C made `fs_ladders` / `max_channels` **per-device maps** keyed by
 * `deviceId` (`'<driver>:<index>'`), and added a richer `device_caps` map.
 * `v` stays `1` (additive growth).  A legacy scalar/`null` `max_channels`
 * is still tolerated for back-compat; read per-device constraints through
 * {@link deviceCapsFor}, never these maps directly.
 */
export interface BridgeCaps {
  v: number;
  /** Which backends the server can drive: 'mock', 'soundcard', 'nidaq'. */
  backends: string[];
  devices: {
    soundcard: string[];
    nidaq: NiDeviceEntry[];
  };
  /** Per-device candidate sample rates keyed by `deviceId`. */
  fs_ladders: Record<string, number[]>;
  /**
   * Per-device `{input, output}` channel counts keyed by `deviceId`.  A
   * legacy scalar / `null` (v1's first cut) is tolerated.
   */
  max_channels: Record<string, DeviceChannelCounts> | number | null;
  pretrigger: boolean;
  ao: boolean;
  /**
   * Per-device capability map keyed by `deviceId` (`'nidaq:0'`,
   * `'soundcard:1'`, `'mock:0'`).  Additive (Wave C): absent → the UI uses
   * the free/global defaults.
   */
  device_caps?: Record<string, DeviceCapsEntry>;
}

/**
 * Container metadata carried out of a bridged `.dvma` capture so a bridged
 * set keeps its real provenance instead of being relabelled as a browser
 * `'web_audio'` set.  All optional; `null` on the Web Audio path (which has
 * no container to read).  Populated by {@link BridgeProvider.lastMeta} from
 * the logged `.dvma`'s single `TimeData` item (`meta` + `settings`).
 */
export interface BridgeRecordingMeta {
  /** `meta.test_name` — the capture's name from the server. */
  testName?: string;
  /** `meta.timestring` — the server's human timestamp. */
  timestring?: string;
  /** `meta.timestamp` — the server's ISO timestamp (decoded `__datetime__`). */
  timestamp?: string;
  /** `meta.units` — per-channel engineering units, if the server set them. */
  units?: unknown;
  /** `meta.channel_cal_factors` — per-channel calibration multipliers. */
  channelCalFactors?: number[];
  /** `settings.device_driver` — the backend actually used ('nidaq'/'soundcard'/'mock'). */
  deviceDriver?: string;
}

/** A pretrigger lifecycle event surfaced during a log (Wave C). */
export type LogStatusEvent = 'armed' | 'triggered' | 'timeout';

/**
 * The outcome of a `configure` round-trip: the sample rate the UI asked for
 * versus the rate the device actually resolved to.  DSA modules (e.g. the
 * NI 9234) snap an off-ladder request to the nearest legal step — measured:
 * request 8000 → get 8533.33 Hz — and the server adopts the TRUE rate, so
 * `requestedFs` and `configuredFs` can differ.  The UI surfaces the mismatch
 * as a non-error note so time/frequency axes are never read at the wrong
 * rate silently.  Emitted by the bridge for BOTH monitor and log configures.
 */
export interface ConfiguredInfo {
  /** The sample rate the UI requested (`RecordConfig.sampleRate`). */
  requestedFs: number;
  /** The sample rate the device resolved to (the `configured` status `fs`). */
  configuredFs: number;
  /** The resolved channel count (the `configured` status `channels`). */
  channels: number;
}

/**
 * Build the effective per-device constraints for a `deviceId` from the
 * server's three per-device maps: the fs ladder from `fs_ladders[deviceId]`,
 * the max INPUT channel count from `max_channels[deviceId].input`, the
 * per-device AO flag from `device_caps[deviceId].ao`, and the per-device
 * voltage rails `ai_vmax` / `ao_vmax` (NI only).  Falls back to an NI
 * device's `ai_channel_count` (from the enumerate entry) for the channel
 * cap when the `max_channels` map has no entry.  Returns `null` when nothing
 * is known (the UI then imposes no bridge-derived constraint).
 */
export function deviceCapsFor(
  caps: BridgeCaps | null,
  deviceId: string | undefined,
): DeviceCapsEntry | null {
  if (!caps || !deviceId) return null;
  const out: DeviceCapsEntry = {};

  const ladder = caps.fs_ladders?.[deviceId];
  if (Array.isArray(ladder) && ladder.length) out.fs_ladder = ladder;

  const mc = caps.max_channels;
  if (mc && typeof mc === 'object') {
    const entry = (mc as Record<string, DeviceChannelCounts>)[deviceId];
    if (entry && typeof entry.input === 'number') out.max_channels = entry.input;
  }

  const dc = caps.device_caps?.[deviceId];
  if (dc && typeof dc.ao === 'boolean') out.ao = dc.ao;
  // Voltage rails (NI only): pass through when the server reports a finite,
  // positive symmetric range so the UI can clamp VmaxNI / output_VmaxNI.
  if (dc && typeof dc.ai_vmax === 'number' && dc.ai_vmax > 0) out.ai_vmax = dc.ai_vmax;
  if (dc && typeof dc.ao_vmax === 'number' && dc.ao_vmax > 0) out.ao_vmax = dc.ao_vmax;

  // Fallback: NI enumerate entry's ai_channel_count when the map is absent.
  if (out.max_channels == null) {
    const i = deviceId.indexOf(':');
    const driver = i >= 0 ? deviceId.slice(0, i) : deviceId;
    const index = i >= 0 ? Number(deviceId.slice(i + 1)) : 0;
    if (driver === 'nidaq') {
      const ni = caps.devices.nidaq[index];
      if (ni && ni.ai_channel_count > 0) out.max_channels = ni.ai_channel_count;
    }
  }

  return Object.keys(out).length ? out : null;
}

/**
 * Whether the Acquire card's output (stimulus) group should render for the
 * given bridge + selected device.  Gated on the bridge advertising analog
 * output (`caps.ao`); a per-device `ao: false` override hides it for that
 * device.  The Web Audio path (null caps) is always hidden — browser output
 * stimulus is a later item.
 */
export function outputCapable(caps: BridgeCaps | null, deviceId?: string): boolean {
  if (!caps || !caps.ao) return false;
  const dc = deviceId ? caps.device_caps?.[deviceId] : undefined;
  return dc?.ao !== false;
}

/** An analog-output-capable device for the Acquire output-device select. */
export interface OutputDevice {
  /** `<driver>:<index>` id (matches the input `deviceId` encoding). */
  deviceId: string;
  /** Human-readable label (the device's `name`, or its id as a fallback). */
  label: string;
  /** Maximum output (AO) channel count, when the server reports one. */
  maxChannels?: number;
}

/**
 * The analog-output-capable devices a bridge advertises, for the Acquire
 * output group's device select.  Reads `device_caps` for every entry with
 * `ao: true` and pairs it with the output channel count from
 * `max_channels[deviceId].output` (when present).  Returns `[]` for the Web
 * Audio path (null caps) or a bridge with no AO — the select is then hidden.
 */
export function outputDevices(caps: BridgeCaps | null): OutputDevice[] {
  if (!caps || !caps.ao || !caps.device_caps) return [];
  const out: OutputDevice[] = [];
  const mc = caps.max_channels;
  for (const [deviceId, entry] of Object.entries(caps.device_caps)) {
    if (!entry || entry.ao !== true) continue;
    let maxChannels: number | undefined;
    if (mc && typeof mc === 'object') {
      const e = (mc as Record<string, DeviceChannelCounts>)[deviceId];
      if (e && typeof e.output === 'number' && e.output > 0) maxChannels = e.output;
    }
    out.push({ deviceId, label: entry.name ?? deviceId, maxChannels });
  }
  return out;
}

/**
 * pydvma's `MySettings` default full-scale voltage (`options.py`:
 * `VmaxNI = 5`, and `output_VmaxNI` defaults to `VmaxNI`).  When the webui
 * sends no explicit `VmaxNI` / `output_VmaxNI`, the server uses this — so it
 * is the "current value" a device rail below it must clamp against.
 */
export const PYDVMA_DEFAULT_VMAX = 5;

/**
 * Default pretrigger sample count used when the pretrigger is ARMED without an
 * explicit sample count set (a "bare arm").  100 matches pydvma's `MySettings`
 * default `chunk_size` (`options.py`), so a bare arm fits the default
 * pre-trigger context buffer WITHOUT forcing `chunk_size` up — the round-4
 * fix for the old default of 1000, which exceeded the default chunk size and
 * wastefully enlarged the buffer.  Editable directly on the Acquire arm
 * control and shared with Setup's pretrigger-samples field (both write the
 * same `BridgeConfig.pretrigSamples`).
 */
export const BARE_ARM_PRETRIG_SAMPLES = 100;

/**
 * Clamp a full-scale voltage to a device rail.  Returns `value` unchanged
 * when no finite positive `cap` is known (mock/soundcard, or a device that
 * did not report a range); otherwise the smaller of the two.  Used for both
 * the NI input range (`VmaxNI` vs `ai_vmax`) and the output range /
 * amplitude (`output_VmaxNI` / `outputAmp` vs `ao_vmax`).
 */
export function clampVoltage(value: number, cap?: number): number {
  if (cap == null || !Number.isFinite(cap) || cap <= 0) return value;
  return value > cap ? cap : value;
}

/**
 * Bridge-only configuration merged into the next `configure` message as
 * `MySettings` kwargs (the NI-DAQ group in SetupCard supplies these).
 * IGNORED by the Web Audio provider.  Field names mirror the camelCase
 * UI; the bridge maps them to the snake_case `MySettings` kwargs the
 * server whitelists.
 */
export interface BridgeConfig {
  /** Driver override; normally derived from the selected deviceId instead. */
  deviceDriver?: 'mock' | 'soundcard' | 'nidaq';
  deviceIndex?: number;
  inputChannelsSpec?: string;
  /** IEPE/ICP excitation current in amps — 0 or 0.002 (legal on NI 9234). */
  iepeExcitCurrentA?: number;
  /** Terminal configuration as a pydvma NI_mode token (e.g. 'DAQmx_Val_RSE'). */
  niMode?: string;
  /**
   * NI analog-INPUT full-scale voltage → `MySettings.VmaxNI` (±V passed as
   * min/max to `add_ai_voltage_chan`).  Clamped to the device's `ai_vmax`
   * rail before send.  Unset → the server's pydvma default (5 V).
   */
  vmaxNI?: number;
  /**
   * NI analog-OUTPUT full-scale voltage → `MySettings.output_VmaxNI`.
   * Clamped to the device's `ao_vmax` rail — the NI 9260 rail (±4.2426 V)
   * is below the pydvma default (5 V), which would silently saturate output.
   * Unset → the server's default (`= VmaxNI`).
   */
  outputVmaxNI?: number;
  /** Pretrigger sample count (null = no pretrigger / free-run capture). */
  pretrigSamples?: number | null;
  pretrigThreshold?: number;
  pretrigChannel?: number;
  /** Pretrigger timeout in seconds (Acquire arm area). */
  pretrigTimeout?: number;
  /**
   * Acquire-card "arm" switch: when true, `startRecording` sends the
   * pretrigger object on the `log` message so the capture waits for the
   * threshold crossing.  False (default) → `log.pretrigger = null`
   * (free-run capture), regardless of the pretrig params above.
   */
  pretrigArmed?: boolean;

  /**
   * Acquire-card output (stimulus) group.  When `outputEnabled`, the `log`
   * message carries `output = {type, amp, f1, f2}`, mapping to pydvma's
   * `Output_Signal_Settings` / `signal_generator`.  `outputType` uses the
   * signal_generator tokens: `'sweep'` (linear chirp f1→f2), `'uniform'`
   * (band-limited uniform/white noise; shown as "white" in the UI), or
   * `'gaussian'` (band-limited Gaussian noise).  Amplitude is in volts;
   * f1/f2 are the sweep endpoints or noise band corners in Hz.
   */
  outputEnabled?: boolean;
  outputType?: 'sweep' | 'uniform' | 'gaussian';
  outputAmp?: number;
  outputF1?: number;
  outputF2?: number;
  /**
   * Output stimulus duration in seconds → the `log.output.duration` key
   * (already accepted by the server's `_build_output_signal`).  Unset →
   * omitted, so the server defaults it to the capture duration (`stored_time`).
   */
  outputDuration?: number;
  /**
   * Selected output (AO) device as `<driver>:<index>` (e.g. `'nidaq:1'`),
   * mapped to `MySettings.output_device_driver` / `output_device_index` in the
   * configure message.  Unset → the server uses the input device / its
   * default output.  Only sent when `outputEnabled`.
   */
  outputDeviceId?: string;
  /**
   * Number of output (AO) channels → `MySettings.output_channels`.  Unset →
   * the server default (1).  Only sent when `outputEnabled`.
   */
  outputChannels?: number;
}

/**
 * The acquisition backend the stores drive.  `kind` lets consumers branch
 * UI (e.g. SetupCard renders the NI group only for a bridge that reports
 * nidaq).  `setConfig` / `dispose` are bridge-only extras (optional so the
 * canonical four-method surface stays exactly the source.ts one).
 */
export interface SourceProvider {
  readonly kind: 'webaudio' | 'bridge';
  /** Bridge feature/device report, or `null` for Web Audio / a dead bridge. */
  capabilities(): Promise<BridgeCaps | null>;
  enumerateInputDevices(): Promise<AudioInputDevice[]>;
  startRecording(cfg: RecordConfig): RecordingHandle;
  startMonitor(
    cfg: Omit<RecordConfig, 'durationS'>,
    ondata: MonitorCallback,
  ): Promise<MonitorHandle>;
  /** Bridge-only: stash NI/driver kwargs for the next configure (no-op on Web Audio). */
  setConfig?(cfg: BridgeConfig): void;
  /**
   * Bridge-only: register a persistent callback for log-scoped pretrigger
   * status events (`armed` / `triggered` / `timeout`) surfaced while a
   * capture runs.  No-op on Web Audio (which has no pretrigger).
   */
  onLogStatus?(cb: (event: LogStatusEvent) => void): void;
  /**
   * Bridge-only: register a persistent callback fired after every
   * `configure` round-trip (monitor OR log) with the requested vs
   * device-resolved sample rate, so the UI can surface a DSA coerced-fs
   * note.  No-op on Web Audio (no server-side coercion).
   */
  onConfigured?(cb: (info: ConfiguredInfo) => void): void;
  /**
   * Bridge-only: container metadata from the most recent logged capture
   * (device driver actually used, calibration, units, test name), or `null`.
   * Web Audio returns `null` (no container to read).
   */
  lastMeta?(): BridgeRecordingMeta | null;
  /** Bridge-only: release the socket + reject pending ops (no-op on Web Audio). */
  dispose?(): void;
}

// ---- Web Audio provider (wraps source.ts + browser output/pretrigger) ----

/**
 * Default browser output-stimulus amplitude when the user flips output on
 * without editing the field — matches the Acquire card's displayed default
 * (0.3).  A NORMALISED gain (0..1); the browser DAC has no calibrated volts.
 */
export const WEB_AUDIO_DEFAULT_OUTPUT_AMP = 0.3;

/**
 * Default absolute pretrigger threshold (normalised |x|) for the Web Audio
 * armed capture.  The browser has no Setup NI-group threshold control, so this
 * fixed default stands in — modest enough to sit above the digital noise floor
 * yet cross on a firm tap / a played tone.  (A dedicated browser threshold
 * control is a documented follow-up; a timeout falls back to an ordinary
 * capture, so an un-crossed arm still yields a full-length set.)
 */
export const WEB_AUDIO_DEFAULT_PRETRIG_THRESHOLD = 0.05;

/**
 * The default backend: the browser soundcard via the Web Audio API.  Wraps
 * `source.ts`; the pre-Wave-B capture behaviour is byte-for-byte unchanged
 * when no output/pretrigger is configured.  Round-5 item 10 lets it ALSO drive
 * a browser output stimulus + armed pretrigger — it stores the Acquire card's
 * {@link BridgeConfig} via {@link setConfig} (the SAME object the bridge uses)
 * and maps the browser-relevant fields into the Web-Audio `RecordConfig`
 * extensions on {@link startRecording}.  NI/driver fields are ignored.
 */
export class WebAudioProvider implements SourceProvider {
  readonly kind = 'webaudio' as const;

  /** Acquire output/pretrigger config (browser-relevant fields only). */
  private config: BridgeConfig = {};
  /** Pretrigger lifecycle sink (armed → triggered/timeout). */
  private statusCb: ((event: LogStatusEvent) => void) | null = null;

  /** Web Audio has no bridge capability document. */
  async capabilities(): Promise<BridgeCaps | null> {
    return null;
  }

  enumerateInputDevices(): Promise<AudioInputDevice[]> {
    return webEnumerateInputDevices();
  }

  /**
   * Stash the Acquire output/pretrigger config so the next capture can drive
   * the browser output stimulus + armed pretrigger.  Only the browser-relevant
   * fields are read (output {@link BridgeConfig.outputEnabled} group,
   * pretrigger {@link BridgeConfig.pretrigArmed} group); NI/driver kwargs are
   * ignored on this path.
   */
  setConfig(cfg: BridgeConfig): void {
    this.config = { ...cfg };
  }

  /** Register the pretrigger lifecycle sink (armed → triggered / timeout). */
  onLogStatus(cb: (event: LogStatusEvent) => void): void {
    this.statusCb = cb;
  }

  startRecording(cfg: RecordConfig): RecordingHandle {
    return webStartRecording({ ...cfg, ...this.recordExtras() });
  }

  startMonitor(
    cfg: Omit<RecordConfig, 'durationS'>,
    ondata: MonitorCallback,
  ): Promise<MonitorHandle> {
    return webStartMonitor(cfg, ondata);
  }

  /**
   * Map the stored {@link BridgeConfig} into the Web-Audio `RecordConfig`
   * extensions: an `output` stimulus when `outputEnabled`, a `pretrig` block
   * when `pretrigArmed`.  Frequency / amplitude defaults mirror the Acquire
   * card's displayed defaults so "flip on → Log" plays exactly what the
   * summary shows.  Amplitude is a normalised gain (clamped to ±1 at play
   * time).
   */
  private recordExtras(): Pick<RecordConfig, 'output' | 'pretrig'> {
    const c = this.config;
    const extras: Pick<RecordConfig, 'output' | 'pretrig'> = {};
    if (c.outputEnabled) {
      extras.output = {
        type: c.outputType ?? 'sweep',
        amp: c.outputAmp ?? WEB_AUDIO_DEFAULT_OUTPUT_AMP,
        f1: c.outputF1 ?? 10,
        f2: c.outputF2 ?? 500,
        durationS: c.outputDuration,
        deviceId: c.outputDeviceId,
        channels: c.outputChannels,
      };
    }
    if (c.pretrigArmed) {
      extras.pretrig = {
        channel: c.pretrigChannel ?? 0,
        threshold: c.pretrigThreshold ?? WEB_AUDIO_DEFAULT_PRETRIG_THRESHOLD,
        pretrigSamples: c.pretrigSamples ?? BARE_ARM_PRETRIG_SAMPLES,
        timeoutS: c.pretrigTimeout ?? 1.0,
        onStatus: this.statusCb ?? undefined,
      };
    }
    return extras;
  }
}

// ---- mode selection ----

/** Same-origin WebSocket URL for the bridge (`ws(s)://host/ws`). */
function defaultBridgeWsUrl(): string {
  if (typeof window === 'undefined') return 'ws://127.0.0.1:8760/ws';
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws`;
}

/**
 * Probe the same-origin `/config` document that `pydvma serve` publishes.
 * Returns true only when the fetch returns a JSON object promptly — the
 * "served by pydvma serve" signature.  A short abort timeout keeps a
 * static host (404 / index.html fallback) from stalling app boot.
 */
async function probeServeConfig(fetchImpl: typeof fetch): Promise<boolean> {
  const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), 1000) : null;
  try {
    const res = await fetchImpl('/config', ctrl ? { signal: ctrl.signal } : undefined);
    if (!res.ok) return false;
    const ctype = res.headers.get('content-type') ?? '';
    if (!ctype.includes('application/json')) return false;
    const body = await res.json();
    return body != null && typeof body === 'object' && !Array.isArray(body);
  } catch {
    return false;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/**
 * Fetch and parse the same-origin `/config` document `pydvma serve` publishes
 * (the served `--settings` MySettings JSON, or `{}` when none was given).
 * Returns the parsed object, or `null` when the fetch fails / is not JSON /
 * is empty — so a bridge boot can prefill Setup from it (`mapServeConfig`)
 * WITHOUT a second detection round-trip.  Same short abort timeout as the
 * detection probe so a static host never stalls boot.  `null` (not `{}`) is
 * returned for an empty object so the caller can skip the "settings loaded"
 * toast when there is nothing to load.
 */
export async function fetchServeConfig(
  fetchImpl?: typeof fetch,
): Promise<Record<string, unknown> | null> {
  const f = fetchImpl ?? (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : undefined);
  if (!f) return null;
  const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), 1000) : null;
  try {
    const res = await f('/config', ctrl ? { signal: ctrl.signal } : undefined);
    if (!res.ok) return null;
    const ctype = res.headers.get('content-type') ?? '';
    if (!ctype.includes('application/json')) return null;
    const body = await res.json();
    if (body == null || typeof body !== 'object' || Array.isArray(body)) return null;
    return Object.keys(body).length > 0 ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** Options for {@link selectProvider} (all injectable so it is testable). */
export interface SelectProviderOptions {
  /** Location search string (defaults to `window.location.search`). */
  search?: string;
  /** `window.__pydvma_bridge` override (defaults to the real global). */
  injected?: unknown;
  /** WebSocket factory forwarded to a constructed BridgeProvider. */
  wsFactory?: (url: string) => import('./bridge').WsLike;
  /** fetch impl for the `/config` probe (defaults to the global `fetch`). */
  fetchImpl?: typeof fetch;
}

/**
 * Pick the acquisition backend at app boot (App.svelte calls this before
 * `acquire.init`).  Precedence:
 *
 *   (a) `window.__pydvma_bridge` injected (string URL or `{url}` / truthy),
 *   (b) a `?bridge=ws://…` URL parameter,
 *   (c) a same-origin `/config` fetch that returns the serve signature,
 *
 * else the Web Audio provider.  (a)/(b) are synchronous; (c) is the
 * "opened through pydvma serve, no param" case and costs one short fetch.
 * The BridgeProvider fails soft — if its socket is dead, `capabilities()`
 * resolves `null` and the app leaves the live-source gate off.
 */
export async function selectProvider(
  opts: SelectProviderOptions = {},
): Promise<SourceProvider> {
  // Lazy import avoids a hard provider→bridge value cycle at module load.
  const { BridgeProvider } = await import('./bridge');

  const search = opts.search ?? (typeof window !== 'undefined' ? window.location.search : '');
  const params = new URLSearchParams(search);
  const bridgeParam = params.get('bridge');
  const injected = 'injected' in opts
    ? opts.injected
    : (typeof window !== 'undefined'
        ? (window as unknown as { __pydvma_bridge?: unknown }).__pydvma_bridge
        : undefined);

  // (a) injected URL / (b) URL param — either names an explicit ws endpoint.
  const injectedUrl = typeof injected === 'string'
    ? injected
    : (injected && typeof injected === 'object' && 'url' in injected
        ? String((injected as { url: unknown }).url)
        : undefined);
  const explicitUrl = bridgeParam || injectedUrl;
  if (explicitUrl) return new BridgeProvider(explicitUrl, opts.wsFactory);
  // (a) truthy-but-URL-less injection → same-origin bridge.
  if (injected) return new BridgeProvider(defaultBridgeWsUrl(), opts.wsFactory);

  // (c) same-origin /config probe.
  const fetchImpl = opts.fetchImpl
    ?? (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : undefined);
  if (fetchImpl && await probeServeConfig(fetchImpl)) {
    return new BridgeProvider(defaultBridgeWsUrl(), opts.wsFactory);
  }

  return new WebAudioProvider();
}
