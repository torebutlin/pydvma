/**
 * BridgeProvider unit tests — driven against a FAKE WebSocket transport
 * (constructor-injectable, mirroring worker/client.ts's WorkerLike pattern).
 * No real socket, no `pydvma serve`.  Covers the binary header decode
 * (incl. bad-magic rejection), a monitor chunk reaching ondata, stop
 * sending stop_monitor, a logged capture resolving into a Recording from
 * real .dvma bytes (built here with writeDvma), error propagation, and the
 * capabilities-null fail-soft fallback.
 */
import { expect, test } from 'vitest';
import {
  BridgeProvider,
  decodeHeader,
  recordingFromDvma,
  recordingMetaFromDvma,
  MAGIC,
  HEADER_SIZE,
  MSG_CHUNK,
  MSG_CONTAINER,
  type WsLike,
} from '../../src/lib/audio/bridge';
import {
  deviceCapsFor,
  outputCapable,
  outputDevices,
  clampVoltage,
  PYDVMA_DEFAULT_VMAX,
  BARE_ARM_PRETRIG_SAMPLES,
  type BridgeCaps,
  type ConfiguredInfo,
  type LogStatusEvent,
} from '../../src/lib/audio/provider';
import type { MonitorChunk } from '../../src/lib/audio/source';
import type { DvmaDataset } from '../../src/lib/model/dataset';
import { recordingToDataset } from '../../src/lib/stores/acquire';
import { writeDvma } from '../../src/lib/codec/dvma';

// ---- fake ws transport ----

/**
 * A fake WsLike that records everything sent and lets the test emit
 * open/message/error/close events on demand.
 */
function makeFakeWs() {
  const sent: Array<string | Uint8Array> = [];
  const ws: WsLike = {
    readyState: 0,
    binaryType: '',
    send(data) {
      if (typeof data === 'string') sent.push(data);
      else if (data instanceof Uint8Array) sent.push(data);
      else if (data instanceof ArrayBuffer) sent.push(new Uint8Array(data));
      else sent.push(new Uint8Array((data as ArrayBufferView).buffer));
    },
    close() { this.readyState = 3; },
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
  };
  return {
    ws,
    sent,
    /** Parsed JSON control frames the provider has sent. */
    sentJson: () => sent.filter((s): s is string => typeof s === 'string').map((s) => JSON.parse(s)),
    open: () => { ws.readyState = 1; ws.onopen?.(); },
    emitJson: (obj: unknown) => ws.onmessage?.({ data: JSON.stringify(obj) }),
    /** Deliver a binary frame as an ArrayBuffer (matches binaryType='arraybuffer'). */
    emitBinary: (bytes: Uint8Array) => ws.onmessage?.({ data: bytes.slice().buffer }),
    error: () => ws.onerror?.(),
    close: () => ws.onclose?.(),
  };
}

/** Flush pending microtasks (lets the provider's async awaits advance). */
const tick = () => new Promise<void>((r) => setTimeout(r, 0));

// ---- frame builders (mirror pydvma/serve.py `encode_*`) ----

function buildFrame(
  msgType: number, dtype: number, streamId: number, nChannels: number,
  seq: number, nSamples: number, fs: number, payload: Uint8Array,
): Uint8Array {
  const buf = new Uint8Array(HEADER_SIZE + payload.byteLength);
  const dv = new DataView(buf.buffer);
  dv.setUint8(0, MAGIC);
  dv.setUint8(1, 1);
  dv.setUint8(2, msgType);
  dv.setUint8(3, dtype);
  dv.setUint16(4, streamId, true);
  dv.setUint16(6, nChannels, true);
  dv.setUint32(8, seq, true);
  dv.setUint32(12, nSamples, true);
  dv.setFloat32(16, fs, true);
  buf.set(payload, HEADER_SIZE);
  return buf;
}

function chunkFrame(interleaved: Float32Array, nChannels: number, fs: number, seq = 0): Uint8Array {
  const payload = new Uint8Array(interleaved.buffer.slice(0));
  return buildFrame(MSG_CHUNK, 0, 1, nChannels, seq, interleaved.length / nChannels, fs, payload);
}

