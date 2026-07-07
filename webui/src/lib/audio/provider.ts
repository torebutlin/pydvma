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
 * The `capabilities` document a `pydvma serve` bridge advertises on
 * `hello` (see `pydvma/serve.py` `build_capabilities`).  `null` is the
 * Web-Audio "there is no bridge" answer.
 */
export interface BridgeCaps {
  v: number;
  /** Which backends the server can drive: 'mock', 'soundcard', 'nidaq'. */
  backends: string[];
  devices: {
    soundcard: string[];
    nidaq: NiDeviceEntry[];
  };
  fs_ladders: Record<string, number[]>;
  max_channels: number | null;
  pretrigger: boolean;
  ao: boolean;
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
  /** Pretrigger sample count (null = no pretrigger / free-run capture). */
  pretrigSamples?: number | null;
  pretrigThreshold?: number;
  pretrigChannel?: number;
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
  /** Bridge-only: release the socket + reject pending ops (no-op on Web Audio). */
  dispose?(): void;
}

// ---- Web Audio provider (wraps source.ts verbatim) ----

/**
 * The default backend: the browser soundcard via the Web Audio API.  A
 * thin pass-through to `source.ts` so the pre-Wave-B behaviour is
 * byte-for-byte unchanged when no bridge is present.
 */
export class WebAudioProvider implements SourceProvider {
  readonly kind = 'webaudio' as const;

  /** Web Audio has no bridge capability document. */
  async capabilities(): Promise<BridgeCaps | null> {
    return null;
  }

  enumerateInputDevices(): Promise<AudioInputDevice[]> {
    return webEnumerateInputDevices();
  }

  startRecording(cfg: RecordConfig): RecordingHandle {
    return webStartRecording(cfg);
  }

  startMonitor(
    cfg: Omit<RecordConfig, 'durationS'>,
    ondata: MonitorCallback,
  ): Promise<MonitorHandle> {
    return webStartMonitor(cfg, ondata);
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
