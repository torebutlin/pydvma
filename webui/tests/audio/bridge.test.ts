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
  MAGIC,
  HEADER_SIZE,
  MSG_CHUNK,
  MSG_CONTAINER,
  type WsLike,
} from '../../src/lib/audio/bridge';
import type { MonitorChunk } from '../../src/lib/audio/source';
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
