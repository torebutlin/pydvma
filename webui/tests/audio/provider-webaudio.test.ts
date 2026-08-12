/**
 * Tests for the WebAudioProvider's round-5 output/pretrigger capabilities
 * (src/lib/audio/provider.ts): it reports the webaudio kind (null bridge caps),
 * and maps the stored BridgeConfig (the SAME object the Acquire card edits)
 * into the Web-Audio RecordConfig extensions on startRecording.  `source.ts`
 * is mocked so the mapping can be inspected without opening a real mic.
 */
import { expect, test, vi, beforeEach } from 'vitest';

// vi.mock is hoisted above module init, so build the spy via vi.hoisted.
const { startRecordingMock } = vi.hoisted(() => ({
  startRecordingMock: vi.fn(() => ({ promise: Promise.resolve(), cancel() {}, elapsed: () => 0 })),
}));
vi.mock('../../src/lib/audio/source', () => ({
  enumerateInputDevices: vi.fn().mockResolvedValue([]),
  startRecording: startRecordingMock,
  startMonitor: vi.fn().mockResolvedValue({ stop() {}, fs: 44100, nChannels: 1 }),
}));

import {
  WebAudioProvider,
  WEB_AUDIO_DEFAULT_OUTPUT_AMP,
  WEB_AUDIO_DEFAULT_PRETRIG_THRESHOLD,
  BARE_ARM_PRETRIG_SAMPLES,
  DEFAULT_PRETRIG_TIMEOUT_S,
} from '../../src/lib/audio/provider';
import type { MultisineStimulusConfig, RecordConfig } from '../../src/lib/audio/source';

function lastRecordConfig(): RecordConfig {
  return startRecordingMock.mock.calls.at(-1)![0] as unknown as RecordConfig;
}

beforeEach(() => startRecordingMock.mockClear());

test('WebAudioProvider reports the webaudio kind and no bridge capability doc', async () => {
  const p = new WebAudioProvider();
  expect(p.kind).toBe('webaudio');
  expect(await p.capabilities()).toBeNull();
});

test('setConfig output + pretrig map into the RecordConfig extensions', () => {
  const p = new WebAudioProvider();
  const events: string[] = [];
  p.onLogStatus((e) => events.push(e));
  p.setConfig({
    outputEnabled: true, outputType: 'gaussian', outputAmp: 0.4, outputF1: 20, outputF2: 400,
    outputDuration: 0.5, outputChannels: 2, outputDeviceId: 'spk-1',
    pretrigArmed: true, pretrigSamples: 128, pretrigThreshold: 0.08, pretrigChannel: 1, pretrigTimeout: 2,
  });
  p.startRecording({ sampleRate: 8000, channelCount: 1, durationS: 1 });

  const cfg = lastRecordConfig();
  expect(cfg.output).toMatchObject({
    type: 'gaussian', amp: 0.4, f1: 20, f2: 400, durationS: 0.5, channels: 2, deviceId: 'spk-1',
  });
  expect(cfg.pretrig).toMatchObject({ channel: 1, threshold: 0.08, pretrigSamples: 128, timeoutS: 2 });
  // The pretrig lifecycle sink is threaded through so status flows.
  expect(typeof cfg.pretrig!.onStatus).toBe('function');
  cfg.pretrig!.onStatus!('armed');
  expect(events).toEqual(['armed']);
});

test('unset output/pretrig fields fall back to the displayed Acquire defaults', () => {
  const p = new WebAudioProvider();
  p.setConfig({ outputEnabled: true, pretrigArmed: true });
  p.startRecording({ sampleRate: 8000, channelCount: 1, durationS: 1 });

  const cfg = lastRecordConfig();
  expect(cfg.output).toMatchObject({ type: 'sweep', amp: WEB_AUDIO_DEFAULT_OUTPUT_AMP, f1: 10, f2: 500 });
  // The timeout default is the SERVER's (20 s) and the one the Acquire card
  // displays — round-11 collapsed three different numbers into one constant.
  expect(cfg.pretrig).toMatchObject({
    channel: 0, threshold: WEB_AUDIO_DEFAULT_PRETRIG_THRESHOLD,
    pretrigSamples: BARE_ARM_PRETRIG_SAMPLES, timeoutS: DEFAULT_PRETRIG_TIMEOUT_S,
  });
});

test('no output / pretrig extensions when both flags are off', () => {
  const p = new WebAudioProvider();
  p.setConfig({ outputEnabled: false, pretrigArmed: false });
  p.startRecording({ sampleRate: 8000, channelCount: 1, durationS: 1 });

  const cfg = lastRecordConfig();
  expect(cfg.output).toBeUndefined();
  expect(cfg.pretrig).toBeUndefined();
});

test('a per-capture outputOverride survives the card-config merge intact', () => {
  const p = new WebAudioProvider();
  // The card's classic stimulus is ON — the BLA override must beat it for this
  // capture WITHOUT erasing it, so the card's own state is untouched.
  p.setConfig({ outputEnabled: true, outputType: 'sweep', outputAmp: 0.3, outputF1: 10, outputF2: 500 });
  const override: MultisineStimulusConfig = {
    type: 'multisine', nSamples: 512, k1: 2, k2: 20, pPeriods: 2, tPeriods: 1,
    seed: 99, m: 1, e: 0, nExc: 1, ampRms: 0.05,
  };
  p.startRecording({ sampleRate: 8000, channelCount: 1, durationS: 1, outputOverride: override });

  const cfg = lastRecordConfig();
  expect(cfg.outputOverride).toEqual(override);                  // not dropped by the merge
  expect(cfg.output).toMatchObject({ type: 'sweep', amp: 0.3 }); // card stimulus still merged in
  // (source.ts resolves `outputOverride ?? output`, so the multisine is what plays.)
});
