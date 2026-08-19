/**
 * BridgeProvider — the browser half of the `pydvma serve` local bridge.
 *
 * Implements the {@link SourceProvider} surface over ONE WebSocket that
 * speaks the serve protocol (`pydvma/serve.py`).  Text frames are JSON
 * control messages; binary frames are 20-byte-header + payload sample
 * chunks (`msgType=1`) or `.dvma` containers (`msgType=2`).  A monitor
 * chunk is decoded to the SAME {@link MonitorChunk} the Web Audio monitor
 * produces, so the monitor store consumes it byte-identically; a logged
 * capture arrives as a `.dvma` container that is parsed back into the SAME
 * {@link Recording} shape `source.ts` produces, so the unchanged
 * `acquire.record` → `recordingToItem` → `addRecordedSet` path ingests a
 * bridged set with no fork.
 *
 * Correlation: the serve protocol carries no request ids — responses are
 * matched to requests by TYPE.  The app issues control requests serially
 * (configure → start_monitor, configure → log), so a small FIFO of
 * predicate waiters settles each reply; an `error` frame rejects the head
 * waiter.  The socket is injectable ({@link WsLike} + a factory, mirroring
 * `worker/client.ts`'s WorkerLike) so tests drive a fake transport.
 *
 * Fail-soft: a socket error/close after open marks the provider dead,
 * rejects every pending op with a clear message, and makes
 * `capabilities()` resolve `null` so the app can fall back to Web Audio.
 * There is no auto-reconnect (lab-local single-user stance).
 */
import { readDvma } from '../codec/dvma';
import {
  BARE_ARM_PRETRIG_SAMPLES,
  CancelledError,
  defaultPretrigThreshold,
  effectiveFullScaleVolts,
} from './provider';
import type {
  AudioInputDevice,
  BridgeCaps,
  BridgeConfig,
  BridgeDefaultDevice,
  BridgeRecordingMeta,
  ConfiguredInfo,
  DeviceCapsEntry,
  DeviceChannelCounts,
  LogStatusEvent,
  MonitorCallback,
  MonitorHandle,
  MultisineStimulusConfig,
  NiDeviceEntry,
  OutputSpec,
  RecordConfig,
  Recording,
  RecordingHandle,
  SourceProvider,
} from './provider';

/** Status-frame events that belong to a log's pretrigger lifecycle. */
const LOG_STATUS_EVENTS: ReadonlySet<string> = new Set(['armed', 'triggered', 'timeout']);

/**
 * Status event the server sends INSTEAD of `log_result` + container when a
 * `cancel` arrives while a log is running.  There is no result to wait for
 * afterwards, so a client that only awaits `log_result` hangs for ever — the
 * lab-observed "Cancel does nothing".
 */
const CANCELLED_EVENT = 'cancelled';

/** pydvma's `MySettings` default `chunk_size` (the pretrigger context buffer). */
const PYDVMA_DEFAULT_CHUNK_SIZE = 100;

// ---- protocol constants (mirror pydvma/serve.py) ----

/** Magic byte at offset 0 of every binary frame (serve.py `MAGIC`). */
export const MAGIC = 0xdb;
/** Protocol version stamped in the header. */
export const PROTOCOL_VERSION = 1;
/** Binary msgType: an interleaved-float32 sample chunk. */
export const MSG_CHUNK = 1;
/** Binary msgType: a `.dvma` container (opaque zip bytes). */
export const MSG_CONTAINER = 2;
/** Fixed little-endian binary-frame header size in bytes. */
export const HEADER_SIZE = 20;

/** Decoded 20-byte binary-frame header. */
export interface FrameHeader {
  magic: number;
  ver: number;
  msgType: number;
  dtype: number;
  streamId: number;
  nChannels: number;
  seq: number;
  nSamples: number;
  fs: number;
}

/**
 * Decode the fixed 20-byte little-endian binary-frame header.
 *
 * Layout (see serve.py): `u8 magic | u8 ver | u8 msgType | u8 dtype |
 * u16 streamId | u16 nChannels | u32 seq | u32 nSamples | f32 fs`.
 * Throws when the frame is shorter than the header or the magic byte is
 * wrong (a corrupt / non-pydvma frame), so callers never trust a bad
 * header.
 */
export function decodeHeader(bytes: Uint8Array): FrameHeader {
  if (bytes.byteLength < HEADER_SIZE) {
    throw new Error(`frame shorter than the ${HEADER_SIZE}-byte header`);
  }
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const magic = dv.getUint8(0);
  if (magic !== MAGIC) {
    throw new Error(
      `bad magic byte 0x${magic.toString(16)} (expected 0x${MAGIC.toString(16)})`,
    );
  }
  return {
    magic,
    ver: dv.getUint8(1),
    msgType: dv.getUint8(2),
    dtype: dv.getUint8(3),
    streamId: dv.getUint16(4, true),
    nChannels: dv.getUint16(6, true),
    seq: dv.getUint32(8, true),
    nSamples: dv.getUint32(12, true),
    fs: dv.getFloat32(16, true),
  };
}

// ---- injectable WebSocket transport ----

/**
 * The slice of the browser WebSocket API the bridge depends on.  A real
 * `WebSocket` conforms structurally; tests inject a fake that records
 * sends and lets the test push frames + open/close/error events.
 */