function containerFrame(dvma: Uint8Array, nChannels: number, nSamples: number, fs: number): Uint8Array {
  return buildFrame(MSG_CONTAINER, 255, 1, nChannels, 1, nSamples, fs, dvma);
}

// ---- header decode ----

test('decodeHeader parses fields and rejects bad magic / short frames', () => {
  const f = buildFrame(MSG_CHUNK, 0, 7, 2, 42, 4, 48000, new Uint8Array(0));
  const h = decodeHeader(f);
  expect(h.magic).toBe(MAGIC);
  expect(h.msgType).toBe(MSG_CHUNK);
  expect(h.streamId).toBe(7);
  expect(h.nChannels).toBe(2);
  expect(h.seq).toBe(42);
  expect(h.nSamples).toBe(4);
  expect(h.fs).toBeCloseTo(48000);

  const bad = f.slice();
  bad[0] = 0x00;
  expect(() => decodeHeader(bad)).toThrow(/magic/);
  expect(() => decodeHeader(new Uint8Array(5))).toThrow(/shorter/);
});

// ---- capabilities + enumeration ----

const CAPS = {
  type: 'capabilities',
  v: 1,
  backends: ['mock', 'soundcard', 'nidaq'],
  devices: {
    soundcard: ['Built-in Mic'],
    nidaq: [{
      name: 'cDAQ1Mod1', product_type: 'NI 9234', is_chassis: false,
      ai_channel_count: 4, ao_channel_count: 0,
      module_names: [], module_ai_counts: {}, module_ao_counts: {},
    }],
  },
  fs_ladders: {}, max_channels: null, pretrigger: true, ao: true,
};

test('capabilities resolves the hello reply and enumerateInputDevices flattens backends', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);

  const capsP = bp.capabilities();
  fake.open();
  await tick();
  // hello was sent on connect.
  expect(fake.sentJson().some((m) => m.type === 'hello')).toBe(true);
  fake.emitJson(CAPS);
  const caps = await capsP;
  expect(caps).not.toBeNull();
  expect(caps!.backends).toContain('nidaq');

  const devs = await bp.enumerateInputDevices();
  // mock synthetic + soundcard + nidaq entries, in that order.
  expect(devs.map((d) => d.deviceId)).toEqual(['mock:0', 'soundcard:0', 'nidaq:0']);
  expect(devs[2].label).toBe('NI: cDAQ1Mod1 (4 ch)');
});

test('capabilities() returns null when the socket errors before open (fail-soft)', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const capsP = bp.capabilities();
  fake.error();          // onerror before open → connect rejects
  fake.close();
  expect(await capsP).toBeNull();
});

test('capabilities() returns null when the ws factory throws', async () => {
  const bp = new BridgeProvider('ws://x/ws', () => { throw new Error('no websocket'); });
  expect(await bp.capabilities()).toBeNull();
});

// ---- monitor ----

async function startMonitor(fake: ReturnType<typeof makeFakeWs>, bp: BridgeProvider, chunks: MonitorChunk[]) {
  const monP = bp.startMonitor({ sampleRate: 44100, channelCount: 2 }, (c) => chunks.push(c));
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', fs: 44100, channels: 2 });
  await tick();
  fake.emitJson({ type: 'status', event: 'monitoring' });
  return monP;
}

test('a monitor chunk frame reaches ondata as a MonitorChunk; stop sends stop_monitor', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const chunks: MonitorChunk[] = [];
  const handle = await startMonitor(fake, bp, chunks);

  expect(handle.fs).toBe(44100);
  expect(handle.nChannels).toBe(2);
  expect(fake.sentJson().map((m) => m.type)).toEqual(['configure', 'start_monitor']);

  // Interleaved 2-channel, 3-sample chunk.
  const interleaved = new Float32Array([1, 10, 2, 20, 3, 30]);
  fake.emitBinary(chunkFrame(interleaved, 2, 44100, 5));
  expect(chunks).toHaveLength(1);
  expect(chunks[0].nChannels).toBe(2);
  expect(chunks[0].nSamples).toBe(3);
  expect(chunks[0].fs).toBeCloseTo(44100);
  expect(Array.from(chunks[0].data)).toEqual([1, 10, 2, 20, 3, 30]);

  handle.stop();
  expect(fake.sentJson().some((m) => m.type === 'stop_monitor')).toBe(true);

  // After stop, further chunks are dropped (onChunk cleared).
  fake.emitBinary(chunkFrame(interleaved, 2, 44100, 6));
  expect(chunks).toHaveLength(1);
});

