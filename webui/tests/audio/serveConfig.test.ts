import { expect, test } from 'vitest';
import { describeServePatch, mapServeConfig, pushedSettingsRefusal } from '../../src/lib/audio/serveConfig';
import { DEFAULT_SETTINGS } from '../../src/lib/stores/acquire';
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

test('pretrig_samples null / "None" DISARMS (present-null clears)', () => {
  for (const v of [null, 'None']) {
    const p = mapServeConfig({ pretrig_samples: v, fs: 8000 }, devices)!;
    expect(p.bridge.pretrigArmed).toBe(false);
    expect(p.bridge.pretrigSamples).toBeNull();
  }
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

// ---- round-11: the trigger prefill reaches the fields the new UI reads ----

test('a served pretrigger prefills the SAME store fields Setup and Acquire edit', () => {
  const p = mapServeConfig({
    fs: 10000,                    // deliberately OFF-ladder: must pass through
    channels: 2,
    stored_time: 5,
    pretrig_samples: 250,
    pretrig_threshold: 0.3,
    pretrig_channel: 1,
    pretrig_timeout: 8,
  }, devices)!;
  // fs is not second-guessed here — the combo can display any rate now, and
  // the Setup notes say what the hardware will really run at.
  expect(p.settings.sampleRate).toBe(10000);
  // Arming is implied by a sample count, and the trigger group reads exactly
  // these four fields (a served config that armed nothing was a dead config).
  expect(p.bridge).toMatchObject({
    pretrigSamples: 250,
    pretrigArmed: true,
    pretrigThreshold: 0.3,
    pretrigChannel: 1,
    pretrigTimeout: 8,
  });
});

test('a negative served threshold is ignored (the recorder compares |x|)', () => {
  const p = mapServeConfig({ fs: 8000, pretrig_threshold: -0.2 }, devices)!;
  expect(p.bridge.pretrigThreshold).toBeUndefined();
  // …while an explicit zero is kept: it is a stated value, not an absent one.
  const q = mapServeConfig({ fs: 8000, pretrig_threshold: 0 }, devices)!;
  expect(q.bridge.pretrigThreshold).toBe(0);
});

// ---- present-null clears, absent leaves alone (Session.apply_settings) ----

test('an absent key leaves the app value alone: no patch key at all', () => {
  const p = mapServeConfig({ fs: 8000 }, devices)!;
  expect('pretrigArmed' in p.bridge).toBe(false);
  expect('pretrigThreshold' in p.bridge).toBe(false);
  expect('vmaxNI' in p.bridge).toBe(false);
  expect('channelCount' in p.settings).toBe(false);
});

test('a null threshold CLEARS to the app default, never a threshold of 0', () => {
  // Number(null) is 0: a careless parse turned "use the default" into
  // "trigger on the noise floor".
  const p = mapServeConfig({ pretrig_samples: 100, pretrig_threshold: null }, devices)!;
  expect('pretrigThreshold' in p.bridge).toBe(true);
  expect(p.bridge.pretrigThreshold).toBeUndefined();
  expect(p.bridge.pretrigArmed).toBe(true);
});

test('null channel / timeout / NI fields clear to undefined (app defaults)', () => {
  const p = mapServeConfig({
    pretrig_channel: null, pretrig_timeout: null, VmaxNI: null, output_VmaxNI: null,
    NI_mode: null, input_channels_spec: null, iepe_excit_current_A: [null, null],
  }, devices)!;
  for (const k of ['pretrigChannel', 'pretrigTimeout', 'vmaxNI', 'outputVmaxNI',
    'niMode', 'inputChannelsSpec', 'iepeExcitCurrentA'] as const) {
    expect(k in p.bridge, k).toBe(true);
    expect(p.bridge[k], k).toBeUndefined();
  }
});

test('null core fields return Setup to its defaults; a null driver picks Default', () => {
  const p = mapServeConfig({ fs: null, channels: null, stored_time: null, device_driver: null }, devices)!;
  expect(p.settings).toEqual({
    sampleRate: DEFAULT_SETTINGS.sampleRate, channelCount: DEFAULT_SETTINGS.channelCount,
    durationS: DEFAULT_SETTINGS.durationS, deviceId: '',
  });
});

test('empty strings and booleans are not numbers', () => {
  const p = mapServeConfig({ fs: '', channels: true, pretrig_threshold: '' }, devices);
  expect(p).toBeNull();
});

test('the hammer → noise round trip: arm, then a null count disarms', () => {
  const hammer = mapServeConfig({ fs: 3000, channels: 2, stored_time: 6,
    pretrig_samples: 100, pretrig_threshold: 0.25 }, devices)!;
  expect(hammer.bridge).toMatchObject({ pretrigArmed: true, pretrigSamples: 100, pretrigThreshold: 0.25 });
  const noise = mapServeConfig({ fs: 3000, channels: 2, stored_time: 30,
    pretrig_samples: null, pretrig_threshold: null }, devices)!;
  expect(noise.bridge.pretrigArmed).toBe(false);
  expect(noise.settings.durationS).toBe(30);
});

test('output: null disables the stimulus; a lone null field does not enable it', () => {
  expect(mapServeConfig({ output: null }, devices)!.bridge.outputEnabled).toBe(false);
  const p = mapServeConfig({ output_amp: null }, devices)!;
  expect('outputEnabled' in p.bridge).toBe(false);
  expect(p.bridge.outputAmp).toBeUndefined();
});

test('analysis defaults: window + TF averaging, null clears, junk ignored', () => {
  expect(mapServeConfig({ analysis_window: 'none', tf_averaging: 'across' }, devices)!.analysis)
    .toEqual({ window: 'none', tfAveraging: 'across' });
  expect(mapServeConfig({ analysis_window: null, tf_averaging: null }, devices)!.analysis)
    .toEqual({ window: null, tfAveraging: null });
  expect(mapServeConfig({ analysis_window: 'flattop', tf_averaging: 'sideways' }, devices)).toBeNull();
});

test('a driver this server does not list is named in notes', () => {
  const p = mapServeConfig({ device_driver: 'nidaq', device_index: 9, fs: 8000 }, devices)!;
  expect(p.notes).toEqual(['nidaq device 9 is not listed by this server, so Setup kept its input device.']);
  expect(mapServeConfig({ fs: 8000 }, devices)!.notes).toEqual([]);
});

test('describeServePatch summarises the headline fields for the toast', () => {
  const p = mapServeConfig({ fs: 3000, channels: 2, stored_time: 6, pretrig_samples: 100,
    analysis_window: 'none' }, devices)!;
  expect(describeServePatch(p)).toBe('3000 Hz · 2 ch · 6 s · trigger armed · window none');
});

test('pushedSettingsRefusal: busy while recording or during a Nonlin run', () => {
  expect(pushedSettingsRefusal({ acquireStatus: 'idle', blaPhase: 'idle' })).toBeNull();
  expect(pushedSettingsRefusal({ acquireStatus: 'done', blaPhase: 'done' })).toBeNull();
  expect(pushedSettingsRefusal({ acquireStatus: 'recording', blaPhase: 'idle' })).toMatch(/capture is in progress/);
  expect(pushedSettingsRefusal({ acquireStatus: 'idle', blaPhase: 'running' })).toMatch(/Nonlin run/);
  expect(pushedSettingsRefusal({ acquireStatus: 'idle', blaPhase: 'analysing' })).toMatch(/Nonlin run/);
});