export interface WsLike {
  readyState: number;
  binaryType: string;
  send(data: string | ArrayBufferLike | ArrayBufferView): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
  onclose: ((ev?: unknown) => void) | null;
}

/** Default factory: a real browser WebSocket (overridable for tests). */
function defaultWsFactory(url: string): WsLike {
  return new WebSocket(url) as unknown as WsLike;
}

// ---- helpers ----

interface Pending {
  match: (msg: Record<string, unknown>) => boolean;
  resolve: (msg: Record<string, unknown>) => void;
  reject: (err: Error) => void;
}

/** `soundcard:2` / `nidaq:0` / `mock:0` → `{driver, index}` (null for ''). */
function parseDeviceId(deviceId?: string): { driver: string; index: number } | null {
  if (!deviceId) return null;
  const i = deviceId.indexOf(':');
  if (i < 0) return null;
  const driver = deviceId.slice(0, i);
  const index = Number(deviceId.slice(i + 1));
  return { driver, index: Number.isFinite(index) ? index : 0 };
}

/** Widen any supported numeric array to a fresh Float64Array copy. */
function toFloat64(a: Float64Array | Float32Array | Uint8Array): Float64Array {
  const out = new Float64Array(a.length);
  out.set(a);
  return out;
}

/**
 * Parse `.dvma` container bytes into the same {@link Recording} shape the
 * Web Audio recorder produces (row-major (N,C) float64 + time axis).  Reads
 * the first TimeData item — a logged capture always has exactly one.  The
 * sample rate comes from the item's settings, falling back to the time
 * axis when absent.
 */
export function recordingFromDvma(bytes: Uint8Array): Recording {
  const ds = readDvma(bytes);
  const item = ds.items.find((it) => it.kind === 'TimeData');
  if (!item) throw new Error('bridge .dvma has no TimeData item');
  const td = item.arrays.time_data;
  const ta = item.arrays.time_axis;
  if (!td || !ta) throw new Error('bridge .dvma TimeData is missing time_data/time_axis');
  const nSamples = td.shape[0] ?? 0;
  const nChannels = td.shape.length > 1 ? td.shape[1] : 1;
  const data = toFloat64(td.data);
  const timeAxis = toFloat64(ta.data);
  let fs = Number(item.settings?.fs);
  if (!Number.isFinite(fs) || fs <= 0) {
    const span = timeAxis.length > 1 ? timeAxis[timeAxis.length - 1] - timeAxis[0] : 0;
    fs = span > 0 ? (timeAxis.length - 1) / span : 44100;
  }
  return { data, timeAxis, fs, nChannels, nSamples };
}

/**
 * Extract the provenance metadata from a bridged `.dvma` container so a
 * bridged set keeps its real identity (device driver actually used,
 * calibration, units, test name, timestamp) instead of being relabelled
 * `'web_audio'`.  Reads the single `TimeData` item's `meta` (unique_id /
 * units / channel_cal_factors / test_name / timestring / timestamp) and
 * `settings` (device_driver).  Returns `null` when the container carries
 * nothing worth preserving.  Values are already tag-decoded by
 * {@link readDvma} to plain JSON-safe scalars/lists, so they can be written
 * straight back into a JS-authored DvmaItem — except `unique_id`, whose
 * ORIGINAL tagged form is carried alongside as `uniqueIdRaw` so the id can be
 * re-emitted as the `{__uuid__}` python wrote (see `BridgeRecordingMeta`).
 */
export function recordingMetaFromDvma(bytes: Uint8Array): BridgeRecordingMeta | null {
  const ds = readDvma(bytes);
  const item = ds.items.find((it) => it.kind === 'TimeData');
  if (!item) return null;
  const meta = item.meta ?? {};
  const settings = item.settings ?? {};
  const out: BridgeRecordingMeta = {};
  if (typeof meta.unique_id === 'string' && meta.unique_id) {
    out.uniqueId = meta.unique_id;
    const raw = item.metaRaw?.unique_id;
    if (raw !== undefined && raw !== meta.unique_id) out.uniqueIdRaw = raw;
  }
  if (typeof meta.test_name === 'string') out.testName = meta.test_name;
  if (typeof meta.timestring === 'string') out.timestring = meta.timestring;
  if (typeof meta.timestamp === 'string') out.timestamp = meta.timestamp;
  if (meta.units != null) out.units = meta.units;
  if (Array.isArray(meta.channel_cal_factors)) {
    out.channelCalFactors = (meta.channel_cal_factors as unknown[]).map(Number);
  }
  if (settings && typeof (settings as Record<string, unknown>).device_driver === 'string') {
    out.deviceDriver = (settings as Record<string, unknown>).device_driver as string;
  }
  return Object.keys(out).length ? out : null;
}

// ---- the provider ----

export class BridgeProvider implements SourceProvider {
  readonly kind = 'bridge' as const;

  private readonly url: string;
  private readonly wsFactory: (url: string) => WsLike;
  private ws: WsLike | null = null;
  private connectPromise: Promise<void> | null = null;
  private dead = false;