test('a configure error rejects the monitor start (error propagation)', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const monP = bp.startMonitor({ sampleRate: 44100, channelCount: 2 }, () => {});
  fake.open();
  await tick();
  fake.emitJson({ type: 'error', message: "device_driver='nidaq' needs the [ni] extra" });
  await expect(monP).rejects.toThrow(/\[ni\] extra/);
});

test('a socket close rejects the in-flight monitor start', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const monP = bp.startMonitor({ sampleRate: 44100, channelCount: 2 }, () => {});
  fake.open();
  await tick();
  fake.close();          // onclose after open → fail() rejects pending
  await expect(monP).rejects.toThrow(/closed/);
});

// ---- log → Recording ----

test('log resolves a Recording parsed from the .dvma container frame', async () => {
  // Build a real .dvma with writeDvma from a tiny 2-channel recording.
  const nSamples = 4, nChannels = 2, fs = 8000;
  const timeAxis = Float64Array.from({ length: nSamples }, (_, i) => i / fs);
  const data = Float64Array.from({ length: nSamples * nChannels }, (_, i) => i + 0.5);
  const dvma = writeDvma(recordingToDataset({ data, timeAxis, fs, nChannels, nSamples }, 'bridged'));

  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const rh = bp.startRecording({ sampleRate: fs, channelCount: nChannels, durationS: 0.5 });
  fake.open();
  await tick();
  // configure → configured
  expect(fake.sentJson()[0]).toMatchObject({ type: 'configure' });
  fake.emitJson({ type: 'status', event: 'configured', fs, channels: nChannels });
  await tick();
  // log sent, carrying duration + null pretrigger
  const logMsg = fake.sentJson().find((m) => m.type === 'log');
  expect(logMsg).toMatchObject({ type: 'log', duration: 0.5, pretrigger: null });
  fake.emitJson({ type: 'log_result', nChannels, nSamples, fs, byteLength: dvma.length });
  await tick();
  fake.emitBinary(containerFrame(dvma, nChannels, nSamples, fs));

  const rec = await rh.promise;
  expect(rec.nChannels).toBe(nChannels);
  expect(rec.nSamples).toBe(nSamples);
  expect(rec.fs).toBe(fs);
  expect(Array.from(rec.data)).toEqual(Array.from(data));
  expect(Array.from(rec.timeAxis)).toEqual(Array.from(timeAxis));
});

test('recordingFromDvma round-trips a writeDvma container directly', () => {
  const nSamples = 3, nChannels = 1, fs = 1000;
  const timeAxis = Float64Array.from({ length: nSamples }, (_, i) => i / fs);
  const data = Float64Array.from([0.1, 0.2, 0.3]);
  const dvma = writeDvma(recordingToDataset({ data, timeAxis, fs, nChannels, nSamples }));
  const rec = recordingFromDvma(dvma);
  expect(rec.nChannels).toBe(1);
  expect(rec.nSamples).toBe(3);
  expect(Array.from(rec.data)).toEqual([0.1, 0.2, 0.3]);
});

test('a log error rejects the recording promise', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const rh = bp.startRecording({ sampleRate: 8000, channelCount: 2, durationS: 0.5 });
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', fs: 8000, channels: 2 });
  await tick();
  fake.emitJson({ type: 'error', message: 'capture failed: trigger timeout' });
  await expect(rh.promise).rejects.toThrow(/trigger timeout/);
});

// ---- NI config plumbing ----

test('setConfig NI kwargs flow into the configure message', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({ iepeExcitCurrentA: 0.002, niMode: 'DAQmx_Val_Diff', pretrigSamples: 128, pretrigThreshold: 0.1 });

  const rh = bp.startRecording({ deviceId: 'nidaq:0', sampleRate: 51200, channelCount: 4, durationS: 1 });
  fake.open();
  await tick();
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  expect(cfg!.settings).toMatchObject({
    device_driver: 'nidaq',
    device_index: 0,
    fs: 51200,
    channels: 4,
    stored_time: 1,
    iepe_excit_current_A: 0.002,
    NI_mode: 'DAQmx_Val_Diff',
    pretrig_samples: 128,
    pretrig_threshold: 0.1,
  });
  // The configure reply never arrives in this test; keep the pending
  // promise from surfacing as an unhandled rejection when the socket is GC'd.
  void rh.promise.catch(() => {});
});

