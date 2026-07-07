/**
 * Unit tests for the capture AudioWorklet processor (capture.worklet.js).
 *
 * The processor runs in AudioWorkletGlobalScope in production, so it depends
 * on the `AudioWorkletProcessor` base class and the `registerProcessor`
 * global.  Here we stub both, import the module (whose top-level
 * `registerProcessor(...)` call hands us the class), then instantiate and
 * drive `process()` with fake 128-frame render quanta to verify the
 * load-bearing accumulation + interleaving contract:
 *
 *   - 128-frame quanta accumulate to the requested chunkFrames before a post
 *   - the posted chunk is interleaved row-major (frame, channel)
 *   - the underlying ArrayBuffer is transferred (zero-copy)
 *   - a chunkFrames that is NOT a multiple of 128 splits correctly, carrying
 *     the partial fill into the next quantum
 *   - process() stays alive (returns true) across empty/idle renders
 */
import { expect, test, vi, beforeEach, afterEach } from 'vitest';

const RENDER_QUANTUM = 128;

/** Per-instance fake of the AudioWorkletGlobalScope base class. */
class FakeAudioWorkletProcessor {
  port = { postMessage: vi.fn(), onmessage: null as unknown };
}

let registered: { name: string; ctor: new (opts?: unknown) => any } | null = null;

beforeEach(() => {
  registered = null;
  vi.stubGlobal('AudioWorkletProcessor', FakeAudioWorkletProcessor);
  vi.stubGlobal('registerProcessor', (name: string, ctor: new (opts?: unknown) => any) => {
    registered = { name, ctor };
  });
});
afterEach(() => vi.restoreAllMocks());

/** Re-import the worklet module against the current global stubs. */
async function loadProcessor() {
  vi.resetModules();
  await import('../../src/lib/audio/capture.worklet.js');
  if (!registered) throw new Error('worklet did not call registerProcessor');
  return registered;
}

/** Build one planar quantum of `nCh` channels where ch c holds a tagged ramp. */
function quantum(startFrame: number, nCh: number, frames = RENDER_QUANTUM): Float32Array[] {
  const chans: Float32Array[] = [];
  for (let c = 0; c < nCh; c++) {
    const a = new Float32Array(frames);
    // Encode both the global frame index and the channel so interleave order
    // is unambiguous: value = globalFrame * 10 + channel.
    for (let i = 0; i < frames; i++) a[i] = (startFrame + i) * 10 + c;
    chans.push(a);
  }
  return chans;
}

test('registers under the expected processor name', async () => {
  const { name } = await loadProcessor();
  expect(name).toBe('pydvma-capture');
});

test('accumulates 128-frame quanta into a 2048-frame interleaved chunk (2ch)', async () => {
  const { ctor } = await loadProcessor();
  const proc = new ctor({ processorOptions: { chunkFrames: 2048, nChannels: 2 } });

  const posts: Array<{ msg: any; transfer: any }> = [];
  proc.port.postMessage = (msg: any, transfer: any) => posts.push({ msg, transfer });

  // 2048 / 128 = 16 quanta fill exactly one chunk.
  for (let q = 0; q < 16; q++) {
    const keep = proc.process([quantum(q * RENDER_QUANTUM, 2)], [], {});
    expect(keep).toBe(true);
    if (q < 15) expect(posts).toHaveLength(0); // no early post
  }

  expect(posts).toHaveLength(1);
  const { msg, transfer } = posts[0];
  expect(msg.nSamples).toBe(2048);
  expect(msg.nChannels).toBe(2);
  expect(msg.data).toBeInstanceOf(Float32Array);
  expect(msg.data.length).toBe(2048 * 2);

  // Interleave check across the whole chunk: data[frame*2 + ch] == frame*10+ch.
  for (const frame of [0, 1, 127, 128, 1000, 2047]) {
    expect(msg.data[frame * 2 + 0]).toBe(frame * 10 + 0);
    expect(msg.data[frame * 2 + 1]).toBe(frame * 10 + 1);
  }

  // Zero-copy: the chunk's ArrayBuffer is transferred.
  expect(Array.isArray(transfer)).toBe(true);
  expect(transfer[0]).toBeInstanceOf(ArrayBuffer);
});

test('posts successive chunks with continuous data across the boundary', async () => {
  const { ctor } = await loadProcessor();
  const proc = new ctor({ processorOptions: { chunkFrames: 2048, nChannels: 1 } });

  const posts: any[] = [];
  proc.port.postMessage = (msg: any) => posts.push(msg);

  for (let q = 0; q < 32; q++) proc.process([quantum(q * RENDER_QUANTUM, 1)], [], {});

  expect(posts).toHaveLength(2);
  // First chunk covers global frames 0..2047, second 2048..4095.
  expect(posts[0].data[0]).toBe(0);
  expect(posts[0].data[2047]).toBe(2047 * 10);
  expect(posts[1].data[0]).toBe(2048 * 10);
  expect(posts[1].data[2047]).toBe(4095 * 10);
});

test('chunkFrames not a multiple of the quantum splits + carries the remainder', async () => {
  const { ctor } = await loadProcessor();
  // 200 is not a multiple of 128: quantum 1 fills 128, quantum 2 completes at
  // frame 200 (posting), then carries 56 frames into the next accumulator.
  const proc = new ctor({ processorOptions: { chunkFrames: 200, nChannels: 1 } });

  const posts: any[] = [];
  proc.port.postMessage = (msg: any) => posts.push(msg);

  proc.process([quantum(0, 1)], [], {});   // 128 frames, filled=128, no post
  expect(posts).toHaveLength(0);
  proc.process([quantum(128, 1)], [], {});  // reaches 200 → posts, carries 56
  expect(posts).toHaveLength(1);
  expect(posts[0].nSamples).toBe(200);
  expect(posts[0].data.length).toBe(200);
  expect(posts[0].data[0]).toBe(0);
  expect(posts[0].data[199]).toBe(199 * 10);

  // The carried 56 frames (200..255) plus more must land in the next chunk.
  for (let f = 256; f < 400; f += RENDER_QUANTUM) proc.process([quantum(f, 1)], [], {});
  // 56 (carried) + 128 + 128 = 312 ≥ 200 → exactly one more full chunk posted.
  expect(posts).toHaveLength(2);
  expect(posts[1].nSamples).toBe(200);
  expect(posts[1].data[0]).toBe(200 * 10); // continuity: first carried frame
});

test('stays alive across empty / idle renders and posts nothing', async () => {
  const { ctor } = await loadProcessor();
  const proc = new ctor({ processorOptions: { chunkFrames: 2048, nChannels: 2 } });
  const posts: any[] = [];
  proc.port.postMessage = (msg: any) => posts.push(msg);

  expect(proc.process([], [], {})).toBe(true);            // no input at all
  expect(proc.process([[]], [], {})).toBe(true);          // input with 0 channels
  expect(posts).toHaveLength(0);
});

test('defaults: chunkFrames 2048, nChannels 1 when processorOptions omitted', async () => {
  const { ctor } = await loadProcessor();
  const proc = new ctor(); // no options
  const posts: any[] = [];
  proc.port.postMessage = (msg: any) => posts.push(msg);

  for (let q = 0; q < 16; q++) proc.process([quantum(q * RENDER_QUANTUM, 1)], [], {});
  expect(posts).toHaveLength(1);
  expect(posts[0].nSamples).toBe(2048);
  expect(posts[0].nChannels).toBe(1);
});