  /** FIFO of JSON-reply waiters (matched by predicate; head rejected on error). */
  private pending: Pending[] = [];
  /** Live monitor sink; set while a monitor is running. */
  private onChunk: MonitorCallback | null = null;
  /** Log-capture container waiter (resolved by the msgType=2 frame). */
  private pendingContainer: { resolve: (b: Uint8Array) => void; reject: (e: Error) => void } | null = null;
  /** A container that arrived before its waiter was parked (ordering safety). */
  private bufferedContainer: Uint8Array | null = null;
  /** Cached capabilities (only successful lookups are cached). */
  private capsCache: BridgeCaps | null = null;
  /** NI/driver kwargs merged into every configure (set by SetupCard). */
  private extraConfig: BridgeConfig = {};
  /** Persistent sink for log-scoped pretrigger status events. */
  private logStatusCb: ((event: LogStatusEvent) => void) | null = null;
  /** Persistent sink for configure round-trips (requested vs resolved fs). */
  private configuredCb: ((info: ConfiguredInfo) => void) | null = null;
  /**
   * Settles the in-flight log with "the server cancelled it".  Set while a
   * `log` is outstanding; calling it also un-parks the `log_result` waiter,
   * which would otherwise sit in the FIFO and swallow the NEXT log's result.
   */
  private cancelWaiter: (() => void) | null = null;
  /**
   * CAPTURE clock for the in-flight log's `elapsed()`.  `null` start means
   * "not counting yet" — an armed pretrigger holds the progress bar at 0
   * while the recorder waits for the crossing, so a 2 s bar cannot sit
   * saturated through a 20 s wait and imply the capture already happened.
   * The `triggered` (or `timeout`) event starts it.
   */
  private logClock: { start: number | null } | null = null;
  /** Provenance metadata from the most recent logged capture. */
  private lastRecordingMeta: BridgeRecordingMeta | null = null;

  constructor(url: string, wsFactory: (url: string) => WsLike = defaultWsFactory) {
    this.url = url;
    this.wsFactory = wsFactory;
  }

  /** Stash NI/driver kwargs merged into the next configure message. */
  setConfig(cfg: BridgeConfig): void {
    this.extraConfig = { ...this.extraConfig, ...cfg };
  }

  /**
   * Register the persistent sink for log-scoped pretrigger status events
   * (`armed` / `triggered` / `timeout`).  These arrive as `status` frames
   * WHILE a `log` is awaiting `log_result`; they are not awaited by any
   * waiter, so the provider routes them here instead of dropping them.
   */
  onLogStatus(cb: (event: LogStatusEvent) => void): void {
    this.logStatusCb = cb;
  }

  /**
   * Register the persistent sink for configure round-trips.  Fired after
   * every `configured` status (monitor OR log) with the requested sample
   * rate and the rate the device resolved to, so the UI can show a DSA
   * coerced-fs note (request 8000 → device 8533.33 Hz).
   */
  onConfigured(cb: (info: ConfiguredInfo) => void): void {
    this.configuredCb = cb;
  }

  /**
   * Surface a `configured` status to {@link configuredCb} with the requested
   * fs paired against the device-resolved `fs` (and channel count).  Ignores
   * a reply that carries no usable `fs` so a soundcard/mock echo without one
   * never emits a spurious note.
   */
  private emitConfigured(requestedFs: number, status: Record<string, unknown>): void {
    const configuredFs = Number(status.fs);
    if (!Number.isFinite(configuredFs) || configuredFs <= 0) return;
    this.configuredCb?.({
      requestedFs,
      configuredFs,
      channels: Number(status.channels) || 0,
      deviceNote: typeof status.deviceNote === 'string' ? status.deviceNote : undefined,
    });
  }

  /** Provenance metadata from the most recent logged capture, or `null`. */
  lastMeta(): BridgeRecordingMeta | null {
    return this.lastRecordingMeta;
  }

  // -- connection --

  private connect(): Promise<void> {
    if (this.dead) return Promise.reject(new Error('bridge connection is closed'));
    if (this.connectPromise) return this.connectPromise;
    this.connectPromise = new Promise<void>((resolve, reject) => {
      let ws: WsLike;
      try {
        ws = this.wsFactory(this.url);
      } catch (e) {
        this.dead = true;
        reject(new Error(`bridge connect failed: ${msgOf(e)}`));
        return;
      }
      this.ws = ws;
      try { ws.binaryType = 'arraybuffer'; } catch { /* fake transports may lack it */ }
      let settled = false;
      ws.onopen = () => { settled = true; resolve(); };
      ws.onmessage = (ev: { data: unknown }) => this.handleMessage(ev.data);
      const down = (why: string) => {
        if (!settled) { settled = true; reject(new Error(why)); }
        this.fail(why);
      };
      ws.onerror = () => down('bridge socket error');
      ws.onclose = () => down('bridge socket closed');
    });
    return this.connectPromise;
  }

  /** Mark dead and reject every pending op with `msg`. */
  private fail(msg: string): void {
    if (this.dead) return;
    this.dead = true;
    const err = new Error(msg);
    for (const p of this.pending) p.reject(err);
    this.pending = [];
    if (this.pendingContainer) { this.pendingContainer.reject(err); this.pendingContainer = null; }
    this.onChunk = null;
  }

  private sendJson(obj: Record<string, unknown>): void {
    if (!this.ws || this.dead) throw new Error('bridge is not connected');
    this.ws.send(JSON.stringify(obj));
  }

  /** Park a JSON-reply waiter that settles when `match` first succeeds. */
  private waitFor(match: (m: Record<string, unknown>) => boolean): Promise<Record<string, unknown>> {
    return new Promise((resolve, reject) => this.pending.push({ match, resolve, reject }));
  }

  // -- inbound frames --