// ---- Wave C: output stimulus + pretrigger arm on the log message ----

/** Build a real .dvma carrying full container provenance (units, cal, driver). */
function dvmaWithMeta() {
  const nSamples = 4, nChannels = 2, fs = 8000;
  const timeAxis = Float64Array.from({ length: nSamples }, (_, i) => i / fs);
  const data = Float64Array.from({ length: nSamples * nChannels }, (_, i) => i + 0.5);
  const ds: DvmaDataset = {
    formatVersion: 2,
    pydvmaVersion: 'webui',
    items: [{
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [nSamples], data: timeAxis, isComplex: false },
        time_data: { shape: [nSamples, nChannels], data, isComplex: false },
      },
      meta: {
        test_name: 'hammer_test',
        timestring: '2026-07-07 12:00:00',
        timestamp: '2026-07-07T12:00:00',
        units: ['V', 'V'],
        channel_cal_factors: [2.5, 1.0],
      },
      settings: { fs, channels: nChannels, stored_time: nSamples / fs, device_driver: 'nidaq' },
    }],
  };
  return { bytes: writeDvma(ds), nSamples, nChannels, fs };
}

test('output kwargs pass through onto the log message when enabled (contract)', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({ outputEnabled: true, outputType: 'sweep', outputAmp: 0.5, outputF1: 20, outputF2: 2000 });
  const rh = bp.startRecording({ sampleRate: 8000, channelCount: 2, durationS: 0.5 });
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', fs: 8000, channels: 2 });
  await tick();
  const logMsg = fake.sentJson().find((m) => m.type === 'log');
  // The wire contract for the stimulus: log.output = {type, amp, f1, f2}.
  expect(logMsg).toMatchObject({ output: { type: 'sweep', amp: 0.5, f1: 20, f2: 2000 } });
  void rh.promise.catch(() => {});
});

test('output + pretrigger are null on the log message when disabled (free-run)', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const rh = bp.startRecording({ sampleRate: 8000, channelCount: 1, durationS: 0.5 });
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', fs: 8000, channels: 1 });
  await tick();
  const logMsg = fake.sentJson().find((m) => m.type === 'log');
  expect(logMsg!.output).toBeNull();
  expect(logMsg!.pretrigger).toBeNull();
  void rh.promise.catch(() => {});
});

test('an armed pretrigger sends the pretrigger object; status events surface and a timeout still resolves', async () => {
  const { bytes, nSamples, nChannels, fs } = dvmaWithMeta();
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const events: LogStatusEvent[] = [];
  bp.onLogStatus((e) => events.push(e));
  bp.setConfig({ pretrigArmed: true, pretrigSamples: 500, pretrigThreshold: 0.05, pretrigChannel: 1, pretrigTimeout: 0.2 });

  const rh = bp.startRecording({ sampleRate: fs, channelCount: nChannels, durationS: 0.5 });
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', fs, channels: nChannels });
  await tick();
  // The log message carries the pretrigger object (arm authoritative).
  const logMsg = fake.sentJson().find((m) => m.type === 'log');
  expect(logMsg).toMatchObject({
    pretrigger: { samples: 500, threshold: 0.05, channel: 1, timeout: 0.2 },
  });

  // Server arms, then times out (MockRecorder never triggers) — NOT an error.
  fake.emitJson({ type: 'status', event: 'armed' });
  fake.emitJson({ type: 'status', event: 'timeout' });
  await tick();
  expect(events).toEqual(['armed', 'timeout']);

  // The capture still lands, and its provenance is preserved.
  fake.emitJson({ type: 'log_result', nChannels, nSamples, fs, byteLength: bytes.length });
  await tick();
  fake.emitBinary(containerFrame(bytes, nChannels, nSamples, fs));
  const rec = await rh.promise;
  expect(rec.nSamples).toBe(nSamples);
  expect(bp.lastMeta()).toMatchObject({ deviceDriver: 'nidaq', testName: 'hammer_test' });
});

