/**
 * Tests for the acquire store's Web Audio output/pretrigger capability seam
 * (round-5 item 10): the reactive `kind` store and the enumerated
 * `webOutputDevices` list that light up the Acquire card's output + pretrigger
 * groups WITHOUT populating `bridgeCaps` (so SetupCard's bridge detection is
 * unaffected).
 */
import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { createAcquireStore } from '../../src/lib/stores/acquire';
import { capabilities } from '../../src/lib/stores/stages';

beforeEach(() => {
  capabilities.set({ liveSource: false, fitEngine: false });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test('kind is webaudio by default and bridgeCaps stays null', async () => {
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue([
        { deviceId: 'mic-1', label: 'Mic', groupId: 'g', kind: 'audioinput', toJSON: () => ({}) },
      ]),
      getUserMedia: vi.fn(),
    },
  });
  const store = createAcquireStore();
  expect(get(store.kind)).toBe('webaudio');
  await store.init();
  // bridgeCaps must remain null on the Web Audio path (SetupCard reads it as
  // the bridge discriminator).
  expect(get(store.bridgeCaps)).toBeNull();
});

test('init enumerates output devices when the browser can select an output (setSinkId)', async () => {
  // A setSinkId-capable AudioContext makes supportsOutputDeviceSelection() true.
  class Ctx { setSinkId() { return Promise.resolve(); } }
  vi.stubGlobal('AudioContext', Ctx);
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue([
        { deviceId: 'mic-1', label: 'Mic', groupId: 'g', kind: 'audioinput', toJSON: () => ({}) },
        { deviceId: 'spk-1', label: 'Speakers', groupId: 'g', kind: 'audiooutput', toJSON: () => ({}) },
        { deviceId: 'spk-2', label: 'Headphones', groupId: 'g', kind: 'audiooutput', toJSON: () => ({}) },
      ]),
      getUserMedia: vi.fn(),
    },
  });
  const store = createAcquireStore();
  await store.init();
  expect(get(store.webOutputDevices)).toEqual([
    { deviceId: 'spk-1', label: 'Speakers' },
    { deviceId: 'spk-2', label: 'Headphones' },
  ]);
});

test('output devices stay empty where the browser cannot select an output (no setSinkId)', async () => {
  class Ctx {} // no setSinkId → supportsOutputDeviceSelection() false
  vi.stubGlobal('AudioContext', Ctx);
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue([
        { deviceId: 'mic-1', label: 'Mic', groupId: 'g', kind: 'audioinput', toJSON: () => ({}) },
        { deviceId: 'spk-1', label: 'Speakers', groupId: 'g', kind: 'audiooutput', toJSON: () => ({}) },
      ]),
      getUserMedia: vi.fn(),
    },
  });
  const store = createAcquireStore();
  await store.init();
  expect(get(store.webOutputDevices)).toEqual([]); // select hides → default output
});