  private handleMessage(data: unknown): void {
    if (typeof data === 'string') { this.handleJson(data); return; }
    let bytes: Uint8Array | null = null;
    if (data instanceof ArrayBuffer) bytes = new Uint8Array(data);
    else if (data instanceof Uint8Array) bytes = data;
    else if (ArrayBuffer.isView(data)) {
      const v = data as ArrayBufferView;
      bytes = new Uint8Array(v.buffer, v.byteOffset, v.byteLength);
    }
    if (bytes) this.handleBinary(bytes);
  }

  private handleBinary(bytes: Uint8Array): void {
    let header: FrameHeader;
    try {
      header = decodeHeader(bytes);
    } catch {
      return; // corrupt / non-pydvma frame — ignore on the wire
    }
    if (header.msgType === MSG_CHUNK) {
      if (!this.onChunk) return;
      const count = header.nSamples * header.nChannels;
      const payload = bytes.slice(HEADER_SIZE); // fresh 0-offset buffer (4-byte aligned)
      const usable = Math.min(count, Math.floor(payload.byteLength / 4));
      const chunk = new Float32Array(payload.buffer, payload.byteOffset, usable);
      this.onChunk({
        data: chunk,
        nSamples: header.nSamples,
        nChannels: header.nChannels,
        fs: header.fs,
      });
    } else if (header.msgType === MSG_CONTAINER) {
      const body = bytes.slice(HEADER_SIZE);
      if (this.pendingContainer) {
        const pc = this.pendingContainer;
        this.pendingContainer = null;
        pc.resolve(body);
      } else {
        this.bufferedContainer = body;
      }
    }
  }

  private handleJson(text: string): void {
    let msg: Record<string, unknown>;
    try {
      const parsed = JSON.parse(text);
      if (parsed == null || typeof parsed !== 'object') return;
      msg = parsed as Record<string, unknown>;
    } catch {
      return;
    }
    if (msg.type === 'error') {
      const err = new Error(String(msg.message ?? 'bridge error'));
      const head = this.pending.shift();
      if (head) head.reject(err);
      if (this.pendingContainer) { this.pendingContainer.reject(err); this.pendingContainer = null; }
      return;
    }
    // Log-scoped pretrigger lifecycle: `armed` / `triggered` / `timeout`
    // arrive while a `log` is awaiting `log_result` and are not awaited by
    // any waiter — surface them to the status sink (a `timeout` is NOT an
    // error: the capture still resolves with the buffered set).
    if (msg.type === 'status' && typeof msg.event === 'string' && LOG_STATUS_EVENTS.has(msg.event)) {
      // The capture clock follows the same events: hold at 0 while armed,
      // run from the crossing (or from the timeout, when the recorder gives
      // up waiting and captures anyway).
      if (this.logClock) {
        this.logClock.start = msg.event === 'armed' ? null : nowMs();
      }
      this.logStatusCb?.(msg.event as LogStatusEvent);
      return;
    }
    // Cancel-during-log: the server sends this INSTEAD of log_result + the
    // container, so the log's waiter has to be released here or it never
    // settles.  With no log in flight this is the ordinary monitor-stop
    // acknowledgement and there is nothing to do.
    if (msg.type === 'status' && msg.event === CANCELLED_EVENT) {
      this.cancelWaiter?.();
      return;
    }
    for (let i = 0; i < this.pending.length; i++) {
      if (this.pending[i].match(msg)) {
        const [p] = this.pending.splice(i, 1);
        p.resolve(msg);
        return;
      }
    }
    // Unmatched status (e.g. a monitor status echo) — nothing waiting, ignore.
  }

  // -- capabilities / enumeration --

  async capabilities(): Promise<BridgeCaps | null> {
    if (this.capsCache) return this.capsCache;
    if (this.dead) return null;
    try {
      await this.connect();
      this.sendJson({ type: 'hello' });
      const msg = await this.waitFor((m) => m.type === 'capabilities');
      this.capsCache = normalizeCaps(msg);
      return this.capsCache;
    } catch {
      return null;
    }
  }

  /**
   * Flatten the capability document into device dropdown entries: a
   * synthetic 'mock' entry when the mock backend is present, then every
   * soundcard name, then each NI device labelled `NI: <name> (<ai> ch)`.
   * The `deviceId` encodes `<driver>:<index>` so the recorder/monitor can
   * derive `device_driver` + `device_index` from the selection.
   */
  async enumerateInputDevices(): Promise<AudioInputDevice[]> {
    const caps = await this.capabilities();
    if (!caps) return [];
    const out: AudioInputDevice[] = [];
    if (caps.backends.includes('mock')) {
      out.push({ deviceId: 'mock:0', label: 'Mock signal generator', groupId: 'mock', hasLabel: true });
    }
    caps.devices.soundcard.forEach((name, i) => {
      // Carry the backend metadata through so the dropdown can collapse
      // one interface's several host-API entries into a single choice —
      // see AudioInputDevice. Older servers omit these keys entirely and
      // the UI falls back to the flat list.
      const dc: any = caps.device_caps?.[`soundcard:${i}`] ?? {};
      // Playback-only endpoints are not inputs. PortAudio enumerates
      // both directions in one list, so without this the INPUT dropdown
      // offers Speakers and Headphones — selectable, and guaranteed to
      // fail at capture. Skipped only when the server actually told us
      // the channel counts; an older bridge that sends no device_caps
      // keeps the flat list rather than losing entries.
      if (typeof dc.max_input_channels === 'number' && dc.max_input_channels < 1) {
        return;
      }
      out.push({
        deviceId: `soundcard:${i}`,
        label: name,
        groupId: 'soundcard',
        hasLabel: true,
        hostapi: dc.hostapi ?? undefined,
        deviceGroup: dc.device_group ?? undefined,
        recommended: dc.recommended ?? undefined,
        backendCount: dc.backend_count ?? undefined,
        hostapiNote: dc.hostapi_note ?? undefined,
        isAlias: dc.is_alias ?? undefined,
        calibration: dc.calibration_status ?? undefined,
        calibrationAdvice: dc.calibration_advice ?? undefined,
        fullScaleVolts: dc.full_scale_volts ?? undefined,
      });
    });
    caps.devices.nidaq.forEach((d, i) => {
      out.push({
        deviceId: `nidaq:${i}`,
        label: `NI: ${d.name} (${d.ai_channel_count} ch)`,
        groupId: 'nidaq',
        hasLabel: true,
      });
    });
    return out;
  }