test('an explicit large pretrigger sample count raises chunk_size to fit the buffer', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({ pretrigArmed: true, pretrigSamples: 500 }); // > default chunk_size 100
  const rh = bp.startRecording({ sampleRate: 8000, channelCount: 2, durationS: 0.5 });
  fake.open();
  await tick();
  // configure is sent immediately (before the configured reply); it must
  // carry chunk_size >= the effective pretrig samples so log_data accepts it.
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  expect(cfg!.settings).toMatchObject({ chunk_size: 500 });
  void rh.promise.catch(() => {});
});

test('a bare arm defaults to 100 samples and does NOT raise chunk_size (round-4 item 11)', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({ pretrigArmed: true }); // bare arm → default 100 (= default chunk_size)
  const rh = bp.startRecording({ sampleRate: 8000, channelCount: 2, durationS: 0.5 });
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', fs: 8000, channels: 2 });
  await tick();
  // 100 <= default chunk_size 100 → no override (the old 1000 default wastefully
  // enlarged the buffer; 100 fits the default context buffer).
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  expect(cfg!.settings.chunk_size).toBeUndefined();
  // …and the log's pretrigger object carries the 100-sample default.
  expect(BARE_ARM_PRETRIG_SAMPLES).toBe(100); // matches options.py default chunk_size
  const logMsg = fake.sentJson().find((m) => m.type === 'log');
  expect(logMsg!.pretrigger).toMatchObject({ samples: BARE_ARM_PRETRIG_SAMPLES });
  void rh.promise.catch(() => {});
});

test('a small pretrigger sample count leaves chunk_size at the server default', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({ pretrigArmed: true, pretrigSamples: 64 });
  const rh = bp.startRecording({ sampleRate: 8000, channelCount: 1, durationS: 0.5 });
  fake.open();
  await tick();
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  // 64 <= default 100 → no chunk_size override (server keeps its default).
  expect(cfg!.settings.chunk_size).toBeUndefined();
  void rh.promise.catch(() => {});
});

test('fuller output kwargs: duration on the output spec, device/channels on configure (round-4 item 12)', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({
    outputEnabled: true, outputType: 'sweep', outputAmp: 0.4, outputF1: 20, outputF2: 2000,
    outputDuration: 0.25, outputDeviceId: 'nidaq:1', outputChannels: 2,
  });
  const rh = bp.startRecording({ deviceId: 'nidaq:0', sampleRate: 51200, channelCount: 4, durationS: 1 });
  fake.open();
  await tick();
  // Output device + channels ride the configure message as MySettings kwargs.
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  expect(cfg!.settings).toMatchObject({
    output_device_driver: 'nidaq', output_device_index: 1, output_channels: 2,
  });
  fake.emitJson({ type: 'status', event: 'configured', fs: 51200, channels: 4 });
  await tick();
  // The stimulus waveform + its duration ride the log message's output spec.
  const logMsg = fake.sentJson().find((m) => m.type === 'log');
  expect(logMsg).toMatchObject({
    output: { type: 'sweep', amp: 0.4, f1: 20, f2: 2000, duration: 0.25 },
  });
  void rh.promise.catch(() => {});
});

test('output device/channels are omitted from configure when output is disabled', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  // Device/channels set, but the stimulus is OFF → they stay out of configure.
  bp.setConfig({ outputEnabled: false, outputDeviceId: 'nidaq:1', outputChannels: 2 });
  const rh = bp.startRecording({ deviceId: 'nidaq:0', sampleRate: 51200, channelCount: 4, durationS: 1 });
  fake.open();
  await tick();
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  expect(cfg!.settings.output_device_driver).toBeUndefined();
  expect(cfg!.settings.output_channels).toBeUndefined();
  void rh.promise.catch(() => {});
});

