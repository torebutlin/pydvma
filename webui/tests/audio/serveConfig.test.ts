import { expect, test } from 'vitest';
import { mapServeConfig } from '../../src/lib/audio/serveConfig';
import type { AudioInputDevice } from '../../src/lib/audio/provider';

/** A minimal enumerated device list (mock + one NI). */
const devices: AudioInputDevice[] = [
  { deviceId: 'mock:0', label: 'Mock signal generator', groupId: 'mock', hasLabel: true },
  { deviceId: 'nidaq:0', label: 'NI: cDAQ1 (4 ch)', groupId: 'nidaq', hasLabel: true },
  { deviceId: 'nidaq:1', label: 'NI: 9260 (0 ch)', groupId: 'nidaq', hasLabel: true },
];

test('full MySettings maps onto settings + bridge patches', () => {
  const cfg = {
    fs: 8000, channels: 4, stored_time: 1.5,
    device_driver: 'nidaq', device_index: 0,
    pretrig_samples: 200, pretrig_threshold: 0.1, pretrig_channel: 1, pretrig_timeout: 5,
    VmaxNI: 5, output_VmaxNI: 4.2426, NI_mode: 'DAQmx_Val_PseudoDiff',
    iepe_excit_current_A: 0.002, input_channels_spec: 'cDAQ1Mod1/ai0:3',
    output: { type: 'sweep', amp: 0.5, f1: 20, f2: 2000, duration: 1.0 },
    output_device_driver: 'nidaq', output_device_index: 1, output_channels: 1,
  };
  const p = mapServeConfig(cfg, devices)!;
  expect(p).not.toBeNull();
  expect(p.settings).toEqual({ sampleRate: 8000, channelCount: 4, durationS: 1.5, deviceId: 'nidaq:0' });
  expect(p.bridge.pretrigSamples).toBe(200);
  expect(p.bridge.pretrigArmed).toBe(true);
  expect(p.bridge.pretrigThreshold).toBe(0.1);
  expect(p.bridge.pretrigChannel).toBe(1);
  expect(p.bridge.pretrigTimeout).toBe(5);
  expect(p.bridge.vmaxNI).toBe(5);
  expect(p.bridge.outputVmaxNI).toBe(4.2426);
  expect(p.bridge.niMode).toBe('DAQmx_Val_PseudoDiff');
  expect(p.bridge.iepeExcitCurrentA).toBe(0.002);
  expect(p.bridge.inputChannelsSpec).toBe('cDAQ1Mod1/ai0:3');
  expect(p.bridge.outputEnabled).toBe(true);
  expect(p.bridge.outputType).toBe('sweep');
  expect(p.bridge.outputAmp).toBe(0.5);
  expect(p.bridge.outputF1).toBe(20);
  expect(p.bridge.outputF2).toBe(2000);
  expect(p.bridge.outputDuration).toBe(1.0);
  expect(p.bridge.outputDeviceId).toBe('nidaq:1');
  expect(p.bridge.outputChannels).toBe(1);
});

test('mock driver maps to mock:0', () => {
  const p = mapServeConfig({ device_driver: 'mock', fs: 44100 }, devices)!;
  expect(p.settings.deviceId).toBe('mock:0');
  expect(p.settings.sampleRate).toBe(44100);
});

test('a partial config patches only present fields', () => {
  const p = mapServeConfig({ fs: 48000, channels: 2 }, devices)!;
  expect(p.settings).toEqual({ sampleRate: 48000, channelCount: 2 });
  expect(p.bridge).toEqual({});           // nothing else
});

test('flat output_* keys enable the output group too', () => {
  const p = mapServeConfig({ output_type: 'gaussian', output_amp: 0.2 }, devices)!;
  expect(p.bridge.outputEnabled).toBe(true);
  expect(p.bridge.outputType).toBe('gaussian');
  expect(p.bridge.outputAmp).toBe(0.2);
});

test('a device the bridge does not expose is skipped (no phantom selection)', () => {
  const p = mapServeConfig({ device_driver: 'nidaq', device_index: 9, fs: 8000 }, devices)!;
  expect(p.settings.deviceId).toBeUndefined();   // nidaq:9 not enumerated
  expect(p.settings.sampleRate).toBe(8000);
});

test('pretrig_samples null / "None" does not arm', () => {
  expect(mapServeConfig({ pretrig_samples: null, fs: 8000 }, devices)!.bridge.pretrigArmed)
    .toBeUndefined();
  expect(mapServeConfig({ pretrig_samples: 'None', fs: 8000 }, devices)!.bridge.pretrigArmed)
    .toBeUndefined();
});

test('iepe as a per-channel array takes the first element', () => {
  const p = mapServeConfig({ iepe_excit_current_A: [0.002, 0.0, 0.002] }, devices)!;
  expect(p.bridge.iepeExcitCurrentA).toBe(0.002);
});

test('garbage inputs return null (no throw)', () => {
  expect(mapServeConfig(null, devices)).toBeNull();
  expect(mapServeConfig(undefined, devices)).toBeNull();
  expect(mapServeConfig('nope', devices)).toBeNull();
  expect(mapServeConfig(42, devices)).toBeNull();
  expect(mapServeConfig([1, 2, 3], devices)).toBeNull();
  expect(mapServeConfig({}, devices)).toBeNull();               // empty object → null
  expect(mapServeConfig({ unknown_key: 5, fs: 'bad' }, devices)).toBeNull();  // no valid field
});

test('malformed numeric fields are skipped, valid ones kept', () => {
  const p = mapServeConfig({ fs: -1, channels: 0, stored_time: 'x', VmaxNI: 5 }, devices)!;
  expect(p.settings.sampleRate).toBeUndefined();   // fs must be > 0
  expect(p.settings.channelCount).toBeUndefined(); // channels must be > 0
  expect(p.settings.durationS).toBeUndefined();
  expect(p.bridge.vmaxNI).toBe(5);                 // the one valid field
});