  // -- configure kwargs --

  /**
   * The device NAME this client believes `cfg.deviceId`'s index refers to.
   *
   * Sent alongside the settings so the server can check the index has not
   * gone stale. Indices are positions in an enumeration, not identities:
   * this client enumerates once on connect, and PortAudio renumbers
   * whenever the device list changes, so an index captured at connect time
   * can silently point at a different device by the time anything records.
   * Undefined when the device is not in the caps we were given, in which
   * case the server has nothing to check against and proceeds on the index.
   */
  private expectedDeviceName(cfg: Omit<RecordConfig, 'durationS'>): string | undefined {
    const caps = this.capsCache;
    if (!caps || !cfg.deviceId) return undefined;
    const dev = parseDeviceId(cfg.deviceId);
    if (!dev || dev.driver === 'mock') return undefined;
    return caps.device_caps?.[cfg.deviceId]?.name ?? undefined;
  }

  /** Build the whitelisted MySettings kwargs for a configure message. */
  private buildSettings(
    cfg: Omit<RecordConfig, 'durationS'>,
    durationS?: number,
  ): Record<string, unknown> {
    const s: Record<string, unknown> = {
      fs: cfg.sampleRate,
      channels: cfg.channelCount,
    };
    const dev = parseDeviceId(cfg.deviceId);
    if (dev) {
      s.device_driver = dev.driver;
      if (dev.driver !== 'mock') s.device_index = dev.index;
    }
    if (durationS != null) s.stored_time = durationS;
    // Digital low-pass: the SERVER owns the whole chain (oversample,
    // anti-alias FIR, resample to fs) — one flag here.
    if (cfg.lpfOn) s.lpf_on = true;

    const ec = this.extraConfig;
    if (ec.deviceDriver && s.device_driver == null) s.device_driver = ec.deviceDriver;
    if (ec.deviceIndex != null && s.device_index == null) s.device_index = ec.deviceIndex;
    if (ec.inputChannelsSpec) s.input_channels_spec = ec.inputChannelsSpec;
    if (ec.iepeExcitCurrentA != null) s.iepe_excit_current_A = ec.iepeExcitCurrentA;
    if (ec.niMode) s.NI_mode = ec.niMode;
    // Voltage rails (already clamped to the device's ai_vmax/ao_vmax by the
    // store before they reach here) map onto MySettings' VmaxNI / output_VmaxNI.
    // Capture-rate control. `fs` stays the DELIVERED rate; these decide what
    // the converter actually runs at before pydvma decimates.
    if (ec.captureFs != null) s.capture_fs = ec.captureFs;
    if (ec.oversample && ec.oversample !== 'auto') s.oversample = ec.oversample;
    // Preamp gain provenance: the server derives VmaxSC from this, because
    // no audio API can read the gain off the interface. A FIXED-GAIN
    // interface (e.g. the ESI U24 XL) has no gain to state at all — full
    // scale is a hardware constant — so force `null` (not 0, which would
    // read as "stated") even if `ec.inputGainDb` still holds a stale
    // number left over from a previously selected variable-gain device
    // (e.g. the operator had a 2i2 selected, then switched to the U24 XL
    // without the now-hidden gain field ever clearing the store). The
    // server auto-derives VmaxSC for a fixed-gain device when
    // `input_gain_db` is `None`; a stale out-of-range gain would instead
    // raise on the fixed-gain profile, whose gain range is exactly 0 dB.
    const selDc = cfg.deviceId ? this.capsCache?.device_caps?.[cfg.deviceId] : undefined;
    if (selDc?.fixed_gain) {
      s.input_gain_db = null;
    } else if (ec.inputGainDb != null) {
      s.input_gain_db = ec.inputGainDb;
      if (ec.inputMode) s.input_mode = ec.inputMode;
    }
    if (ec.vmaxNI != null) s.VmaxNI = ec.vmaxNI;
    if (ec.outputVmaxNI != null) s.output_VmaxNI = ec.outputVmaxNI;
    if (ec.pretrigSamples !== undefined) s.pretrig_samples = ec.pretrigSamples;
    if (ec.pretrigThreshold != null) s.pretrig_threshold = ec.pretrigThreshold;
    if (ec.pretrigChannel != null) s.pretrig_channel = ec.pretrigChannel;

    // Output (AO) device + channel selection (Acquire output group), sent as
    // whitelisted MySettings kwargs only when the stimulus is enabled. The
    // driver/index are derived from the selected output deviceId exactly like
    // the input device; output_channels sizes the generated waveform.  A
    // per-capture `outputOverride` (BLA) counts as "enabled" here too — it
    // wins over the card's enabled-ness, so the AO device selection must ride
    // along even when the card's stimulus group is switched off.
    const override = cfg.outputOverride;
    if (ec.outputEnabled || override) {
      const od = parseDeviceId(ec.outputDeviceId);
      if (od) {
        s.output_device_driver = od.driver;
        if (od.driver !== 'mock') s.output_device_index = od.index;
      }
      if (ec.outputChannels != null) s.output_channels = ec.outputChannels;
      // A multisine drives one channel PER EXCITATION and its buffer has
      // EXACTLY `n_exc` columns — unlike `signal_generator`, which fills
      // `output_channels` columns with copies of one waveform. So this
      // OVERRIDES the card's value in both directions rather than widening it:
      // a staled-wider `outputChannels` (an Acquire-card edit, or a
      // `--settings` prefill) would make the write fail on the (n_samples,
      // n_exc) buffer — sounddevice rejects the column mismatch, DAQmx errors
      // on a channel string wider than the data. The server's own generator
      // also rejects `n_exc > settings.output_channels`, so too-narrow fails
      // too; exactness is the only value that always works.
      if (override?.type === 'multisine') {
        s.output_channels = override.nExc;
      }
      // Store-derived AO rate clamp (the effective output device's
      // ao_max_rate sits below the input fs, e.g. USB-6003 AO at 5 kS/s):
      // without it the server defaults output_fs = fs and rejects the log
      // with "output_fs exceeds the maximum AO sample rate".
      if (ec.outputFs != null) s.output_fs = ec.outputFs;
    }

    // A pretrigger's context buffer (`chunk_size`, pydvma default 100) must
    // be at least as large as `pretrig_samples`, else MySettings REJECTS the
    // whole configure (options.py: "pretrig_samples must not exceed
    // chunk_size").  Keyed on the sample count being PRESENT, not on the arm
    // switch: `pretrig_samples` above rides every configure — monitor as well
    // as log — the moment Setup holds a value, so gating the raise on `armed`
    // (or on this being a log) let a merely STAGED 500 break configure with
    // nothing armed and no capture in sight.  The bare-arm default equals the
    // default chunk_size (100), so arming alone still needs no bigger buffer.
    const effSamples = ec.pretrigSamples ?? (ec.pretrigArmed ? BARE_ARM_PRETRIG_SAMPLES : null);
    if (effSamples != null && effSamples > PYDVMA_DEFAULT_CHUNK_SIZE) {
      s.chunk_size = effSamples;
    }
    return s;
  }