test('a staged output_fs clamp rides configure when the stimulus is enabled — not when off', async () => {
  // Enabled: the store-derived AO rate clamp (USB-6003 AO at 5 kS/s) maps
  // onto the MySettings output_fs kwarg, so the server never falls back to
  // its output_fs = fs default (which the device rejects at log time).
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({
    outputEnabled: true, outputType: 'sweep', outputAmp: 0.4, outputF1: 20, outputF2: 500,
    outputFs: 5000,
  });
  const rh = bp.startRecording({ deviceId: 'nidaq:0', sampleRate: 8000, channelCount: 1, durationS: 1 });
  fake.open();
  await tick();
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  expect(cfg!.settings).toMatchObject({ fs: 8000, output_fs: 5000 });
  void rh.promise.catch(() => {});

  // Disabled: no stimulus → no AO task, so the clamp stays out of configure.
  const fake2 = makeFakeWs();
  const bp2 = new BridgeProvider('ws://x/ws', () => fake2.ws);
  bp2.setConfig({ outputEnabled: false, outputFs: 5000 });
  const rh2 = bp2.startRecording({ deviceId: 'nidaq:0', sampleRate: 8000, channelCount: 1, durationS: 1 });
  fake2.open();
  await tick();
  const cfg2 = fake2.sentJson().find((m) => m.type === 'configure');
  expect(cfg2!.settings.output_fs).toBeUndefined();
  void rh2.promise.catch(() => {});
});

// ---- Wave C: bridged-set metadata join ----

test('recordingMetaFromDvma extracts provenance from a container', () => {
  const { bytes } = dvmaWithMeta();
  expect(recordingMetaFromDvma(bytes)).toEqual({
    testName: 'hammer_test',
    timestring: '2026-07-07 12:00:00',
    timestamp: '2026-07-07T12:00:00',
    units: ['V', 'V'],
    channelCalFactors: [2.5, 1.0],
    deviceDriver: 'nidaq',
  });
});

test('recordingMetaFromDvma reads the driver from a bare (web_audio) container', () => {
  const nSamples = 2, nChannels = 1, fs = 1000;
  const timeAxis = Float64Array.from({ length: nSamples }, (_, i) => i / fs);
  const data = Float64Array.from([0.1, 0.2]);
  const bytes = writeDvma(recordingToDataset({ data, timeAxis, fs, nChannels, nSamples }, 'x'));
  const meta = recordingMetaFromDvma(bytes);
  expect(meta?.deviceDriver).toBe('web_audio');
  expect(meta?.testName).toBe('x');
});

// ---- Wave C: per-device caps ----

test('normalizeCaps parses per-device caps; outputCapable honours a per-device ao override', async () => {
  // Real Wave-C shape: fs_ladders / max_channels are per-device maps keyed
  // by deviceId; device_caps carries the per-device ao flag.
  const caps = {
    ...CAPS,
    ao: true,
    fs_ladders: { 'nidaq:0': [25600, 51200], 'soundcard:0': [44100, 48000] },
    max_channels: {
      'nidaq:0': { input: 4, output: 2 },
      'soundcard:0': { input: 2, output: 2 },
    },
    device_caps: {
      'mock:0': { driver: 'mock', index: 0, name: 'Mock', ao: true },
      'nidaq:0': { driver: 'nidaq', index: 0, name: 'cDAQ1Mod1', ao: false },
      'soundcard:0': { driver: 'soundcard', index: 0, name: 'Built-in Mic', ao: true },
    },
  };
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const capsP = bp.capabilities();
  fake.open();
  await tick();
  fake.emitJson(caps);
  const c = await capsP;
  expect(c!.device_caps!['nidaq:0'].ao).toBe(false);
  // deviceCapsFor reads fs from fs_ladders[id], channels from max_channels[id].input.
  expect(deviceCapsFor(c, 'nidaq:0')).toEqual({ fs_ladder: [25600, 51200], max_channels: 4, ao: false });
  // Global ao true, but nidaq:0 has per-device ao:false → output group hidden;
  // soundcard:0 has per-device ao:true → visible.
  expect(outputCapable(c, 'nidaq:0')).toBe(false);
  expect(outputCapable(c, 'soundcard:0')).toBe(true);
});

test('deviceCapsFor falls back to the NI ai_channel_count when max_channels lacks an entry', () => {
  const caps: BridgeCaps = {
    v: 1,
    backends: ['nidaq'],
    devices: {
      soundcard: [],
      nidaq: [{
        name: 'cDAQ1Mod1', product_type: 'NI 9234', is_chassis: false,
        ai_channel_count: 4, ao_channel_count: 0,
        module_names: [], module_ai_counts: {}, module_ao_counts: {},
      }],
    },
    fs_ladders: { 'nidaq:0': [51200] },
    max_channels: null,
    pretrigger: true,
    ao: false,
  };
  expect(deviceCapsFor(caps, 'nidaq:0')).toEqual({ fs_ladder: [51200], max_channels: 4 });
  expect(outputCapable(caps, 'nidaq:0')).toBe(false); // no global ao
});

