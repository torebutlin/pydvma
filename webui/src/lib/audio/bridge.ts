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
import type {
  AudioInputDevice,
  BridgeCaps,
  BridgeConfig,
  MonitorCallback,
  MonitorHandle,
  NiDeviceEntry,
  RecordConfig,
  Recording,
  RecordingHandle,
  SourceProvider,
} from './provider';

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

  constructor(url: string, wsFactory: (url: string) => WsLike = defaultWsFactory) {
    this.url = url;
    this.wsFactory = wsFactory;
  }

  /** Stash NI/driver kwargs merged into the next configure message. */
  setConfig(cfg: BridgeConfig): void {
    this.extraConfig = { ...this.extraConfig, ...cfg };
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
      out.push({ deviceId: `soundcard:${i}`, label: name, groupId: 'soundcard', hasLabel: true });
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

    const ec = this.extraConfig;
    if (ec.deviceDriver && s.device_driver == null) s.device_driver = ec.deviceDriver;
    if (ec.deviceIndex != null && s.device_index == null) s.device_index = ec.deviceIndex;
    if (ec.inputChannelsSpec) s.input_channels_spec = ec.inputChannelsSpec;
    if (ec.iepeExcitCurrentA != null) s.iepe_excit_current_A = ec.iepeExcitCurrentA;
    if (ec.niMode) s.NI_mode = ec.niMode;
    if (ec.pretrigSamples !== undefined) s.pretrig_samples = ec.pretrigSamples;
    if (ec.pretrigThreshold != null) s.pretrig_threshold = ec.pretrigThreshold;
    if (ec.pretrigChannel != null) s.pretrig_channel = ec.pretrigChannel;
    return s;
  }

  // -- monitor --

  async startMonitor(
    cfg: Omit<RecordConfig, 'durationS'>,
    ondata: MonitorCallback,
  ): Promise<MonitorHandle> {
    try {
      await this.connect();
      this.onChunk = ondata;
      this.sendJson({ type: 'configure', settings: this.buildSettings(cfg) });
      const status = await this.waitFor((m) => m.type === 'status' && m.event === 'configured');
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
    const startT = nowMs();

    const promise = (async (): Promise<Recording> => {
      await this.connect();
      this.sendJson({ type: 'configure', settings: this.buildSettings(cfg, cfg.durationS) });
      await this.waitFor((m) => m.type === 'status' && m.event === 'configured');
      if (cancelled) {
        try { this.sendJson({ type: 'cancel' }); } catch { /* */ }
        throw new Error('cancelled');
      }
      this.sendJson({ type: 'log', duration: cfg.durationS, pretrigger: null });
      await this.waitFor((m) => m.type === 'log_result');
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
      return recordingFromDvma(bytes);
    })();

    return {
      promise,
      cancel: () => {
        cancelled = true;
        if (!this.dead && this.ws) {
          try { this.sendJson({ type: 'cancel' }); } catch { /* */ }
        }
      },
      elapsed: () => Math.min(cfg.durationS, (nowMs() - startT) / 1000),
    };
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

function msgOf(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function nowMs(): number {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

/** Coerce a capabilities JSON message into a well-typed BridgeCaps. */
function normalizeCaps(m: Record<string, unknown>): BridgeCaps {
  const devices = (m.devices ?? {}) as { soundcard?: unknown; nidaq?: unknown };
  return {
    v: Number(m.v) || PROTOCOL_VERSION,
    backends: Array.isArray(m.backends) ? (m.backends as string[]) : [],
    devices: {
      soundcard: Array.isArray(devices.soundcard) ? (devices.soundcard as string[]) : [],
      nidaq: Array.isArray(devices.nidaq) ? (devices.nidaq as NiDeviceEntry[]) : [],
    },
    fs_ladders: (m.fs_ladders ?? {}) as Record<string, number[]>,
    max_channels: m.max_channels == null ? null : Number(m.max_channels),
    pretrigger: Boolean(m.pretrigger),
    ao: Boolean(m.ao),
  };
}