  /**
   * Build the `log` message's `pretrigger` field from the Acquire arm
   * switch + Setup's pretrigger params.  `null` (free-run capture) unless
   * `pretrigArmed` is set; when armed, an object the server maps onto
   * `MySettings.pretrig_*` (samples/threshold/channel/timeout).
   *
   * UNITS: the threshold is compared against VmaxSC-scaled data server-side,
   * i.e. VOLTS on a characterised interface.  The server's own default
   * (`0.05`) predates that scaling and means 0.05 V — 0.36 % of full scale on
   * a 2i2, which triggers on the noise floor.  So when the operator has
   * stated no threshold, the client sends `5 % of full scale` EXPLICITLY
   * rather than letting the stale default stand; the same number Setup shows
   * as the field's placeholder ({@link defaultPretrigThreshold}).
   */
  private buildPretrigger(cfg: Omit<RecordConfig, 'durationS'>): Record<string, unknown> | null {
    const ec = this.extraConfig;
    if (!ec.pretrigArmed) return null;
    // The server arms only when `samples` is non-null; a bare arm (no
    // Setup / arm-control pretrig-samples) defaults to BARE_ARM_PRETRIG_SAMPLES
    // (100 — matches the default chunk_size) so arming actually arms rather
    // than silently free-running.
    const p: Record<string, unknown> = {
      samples: ec.pretrigSamples ?? BARE_ARM_PRETRIG_SAMPLES,
    };
    p.threshold = ec.pretrigThreshold
      ?? defaultPretrigThreshold(
        effectiveFullScaleVolts(this.capsCache, cfg.deviceId, ec),
      );
    if (ec.pretrigChannel != null) p.channel = ec.pretrigChannel;
    if (ec.pretrigTimeout != null) p.timeout = ec.pretrigTimeout;
    return p;
  }