test('outputCapable / deviceCapsFor are null-safe for the Web Audio path', () => {
  expect(outputCapable(null, 'x')).toBe(false);
  expect(deviceCapsFor(null, 'x')).toBeNull();
});

// ---- Wave D / round-4: output-device enumeration ----

test('outputDevices lists AO-capable devices with names + output channel counts', () => {
  const caps: BridgeCaps = {
    v: 1,
    backends: ['mock', 'nidaq'],
    devices: {
      soundcard: [],
      nidaq: [{
        name: 'cDAQ1', product_type: 'cDAQ-9174', is_chassis: true,
        ai_channel_count: 4, ao_channel_count: 2,
        module_names: [], module_ai_counts: {}, module_ao_counts: {},
      }],
    },
    fs_ladders: { 'nidaq:0': [51200] },
    max_channels: { 'nidaq:0': { input: 4, output: 2 }, 'mock:0': { input: 2, output: 2 } },
    pretrigger: true,
    ao: true,
    device_caps: {
      'mock:0': { driver: 'mock', index: 0, name: 'Mock signal generator', ao: true },
      'nidaq:0': { driver: 'nidaq', index: 0, name: 'cDAQ1', ao: true, ao_vmax: 4.2426 },
      // An input-only device (ao:false) must NOT appear as an output option.
      'nidaq:1': { driver: 'nidaq', index: 1, name: 'input-only', ao: false },
    },
  };
  const out = outputDevices(caps);
  expect(out.map((d) => d.deviceId).sort()).toEqual(['mock:0', 'nidaq:0']);
  const ni = out.find((d) => d.deviceId === 'nidaq:0');
  expect(ni).toMatchObject({ label: 'cDAQ1', maxChannels: 2 });
  // mock has no max_channels entry → maxChannels undefined but still listed.
  expect(out.find((d) => d.deviceId === 'mock:0')).toMatchObject({ label: 'Mock signal generator' });
});

test('outputDevices is empty for the Web Audio path or a bridge with no AO', () => {
  expect(outputDevices(null)).toEqual([]);
  const noAo: BridgeCaps = {
    v: 1, backends: ['nidaq'], devices: { soundcard: [], nidaq: [] },
    fs_ladders: {}, max_channels: null, pretrigger: true, ao: false,
    device_caps: { 'nidaq:0': { driver: 'nidaq', index: 0, name: 'x', ao: false } },
  };
  expect(outputDevices(noAo)).toEqual([]);
});

// ---- Wave D follow-up: voltage caps + clamp helper ----

test('deviceCapsFor surfaces per-device ai_vmax / ao_vmax voltage rails', () => {
  const caps: BridgeCaps = {
    v: 1,
    backends: ['nidaq'],
    devices: {
      soundcard: [],
      nidaq: [{
        name: 'cDAQ1', product_type: 'cDAQ-9174', is_chassis: true,
        ai_channel_count: 4, ao_channel_count: 2,
        module_names: [], module_ai_counts: {}, module_ao_counts: {},
      }],
    },
    fs_ladders: { 'nidaq:0': [51200] },
    max_channels: { 'nidaq:0': { input: 4, output: 2 } },
    pretrigger: true,
    ao: true,
    device_caps: {
      // 9234 AI rail ±5 V; 9260 AO rail ±4.2426 V (below the 5 V default!).
      'nidaq:0': { driver: 'nidaq', index: 0, name: 'cDAQ1', ao: true, ai_vmax: 5, ao_vmax: 4.2426 },
    },
  };
  expect(deviceCapsFor(caps, 'nidaq:0')).toMatchObject({
    fs_ladder: [51200], max_channels: 4, ao: true, ai_vmax: 5, ao_vmax: 4.2426,
  });
});