  /**
   * Build the `log` message's `output` (stimulus) field from the Acquire
   * output group, or from a per-capture `override` when one is given.  `null`
   * with no override unless `outputEnabled`; when on, `{type, amp, f1, f2}`
   * (plus an optional `duration`) mapping to pydvma's `signal_generator` /
   * `Output_Signal_Settings`.  The output device + channel selection travels
   * separately, as MySettings kwargs in the configure message (see
   * {@link buildSettings}).
   *
   * An `override` REPLACES the card's stimulus for this capture (both
   * enabled-ness and content): a classic spec emits the same four keys from
   * the override's own fields, a `'multisine'` one emits the separate
   * snake_case multisine keyset (see {@link multisineOutputWire}).
   */
  private buildOutput(override?: OutputSpec): Record<string, unknown> | null {
    if (override) {
      if (override.type === 'multisine') return multisineOutputWire(override);
      const o: Record<string, unknown> = {
        type: override.type, amp: override.amp, f1: override.f1, f2: override.f2,
      };
      if (override.durationS != null && override.durationS > 0) o.duration = override.durationS;
      return o;
    }
    const ec = this.extraConfig;
    if (!ec.outputEnabled) return null;
    // Unset fields fall back to the SAME defaults AcquireCard displays
    // (and provider.ts's Web Audio path uses). The store only holds a
    // value once the user edits the field, so `?? 0` here made a fresh
    // session's untouched output group send a 0 Hz "sweep" at 0 V —
    // i.e. silence, or (with amp set) a windowed DC pulse — while the
    // settings chip claimed "sweep 0.3V 10-500Hz" (reproduced on real
    // NI hardware, 2026-07-10).
    const out: Record<string, unknown> = {
      type: ec.outputType ?? 'sweep',
      amp: ec.outputAmp ?? 0.3,
      f1: ec.outputF1 ?? 10,
      f2: ec.outputF2 ?? 500,
    };
    // Optional stimulus duration (server default = the capture duration).
    if (ec.outputDuration != null && ec.outputDuration > 0) out.duration = ec.outputDuration;
    return out;
  }

  // -- monitor --

  async startMonitor(
    cfg: Omit<RecordConfig, 'durationS'>,
    ondata: MonitorCallback,
  ): Promise<MonitorHandle> {
    try {
      await this.connect();
      this.onChunk = ondata;
      this.sendJson({ type: 'configure', settings: this.buildSettings(cfg),
        device_name: this.expectedDeviceName(cfg) });
      const status = await this.waitFor((m) => m.type === 'status' && m.event === 'configured');
      this.emitConfigured(cfg.sampleRate, status);
      this.sendJson({ type: 'start_monitor' });
      await this.waitFor((m) => m.type === 'status' && m.event === 'monitoring');

      const fs = Number(status.fs) || cfg.sampleRate;
      const nChannels = Number(status.channels) || cfg.channelCount;
      let stopped = false;
      const stop = () => {
        if (stopped) return;
        stopped = true;
        this.onChunk = null;
        if (!this.dead && this.ws) {
          try { this.sendJson({ type: 'stop_monitor' }); } catch { /* socket gone */ }
        }
      };
      return { stop, fs, nChannels };
    } catch (e) {
      this.onChunk = null;
      throw e instanceof Error ? e : new Error(msgOf(e));
    }
  }

  // -- record (log) --

  startRecording(cfg: RecordConfig): RecordingHandle {
    let cancelled = false;
    // Capture-relative clock. It deliberately does NOT start at
    // startRecording(): everything before the `log` frame — connect,
    // configure, the device opening its stream — is setup, and counting it
    // against the capture duration made the progress bar arrive already part
    // spent (and saturated before a single sample on a slow open).
    const clock: { start: number | null } = { start: null };
    this.logClock = clock;

    const promise = (async (): Promise<Recording> => {
      await this.connect();
      this.sendJson({ type: 'configure', settings: this.buildSettings(cfg, cfg.durationS),
        device_name: this.expectedDeviceName(cfg) });
      const configured = await this.waitFor((m) => m.type === 'status' && m.event === 'configured');
      this.emitConfigured(cfg.sampleRate, configured);
      if (cancelled) {
        try { this.sendJson({ type: 'cancel' }); } catch { /* */ }
        throw new CancelledError();
      }
      const pretrigger = this.buildPretrigger(cfg);
      this.sendJson({
        type: 'log',
        duration: cfg.durationS,
        pretrigger,
        output: this.buildOutput(cfg.outputOverride),
      });
      // An armed capture starts counting at the crossing (handleJson moves
      // the clock on `triggered`/`timeout`); a free-run one starts now.
      clock.start = pretrigger ? null : nowMs();
      await this.awaitLogOutcome();
      const bytes = await new Promise<Uint8Array>((resolve, reject) => {
        // The container frame follows log_result; it may (rarely) have
        // arrived first and been buffered.
        if (this.bufferedContainer) {
          const b = this.bufferedContainer;
          this.bufferedContainer = null;
          resolve(b);
          return;
        }
        this.pendingContainer = { resolve, reject };
      });
      this.lastRecordingMeta = recordingMetaFromDvma(bytes);
      return recordingFromDvma(bytes);
    })();
    // Whatever the outcome, the clock belongs to no capture afterwards.
    void promise.catch(() => {}).then(() => {
      if (this.logClock === clock) this.logClock = null;
    });

    return {
      promise,
      cancel: () => {
        cancelled = true;
        if (!this.dead && this.ws) {
          try { this.sendJson({ type: 'cancel' }); } catch { /* */ }
        }
      },
      elapsed: () => (
        clock.start == null ? 0 : Math.min(cfg.durationS, (nowMs() - clock.start) / 1000)
      ),
    };
  }

  /**
   * Wait for the log to end, either way: `log_result` (a container follows)
   * or `status/cancelled` (nothing follows — the server dropped the capture
   * because the user cancelled), which rejects with {@link CancelledError}.
   *
   * Racing matters structurally, not just for tidiness: the `log_result`
   * waiter lives in a FIFO matched by TYPE, so a waiter left parked after a
   * cancel would swallow the NEXT capture's result and hang that one instead.
   * Whichever branch settles removes the other.
   */
  private awaitLogOutcome(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const entry: Pending = {
        match: (m) => m.type === 'log_result',
        resolve: () => { this.cancelWaiter = null; resolve(); },
        reject: (e) => { this.cancelWaiter = null; reject(e); },
      };
      this.pending.push(entry);
      this.cancelWaiter = () => {
        const i = this.pending.indexOf(entry);
        if (i >= 0) this.pending.splice(i, 1);
        this.cancelWaiter = null;
        reject(new CancelledError());
      };
    });
  }

  // -- teardown --

  dispose(): void {
    if (this.dead) { try { this.ws?.close(); } catch { /* */ } return; }
    this.dead = true;
    const err = new Error('bridge disposed');
    for (const p of this.pending) p.reject(err);
    this.pending = [];
    if (this.pendingContainer) { this.pendingContainer.reject(err); this.pendingContainer = null; }
    this.onChunk = null;
    try { this.ws?.close(); } catch { /* */ }
  }
}

// ---- module helpers ----

/**
 * Map a camelCase {@link MultisineStimulusConfig} onto the EXACT snake_case
 * keyset `pydvma serve` whitelists for a multisine `log.output`
 * (`_OUTPUT_SPEC_KEYS_MULTISINE` in `serve.py`): `type`, `amp` (the wire name
 * for `amp_rms`), `n_samples`, `k1`, `k2`, `p_periods`, `t_periods`, `seed`,
 * `m`, `e`, `n_exc`.
 *
 * The server rejects the whole log on ANY unknown key, so this builds the
 * object field-by-field rather than spreading the spec — `limit` and
 * `deviceId` (browser-only) must not leak, and neither may `duration`, which
 * multisine explicitly refuses: its length is derived from `n_samples`,
 * `t_periods`, `p_periods` and `fs`.
 */
function multisineOutputWire(spec: MultisineStimulusConfig): Record<string, unknown> {
  return {
    type: 'multisine',
    amp: spec.ampRms,
    n_samples: spec.nSamples,
    k1: spec.k1,
    k2: spec.k2,
    p_periods: spec.pPeriods,
    t_periods: spec.tPeriods,
    seed: spec.seed,
    m: spec.m,
    e: spec.e,
    n_exc: spec.nExc,
  };
}

function msgOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function nowMs(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

/** Coerce a capabilities JSON message into a well-typed BridgeCaps. */
function normalizeCaps(m: Record<string, unknown>): BridgeCaps {
  const devices = (m.devices ?? {}) as { soundcard?: unknown; nidaq?: unknown };
  const caps: BridgeCaps = {
    v: Number(m.v) || PROTOCOL_VERSION,
    backends: Array.isArray(m.backends) ? (m.backends as string[]) : [],
    devices: {
      soundcard: Array.isArray(devices.soundcard) ? (devices.soundcard as string[]) : [],
      nidaq: Array.isArray(devices.nidaq) ? (devices.nidaq as NiDeviceEntry[]) : [],
    },
    fs_ladders: (m.fs_ladders ?? {}) as Record<string, number[]>,
    max_channels: normalizeMaxChannels(m.max_channels),
    pretrigger: Boolean(m.pretrigger),
    ao: Boolean(m.ao),
  };
  // Per-device caps (Wave C) — additive; only attach a well-formed object.
  if (m.device_caps && typeof m.device_caps === 'object' && !Array.isArray(m.device_caps)) {
    caps.device_caps = m.device_caps as Record<string, DeviceCapsEntry>;
  }
  // Which device "Default" actually resolves to (round-11) — additive, and
  // `null` is a real answer (no device), so only a well-formed object counts.
  const di = normalizeDefaultDevice(m.default_input);
  if (di !== undefined) caps.default_input = di;
  const dout = normalizeDefaultDevice(m.default_output);
  if (dout !== undefined) caps.default_output = dout;
  return caps;
}

/**
 * Coerce a `default_input` / `default_output` capability field into a
 * {@link BridgeDefaultDevice}.  Returns `null` for an explicit server `null`
 * (the driver has no default device) and `undefined` when the field is absent
 * or malformed — an older bridge, whose UI simply keeps saying "Default".
 */
function normalizeDefaultDevice(v: unknown): BridgeDefaultDevice | null | undefined {
  if (v === null) return null;
  if (!v || typeof v !== 'object' || Array.isArray(v)) return undefined;
  const o = v as Record<string, unknown>;
  const name = typeof o.name === 'string' ? o.name : '';
  const driver = typeof o.driver === 'string' ? o.driver : '';
  if (!name || !driver) return undefined;
  const index = Number(o.index);
  return {
    driver,
    index: Number.isFinite(index) ? index : 0,
    name,
    hostapi: typeof o.hostapi === 'string' && o.hostapi ? o.hostapi : undefined,
  };
}

/**
 * Pass `max_channels` through: a Wave-C per-device `{input, output}` map
 * (keyed by deviceId), a legacy scalar, or `null`.  Anything else → `null`.
 * Consumers read per-device counts via {@link deviceCapsFor}, never this
 * raw value.
 */
function normalizeMaxChannels(v: unknown): BridgeCaps['max_channels'] {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    return v as Record<string, DeviceChannelCounts>;
  }
  return typeof v === 'number' ? v : null;
}