test('deviceCapsFor omits non-positive / absent vmax (mock/soundcard have none)', () => {
  const caps: BridgeCaps = {
    v: 1, backends: ['mock'],
    devices: { soundcard: [], nidaq: [] },
    fs_ladders: {}, max_channels: null, pretrigger: true, ao: true,
    device_caps: {
      'mock:0': { driver: 'mock', index: 0, name: 'Mock', ao: true }, // no vmax keys
      'nidaq:9': { driver: 'nidaq', index: 9, name: 'weird', ao: false, ai_vmax: 0, ao_vmax: -1 },
    },
  };
  expect(deviceCapsFor(caps, 'mock:0')?.ai_vmax).toBeUndefined();
  const ni = deviceCapsFor(caps, 'nidaq:9');
  expect(ni?.ai_vmax).toBeUndefined(); // 0 rejected (not > 0)
  expect(ni?.ao_vmax).toBeUndefined(); // -1 rejected
});

test('clampVoltage clamps down to a rail but passes through when under it or when no cap', () => {
  expect(clampVoltage(5, 4.2426)).toBe(4.2426); // over the rail → clamped
  expect(clampVoltage(3, 4.2426)).toBe(3);       // under the rail → unchanged
  expect(clampVoltage(5, undefined)).toBe(5);    // no cap (mock/soundcard) → unchanged
  expect(clampVoltage(5, 0)).toBe(5);            // non-positive cap ignored
  expect(PYDVMA_DEFAULT_VMAX).toBe(5);           // mirrors options.py VmaxNI=5
});

test('VmaxNI / output_VmaxNI kwargs flow into the configure message', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  bp.setConfig({ vmaxNI: 5, outputVmaxNI: 4.2426 });
  const rh = bp.startRecording({ deviceId: 'nidaq:0', sampleRate: 51200, channelCount: 4, durationS: 1 });
  fake.open();
  await tick();
  const cfg = fake.sentJson().find((m) => m.type === 'configure');
  expect(cfg!.settings).toMatchObject({ VmaxNI: 5, output_VmaxNI: 4.2426 });
  void rh.promise.catch(() => {});
});

// ---- Wave D follow-up: onConfigured (DSA coerced-fs) ----

test('onConfigured fires from a monitor configure with requested vs resolved fs', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const infos: ConfiguredInfo[] = [];
  bp.onConfigured((i) => infos.push(i));

  const monP = bp.startMonitor({ sampleRate: 8000, channelCount: 2 }, () => {});
  fake.open();
  await tick();
  // The device coerces 8000 → 8533.33 (DSA snap) and reports it in `configured`.
  fake.emitJson({ type: 'status', event: 'configured', fs: 8533.33, channels: 2 });
  await tick();
  fake.emitJson({ type: 'status', event: 'monitoring' });
  await monP;

  expect(infos).toEqual([{ requestedFs: 8000, configuredFs: 8533.33, channels: 2 }]);
});

test('onConfigured fires from a log configure too (requested == resolved when honoured)', async () => {
  const { bytes, nSamples, nChannels, fs } = dvmaWithMeta();
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const infos: ConfiguredInfo[] = [];
  bp.onConfigured((i) => infos.push(i));

  const rh = bp.startRecording({ sampleRate: fs, channelCount: nChannels, durationS: 0.5 });
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', fs, channels: nChannels });
  await tick();
  fake.emitJson({ type: 'log_result', nChannels, nSamples, fs, byteLength: bytes.length });
  await tick();
  fake.emitBinary(containerFrame(bytes, nChannels, nSamples, fs));
  await rh.promise;

  expect(infos).toEqual([{ requestedFs: fs, configuredFs: fs, channels: nChannels }]);
});

test('onConfigured is skipped when the configured reply carries no usable fs', async () => {
  const fake = makeFakeWs();
  const bp = new BridgeProvider('ws://x/ws', () => fake.ws);
  const infos: ConfiguredInfo[] = [];
  bp.onConfigured((i) => infos.push(i));

  const monP = bp.startMonitor({ sampleRate: 44100, channelCount: 1 }, () => {});
  fake.open();
  await tick();
  fake.emitJson({ type: 'status', event: 'configured', channels: 1 }); // no fs
  await tick();
  fake.emitJson({ type: 'status', event: 'monitoring' });
  await monP;

  expect(infos).toEqual([]);
});
