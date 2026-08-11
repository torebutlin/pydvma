import { get } from 'svelte/store';
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import {
  createBlaStore,
  defaultBlaDesign,
  deriveBla,
  binFor,
  periodSamplesFor,
  preflightBla,
  firstBlaError,
  outputRailFor,
  excitationLabel,
  BLA_BRIDGE_PEAK_MARGIN,
  BLA_CAPTURE_MARGIN_SAMPLES,
  type BlaActions,
  type BlaDesign,
  type BlaPreflightInput,
} from '../../src/lib/stores/bla';
import { createAcquireStore } from '../../src/lib/stores/acquire';
import { createSelection } from '../../src/lib/stores/selection';
import { capabilities } from '../../src/lib/stores/stages';
import type { EngineStore } from '../../src/lib/stores/engine';
import type { RecordConfig, Recording } from '../../src/lib/audio/source';
import {
  PYDVMA_DEFAULT_VMAX,
  type BridgeCaps,
  type BridgeConfig,
  type SourceProvider,
} from '../../src/lib/audio/provider';

beforeEach(() => {
  capabilities.set({ liveSource: false, fitEngine: false });
  vi.stubGlobal('navigator', {
    mediaDevices: {
      enumerateDevices: vi.fn().mockResolvedValue([]),
      getUserMedia: vi.fn(),
    },
  });
});
afterEach(() => vi.restoreAllMocks());

// ---- fixtures ----

const FS = 48000;

/** A design that resolves to N = 480, k1 = 10, k2 = 50 at 48 kHz. */
function testDesign(over: Partial<BlaDesign> = {}): BlaDesign {
  return {
    ...defaultBlaDesign(),
    f1Hz: 1000, f2Hz: 5000, dfHz: 100, ampRms: 0.05,
    M: 2, P: 2, tPeriods: 1, testName: 'run',
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 0 }],
    ...over,
  };
}

/** Two enabled excitations measured on channels 0 and 1. */
function misoDesign(over: Partial<BlaDesign> = {}): BlaDesign {
  return testDesign({
    outputs: [
      { aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 0 },
      { aoChannel: 1, enabled: true, xMode: 'measured', xChannel: 1 },
    ],
    ...over,
  });
}

function baseInput(over: Partial<BlaPreflightInput> = {}): BlaPreflightInput {
  const design = over.design ?? testDesign();
  const channelCount = over.channelCount ?? 2;
  return {
    design,
    values: over.values ?? deriveBla(design, FS, channelCount),
    requestedFs: FS,
    channelCount,
    lpfOn: false,
    pretrigArmed: false,
    providerKind: 'webaudio',
    caps: null,
    inputDeviceId: '',
    outputRail: 1,
    seed: 1234,
    ...over,
  };
}

/** Bridge caps for one NI device (M-series ⇒ hardware-timed AO). */
function niCaps(over: Partial<BridgeCaps> = {}): BridgeCaps {
  return {
    v: 1,
    backends: ['mock', 'nidaq'],
    devices: {
      soundcard: [],
      nidaq: [{
        name: 'Dev1', product_type: 'USB-6212', is_chassis: false,
        ai_channel_count: 16, ao_channel_count: 2,
        module_names: [], module_ai_counts: {}, module_ao_counts: {},
      }],
    },
    fs_ladders: { 'nidaq:0': [FS] },
    max_channels: { 'nidaq:0': { input: 16, output: 2 } },
    pretrigger: true,
    ao: true,
    device_caps: {
      'nidaq:0': { ao: true, product_type: 'USB-6212', is_chassis: false, ao_vmax: 10 },
    },
    ...over,
  };
}

/** Bridge caps for a cDAQ chassis (phase-coherent, NOT sample-accurate). */
function chassisCaps(): BridgeCaps {
  const caps = niCaps();
  caps.devices.nidaq[0] = {
    ...caps.devices.nidaq[0], name: 'cDAQ1', product_type: 'cDAQ-9174', is_chassis: true,
  };
  caps.device_caps!['nidaq:0'] = {
    ao: true, product_type: 'cDAQ-9174', is_chassis: true, ao_vmax: 4.2426,
  };
  return caps;
}

/** A fake provider that returns a synthetic capture of the requested length. */
function fakeProvider(opts: { kind?: 'webaudio' | 'bridge'; fs?: number; caps?: BridgeCaps } = {}) {
  const configs: RecordConfig[] = [];
  const provider: SourceProvider & { configs: RecordConfig[]; bridgeConfig: BridgeConfig } = {
    kind: opts.kind ?? 'webaudio',
    configs,
    bridgeConfig: {},
    capabilities: async () => opts.caps ?? null,
    enumerateInputDevices: async () => [],
    startRecording(cfg: RecordConfig) {
      configs.push({ ...cfg });
      const fs = opts.fs ?? FS;
      const nSamples = Math.max(1, Math.round(cfg.durationS * fs));
      const rec: Recording = {
        data: new Float64Array(nSamples * cfg.channelCount),
        timeAxis: Float64Array.from({ length: nSamples }, (_, i) => i / fs),
        fs,
        nChannels: cfg.channelCount,
        nSamples,
      };
      return { promise: Promise.resolve(rec), cancel: () => {}, elapsed: () => 0 };
    },
    startMonitor: async () => ({ stop: () => {}, fs: FS, nChannels: 1 }),
    setConfig(cfg: BridgeConfig) { provider.bridgeConfig = { ...cfg }; },
  };
  return provider;
}

/**
 * Actions double: registers each landed item with the REAL selection store
 * (so tray visibility is testable) and records what it was asked to land.
 */
function fakeActions(selection: ReturnType<typeof createSelection>, nChannels: number) {
  const landed: string[] = [];
  const actions: BlaActions & { landed: string[]; blaCalls: unknown[][] } = {
    landed,
    blaCalls: [],
    addRecordedSet: (item) => {
      const name = String(item.meta.test_name);
      landed.push(name);
      return selection.addSet({ name, nChannels, durationS: 0, timestamp: '' });
    },
    addBlaSets: (results, o) => {
      actions.blaCalls.push([results, o]);
      return results.map((_, q) =>
        selection.addSet({ name: `bla${q}`, nChannels: 1, durationS: 0, timestamp: '' }));
    },
  };
  return actions;
}

function fakeEngine(result: unknown = []) {
  const enqueue = vi.fn(async () => result);
  const boot = vi.fn(async () => {});
  return {
    engine: { boot, enqueue, whenReady: async () => {}, status: null, client: null } as unknown as EngineStore,
    boot,
    enqueue,
  };
}

/** A minimal calc_bla-shaped result payload (one excitation, one response). */
function blaResult() {
  return [{
    freq_axis: { shape: [3], data: Float64Array.from([100, 200, 300]), complex: false },
    tf_data: { shape: [3, 1], data: Float64Array.from([1, 0, 1, 0, 1, 0]), complex: true },
    coherence: null,
    bla_sigma_nl: { shape: [3, 1], data: Float64Array.from([0.1, 0.1, 0.1]), complex: false },
    bla_sigma_n: { shape: [3, 1], data: Float64Array.from([0.01, 0.01, 0.01]), complex: false },
    bla: { x_mode: 'measured', q: 0 },
  }];
}

function makeStore(over: {
  design?: BlaDesign;
  channelCount?: number;
  provider?: ReturnType<typeof fakeProvider>;
  engineResult?: unknown;
} = {}) {
  const provider = over.provider ?? fakeProvider();
  const acquire = createAcquireStore(provider);
  const channelCount = over.channelCount ?? 2;
  acquire.patch({ sampleRate: FS, channelCount, durationS: 3.5 });
  const selection = createSelection();
  const actions = fakeActions(selection, channelCount);
  const { engine, boot, enqueue } = fakeEngine(over.engineResult ?? blaResult());
  const views: string[] = [];
  const bla = createBlaStore({
    acquire, actions, engine, selection, viewState: { activate: (v) => views.push(v) },
  });
  bla.design.set(over.design ?? testDesign());
  return { bla, acquire, actions, selection, provider, boot, enqueue, views };
}

/**
 * Same, but on a BRIDGE provider advertising a sample-synced NI device — the
 * only path where commanded x is admissible. `init()` pulls the caps in, then
 * the device is selected (which re-runs the store's voltage/rate clamps).
 */
async function makeBridgeStore(over: { design?: BlaDesign; channelCount?: number } = {}) {
  const provider = fakeProvider({ kind: 'bridge', caps: niCaps() });
  const s = makeStore({ ...over, provider });
  await s.acquire.init();
  s.acquire.patch({ deviceId: 'nidaq:0' });
  return s;
}

// ---- derived maths ----

test('period length and excited bins follow N = round(fs/df), k = round(f*N/fs)', () => {
  expect(periodSamplesFor(48000, 100)).toBe(480);
  expect(periodSamplesFor(44100, 7)).toBe(6300);
  expect(periodSamplesFor(48000, 0)).toBe(0);          // nonsense request → flagged, never NaN

  const v = deriveBla(testDesign(), FS, 2);
  expect(v.periodSamples).toBe(480);
  expect(v.periodS).toBeCloseTo(0.01, 12);
  expect(v.k1).toBe(10);
  expect(v.k2).toBe(50);
  expect(v.linesCount).toBe(41);
});

test('bins clamp into [1, floor((N-1)/2)] — DC and Nyquist are never excited', () => {
  const N = 480;
  expect(binFor(0, N, FS)).toBe(1);                    // DC clamps up
  expect(binFor(40000, N, FS)).toBe(239);              // above Nyquist clamps down
  expect(binFor(24000, N, FS)).toBe(239);              // the Nyquist bin itself is excluded
  const v = deriveBla(testDesign({ f1Hz: 0, f2Hz: 40000 }), FS, 2);
  expect(v.k1).toBe(1);
  expect(v.k2).toBe(239);
});

test('capture length carries rounding slack and totals the whole run', () => {
  const d = testDesign({ M: 3, tPeriods: 1, P: 2 });
  const v = deriveBla(d, FS, 2);
  expect(v.captureSamples).toBe(3 * 480 + BLA_CAPTURE_MARGIN_SAMPLES);
  expect(v.captureS).toBeCloseTo(v.captureSamples / FS, 12);
  expect(v.totalRunS).toBeCloseTo(3 * 1 * v.captureS, 12);   // M * n_exc * capture
});

test('responses are every channel that is not a measured drive', () => {
  expect(deriveBla(testDesign(), FS, 4).respChannels).toEqual([1, 2, 3]);
  expect(deriveBla(misoDesign(), FS, 4).respChannels).toEqual([2, 3]);
  // Commanded x measures nothing, so every input channel is a response.
  const commanded = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'commanded', xChannel: null }],
  });
  const v = deriveBla(commanded, FS, 3);
  expect(v.xMode).toBe('commanded');
  expect(v.xChannels).toEqual([]);
  expect(v.respChannels).toEqual([0, 1, 2]);
  // A disabled row does not count towards n_exc.
  expect(deriveBla(misoDesign({
    outputs: [
      { aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 0 },
      { aoChannel: 1, enabled: false, xMode: 'measured', xChannel: 1 },
    ],
  }), FS, 3).nExc).toBe(1);
});

// ---- preflight ----

test('a sound design passes preflight cleanly', () => {
  expect(preflightBla(baseInput())).toEqual([]);
});

test('a staged output_fs clamp is an ERROR, never a silent clamp', () => {
  const checks = preflightBla(baseInput({
    providerKind: 'bridge', caps: niCaps(), inputDeviceId: 'nidaq:0', stagedOutputFs: 5000,
  }));
  expect(checks.some((c) => c.code === 'output-fs' && !c.ok)).toBe(true);
  expect(firstBlaError(checks)).toMatch(/output_fs = fs/);
});

test('the digital low-pass is refused (it resamples away the periodicity)', () => {
  const checks = preflightBla(baseInput({ lpfOn: true }));
  const lpf = checks.find((c) => c.code === 'lpf');
  expect(lpf?.ok).toBe(false);
  expect(lpf?.reason).toMatch(/resamples/);
});

test('an armed pretrigger is an advisory, not a failure', () => {
  const checks = preflightBla(baseInput({ pretrigArmed: true }));
  expect(checks).toHaveLength(1);
  expect(checks[0].ok).toBe(true);                     // advisory ⇒ the run may start
  expect(checks[0].code).toBe('pretrigger');
  expect(firstBlaError(checks)).toBe('');
});

test('commanded x is refused unless the caps prove a ROUTED AI sample clock', () => {
  const design = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'commanded', xChannel: null }],
  });
  const values = deriveBla(design, FS, 2);
  const reason = (over: Partial<BlaPreflightInput>) =>
    preflightBla(baseInput({ design, values, ...over })).find((c) => c.code === 'commanded-sync');
  const bridged = (over: Partial<BlaPreflightInput>) =>
    reason({ providerKind: 'bridge', inputDeviceId: 'nidaq:0', ...over });

  // Browser / soundcard: no sync possible.
  expect(reason({})?.ok).toBe(false);
  // Software-timed AO (USB-6003) — cannot share the AI clock at all.
  const sw = niCaps();
  sw.devices.nidaq[0].product_type = 'USB-6003';
  sw.device_caps!['nidaq:0'].product_type = 'USB-6003';
  expect(bridged({ caps: sw })?.ok).toBe(false);
  // cDAQ chassis: AI/AO ride the chassis timebase (phase-coherent) but the
  // per-module AI sample clock is NOT routable as an AO source, so the drive
  // is not sample-accurate — commanded x must be refused there too.
  expect(bridged({ caps: chassisCaps() })?.ok).toBe(false);
  expect(bridged({ caps: chassisCaps() })?.reason).toMatch(/non-chassis/);
  // Unknown hardware (no product_type reported) cannot PROVE sync.
  const bare = niCaps();
  bare.devices.nidaq[0].product_type = '';
  delete bare.device_caps!['nidaq:0'].product_type;
  expect(bridged({ caps: bare })?.ok).toBe(false);
  // Right hardware, but the AO runs on a different device.
  expect(bridged({ caps: niCaps(), outputDeviceId: 'nidaq:1' })?.ok).toBe(false);
  // Right hardware, but the AO rate is clamped away from fs.
  expect(bridged({ caps: niCaps(), stagedOutputFs: 5000 })?.ok).toBe(false);
  // Right hardware, but the capture is resampled by the digital low-pass.
  expect(bridged({ caps: niCaps(), lpfOn: true })?.ok).toBe(false);
  // M-series, same device, matched rate ⇒ allowed.
  expect(bridged({ caps: niCaps() })).toBeUndefined();
});

test('a mixed measured/commanded table is refused', () => {
  const design = misoDesign({
    outputs: [
      { aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 0 },
      { aoChannel: 1, enabled: true, xMode: 'commanded', xChannel: null },
    ],
  });
  const checks = preflightBla(baseInput({ design, values: deriveBla(design, FS, 3), channelCount: 3 }));
  expect(checks.find((c) => c.code === 'x-mode')?.reason).toMatch(/same x source/);
});

test('measured-x channels must be distinct and in range, leaving a response', () => {
  const overlap = misoDesign({
    outputs: [
      { aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 0 },
      { aoChannel: 1, enabled: true, xMode: 'measured', xChannel: 0 },
    ],
  });
  expect(preflightBla(baseInput({
    design: overlap, values: deriveBla(overlap, FS, 3), channelCount: 3,
  })).find((c) => c.code === 'x-channels')?.reason).toMatch(/more than one excitation/);

  const outOfRange = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 5 }],
  });
  expect(preflightBla(baseInput({
    design: outOfRange, values: deriveBla(outOfRange, FS, 2), channelCount: 2,
  })).find((c) => c.code === 'x-channels')?.reason).toMatch(/outside the 2 captured/);

  // One channel captured and it carries the drive ⇒ nothing left to measure.
  expect(preflightBla(baseInput({ channelCount: 1, values: deriveBla(testDesign(), FS, 1) }))
    .find((c) => c.code === 'resp-channels')?.ok).toBe(false);
});

test('the enabled outputs must be the prefix ao0..ao(n-1), in order', () => {
  // `aoChannel` is decorative in V1: the run reduces the table to a COUNT and
  // both generators write excitation q to buffer column q, which the server
  // maps onto the device's FIRST n_exc analog outputs. Enabling ao1 alone
  // would therefore drive ao0 — refused rather than silently re-routed.
  const only1 = misoDesign({
    outputs: [
      { aoChannel: 0, enabled: false, xMode: 'measured', xChannel: 0 },
      { aoChannel: 1, enabled: true, xMode: 'measured', xChannel: 1 },
    ],
  });
  const gap = preflightBla(baseInput({
    design: only1, values: deriveBla(only1, FS, 3), channelCount: 3,
  })).find((c) => c.code === 'ao-prefix');
  expect(gap?.ok).toBe(false);
  expect(gap?.reason).toMatch(/drives ao0…ao0 in order, but the table enables ao1/);
  expect(gap?.reason).toMatch(/per-channel routing is a follow-up/);

  // A hole in the middle of a wider selection is refused the same way.
  const holed = misoDesign({
    outputs: [
      { aoChannel: 0, enabled: true, xMode: 'measured', xChannel: 0 },
      { aoChannel: 1, enabled: false, xMode: 'measured', xChannel: 1 },
      { aoChannel: 2, enabled: true, xMode: 'measured', xChannel: 2 },
    ],
  });
  expect(preflightBla(baseInput({
    design: holed, values: deriveBla(holed, FS, 4), channelCount: 4,
  })).find((c) => c.code === 'ao-prefix')?.ok).toBe(false);

  // The prefix selections pass: ao0 alone, and ao0+ao1.
  expect(preflightBla(baseInput())).toEqual([]);
  const two = misoDesign();
  expect(preflightBla(baseInput({
    design: two, values: deriveBla(two, FS, 3), channelCount: 3,
  }))).toEqual([]);
});

test('n_exc cannot exceed the output device AO channel count', () => {
  const caps = niCaps();
  caps.max_channels = { 'nidaq:0': { input: 16, output: 1 } };
  const design = misoDesign();
  const checks = preflightBla(baseInput({
    design, values: deriveBla(design, FS, 3), channelCount: 3,
    providerKind: 'bridge', caps, inputDeviceId: 'nidaq:0',
  }));
  expect(checks.find((c) => c.code === 'ao-channels')?.reason)
    .toMatch(/2 excitations but the output device has only 1/);
});

test('the peak guard checks every (m, e), not just the first', () => {
  // A level far above the rail fails; the same design under the rail passes.
  const hot = testDesign({ ampRms: 10, M: 3 });
  const checks = preflightBla(baseInput({ design: hot, values: deriveBla(hot, FS, 2) }));
  expect(checks.find((c) => c.code === 'peak')?.reason).toMatch(/exceeds the limit/);
  expect(preflightBla(baseInput())).toEqual([]);
  // Skipping the guard (the card's live validation) leaves the hot design clean.
  expect(preflightBla(baseInput({ design: hot, values: deriveBla(hot, FS, 2) }), { peakCheck: false }))
    .toEqual([]);
});

test('the peak limit is the SERVER rail (output_VmaxNI), never the device ao_vmax', () => {
  expect(outputRailFor('webaudio', {}, '')).toBe(1);
  // Unset output_VmaxNI ⇒ the server runs at its 5 V default even on a device
  // whose AO can swing to 10 V (6212/6003 report ao_vmax = 10). Checking the
  // peak against 10 would pass a level here that hard-fails at capture (0, 0).
  expect(outputRailFor('bridge', {}, 'nidaq:0')).toBe(PYDVMA_DEFAULT_VMAX);
  expect(PYDVMA_DEFAULT_VMAX).toBe(5);
  // A staged rail (the acquire store clamps down to a 9260's ±4.2426 V) wins.
  expect(outputRailFor('bridge', { outputVmaxNI: 4.2426 }, 'nidaq:0')).toBe(4.2426);
  expect(outputRailFor('bridge', {}, 'soundcard:0')).toBe(1);         // VmaxSC default
  // The output-device select repoints the rail at the chosen device's driver.
  expect(outputRailFor('bridge', { outputDeviceId: 'soundcard:0' }, 'nidaq:0')).toBe(1);
});

test('a level between the 5 V server rail and a 10 V device rail is REFUSED', () => {
  // The regression this guards: peak ∈ (5, 10] V passed preflight against
  // ao_vmax and then hard-failed at the first capture.
  const design = testDesign({ ampRms: 2 });                   // peak ≈ 6.25 V
  const values = deriveBla(design, FS, 2);
  const railed = preflightBla(baseInput({
    design, values, providerKind: 'bridge', caps: niCaps(), inputDeviceId: 'nidaq:0',
    outputRail: outputRailFor('bridge', {}, 'nidaq:0'),
  }));
  // ±4.85 = the 5 V rail less the bridge headroom margin (see below).
  expect(railed.find((c) => c.code === 'peak')?.reason).toMatch(/exceeds the limit ±4.85/);
  // Explicitly staging the wider rail (a device that really can swing 10 V)
  // admits the same level — the check follows the setting, not the capability.
  expect(preflightBla(baseInput({
    design, values, providerKind: 'bridge', caps: niCaps(), inputDeviceId: 'nidaq:0',
    outputRail: outputRailFor('bridge', { outputVmaxNI: 10 }, 'nidaq:0'),
  }))).toEqual([]);
});

test('the bridge peak sweep keeps headroom for the server PRNG; the browser does not', () => {
  // The sweep generates with mulberry32, but the SERVER redraws the phases
  // with numpy — same amplitude law, different crest factor — so a level just
  // under the rail can pass here and trip `multisine_generator` mid-run.
  // peak ≈ 4.91 V: inside the 5 V rail, past 0.97 × 5 = 4.85.
  expect(BLA_BRIDGE_PEAK_MARGIN).toBe(0.97);
  const design = testDesign({ ampRms: 1.57 });
  const values = deriveBla(design, FS, 2);
  const peakCheck = (providerKind: 'webaudio' | 'bridge') =>
    preflightBla(baseInput({
      design, values, providerKind, outputRail: 5,
      caps: providerKind === 'bridge' ? niCaps() : null,
      inputDeviceId: providerKind === 'bridge' ? 'nidaq:0' : '',
    })).find((c) => c.code === 'peak');
  // Browser: these ARE the waveforms that play, so the full rail is honest.
  expect(peakCheck('webaudio')).toBeUndefined();
  expect(peakCheck('bridge')?.ok).toBe(false);
});

// ---- run sequencing ----

test('a run issues M x n_exc captures in (m, e) order with one shared seed', async () => {
  const { bla, provider, actions } = makeStore({ design: misoDesign({ M: 2 }), channelCount: 3 });
  await bla.start({ seed: 4242 });

  expect(provider.configs).toHaveLength(4);
  const specs = provider.configs.map((c) => c.outputOverride as { m: number; e: number; seed: number; nExc: number });
  expect(specs.map((s) => [s.m, s.e])).toEqual([[0, 0], [0, 1], [1, 0], [1, 1]]);
  expect(specs.every((s) => s.seed === 4242)).toBe(true);   // ONE seed for the whole run
  expect(specs.every((s) => s.nExc === 2)).toBe(true);
  expect(specs[0]).toMatchObject({
    type: 'multisine', nSamples: 480, k1: 10, k2: 50, pPeriods: 2, tPeriods: 1, ampRms: 0.05,
  });

  // Every capture landed as its own named raw set.
  expect(actions.landed).toEqual(['run r1e1', 'run r1e2', 'run r2e1', 'run r2e2']);
  const st = get(bla.state);
  expect(st.rawSetIds).toHaveLength(4);
  expect(st.phase).toBe('done');
});

test('raw capture sets land hidden so M x n sets do not flood the tray', async () => {
  const { bla, selection } = makeStore();
  await bla.start({ seed: 7 });
  const ids = get(bla.state).rawSetIds;
  expect(ids).toHaveLength(2);

  const offFor = (id: number) => get(selection.setsView).find((s) => s.id === id)?.allOff;
  expect(ids.map(offFor)).toEqual([true, true]);        // hidden by default
  bla.setRawVisible(true);
  expect(ids.map(offFor)).toEqual([false, false]);      // the card's "show raw captures"
  bla.setRawVisible(false);
  expect(ids.map(offFor)).toEqual([true, true]);
});

test('capture duration is staged per run and the user value restored afterwards', async () => {
  const { bla, acquire, provider } = makeStore();
  expect(get(acquire.settings).durationS).toBe(3.5);
  await bla.start({ seed: 1 });
  // (t + P) * N + margin = 3*480 + 256 = 1696 samples at 48 kHz.
  expect(provider.configs[0].durationS).toBeCloseTo(1696 / FS, 12);
  expect(get(acquire.settings).durationS).toBe(3.5);            // restored
});

test('phase transitions run through running → analysing → done', async () => {
  const seen: string[] = [];
  const { bla } = makeStore();
  const unsub = bla.state.subscribe((s) => {
    if (seen[seen.length - 1] !== s.phase) seen.push(s.phase);
  });
  await bla.start({ seed: 3 });
  unsub();
  expect(seen).toEqual(['idle', 'running', 'analysing', 'done']);
});

test('cancel stops between captures, keeps what landed, and dispatches no analysis', async () => {
  const { bla, acquire, provider, enqueue } = makeStore({ design: misoDesign({ M: 3 }), channelCount: 3 });
  const unsub = bla.state.subscribe((s) => {
    if (s.phase === 'running' && s.rawSetIds.length === 2) bla.cancel();
  });
  await bla.start({ seed: 9 });
  unsub();

  expect(provider.configs.length).toBe(2);            // stopped before the third
  const st = get(bla.state);
  expect(st.phase).toBe('cancelled');
  expect(st.rawSetIds).toHaveLength(2);               // already-landed sets stay
  expect(enqueue).not.toHaveBeenCalled();
  expect(get(acquire.settings).durationS).toBe(3.5);  // duration restored on cancel too
});

test('the Acquire card cancelling a capture reads as cancelled, not as an error', async () => {
  const provider = fakeProvider();
  const inner = provider.startRecording.bind(provider);
  provider.startRecording = (cfg) => {
    const h = inner(cfg);
    return { ...h, promise: Promise.reject(new Error('cancelled')) };
  };
  const { bla, acquire, enqueue } = makeStore({ provider });
  await bla.start({ seed: 21 });
  expect(get(bla.state).phase).toBe('cancelled');
  expect(get(bla.state).error).toBe('');
  expect(enqueue).not.toHaveBeenCalled();
  expect(get(acquire.settings).durationS).toBe(3.5);
});

test('an armed pretrigger is disarmed for the run and restored after', async () => {
  const { bla, acquire } = makeStore();
  acquire.patchBridge({ pretrigArmed: true });
  let armedDuringRun: boolean | undefined;
  const unsub = bla.state.subscribe((s) => {
    if (s.phase === 'running' && armedDuringRun === undefined) {
      armedDuringRun = get(acquire.bridgeConfig).pretrigArmed;
    }
  });
  await bla.start({ seed: 5 });
  unsub();
  expect(armedDuringRun).toBe(false);
  expect(get(acquire.bridgeConfig).pretrigArmed).toBe(true);
  expect(get(bla.state).notes).toEqual([expect.stringContaining('Pretrigger disarmed')]);
});

// ---- analysis dispatch + results ----

test('calc_bla is booted, sent snake_case run_spec, and its sets land', async () => {
  const { bla, actions, boot, enqueue, views } = makeStore({
    design: misoDesign({ M: 2 }), channelCount: 3,
  });
  await bla.start({ seed: 88 });

  expect(boot).toHaveBeenCalled();                 // MANDATORY first-compute kick
  const [op, payload] = enqueue.mock.calls[0] as [string, Record<string, unknown>];
  expect(op).toBe('calc_bla');
  expect(payload.run_spec).toEqual({
    multisine: {
      n_samples: 480, k1: 10, k2: 50, p_periods: 2, t_periods: 1,
      seed: 88, amp_rms: 0.05, n_exc: 2, M: 2,
    },
    x_mode: 'measured',
    x_channels: [0, 1],
    resp_channels: [2],
    fs: FS,
  });
  // The capture list is the (m, e)-ordered ensemble the engine op requires.
  const arrays = payload.time_arrays as { n_channels: number; fs: number }[];
  expect(arrays).toHaveLength(4);
  expect(arrays.every((a) => a.n_channels === 3 && a.fs === FS)).toBe(true);

  const st = get(bla.state);
  expect(st.phase).toBe('done');
  expect(st.resultSetIds).toHaveLength(1);
  expect(st.runSpec?.multisine.seed).toBe(88);
  expect(views).toEqual(['tf']);                   // the plot jumps to TF
  const [, opts] = actions.blaCalls[0] as [unknown[], { names: string[]; channelLabels: string[] }];
  expect(opts.names).toEqual(['run BLA q1 (via ch0)']);
  expect(opts.channelLabels).toEqual(['ch_2']);
});

test('excitationLabel names an excitation the same way everywhere', () => {
  // The result set's tray name is this label behind the test name, and the
  // card's verdict line is the label alone — one helper, so they cannot drift.
  expect(excitationLabel(0, 'measured', [2, 3])).toBe('q1 (via ch2)');
  expect(excitationLabel(1, 'measured', [2, 3])).toBe('q2 (via ch3)');
  expect(excitationLabel(0, 'commanded', null)).toBe('q1 (commanded)');
  // A run spec that never recorded the channel (or a stale index) degrades to
  // 'ch?' rather than rendering 'chundefined'.
  expect(excitationLabel(5, 'measured', [0])).toBe('q6 (via ch?)');
  expect(excitationLabel(0, 'measured')).toBe('q1 (via ch?)');
});

test('a commanded run on the browser path is refused before any capture', async () => {
  const design = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'commanded', xChannel: null }],
  });
  const { bla, actions, enqueue, provider } = makeStore({ design, channelCount: 2 });
  await bla.start({ seed: 2 });
  expect(get(bla.state).phase).toBe('error');
  expect(get(bla.state).error).toMatch(/sample-synced NI output/);
  expect(provider.configs).toHaveLength(0);
  expect(enqueue).not.toHaveBeenCalled();
  expect(actions.blaCalls).toHaveLength(0);
});

test('a commanded run sends x_mode commanded, x_channels null, every input a response', async () => {
  const design = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'commanded', xChannel: null }],
  });
  const { bla, actions, enqueue } = await makeBridgeStore({ design, channelCount: 2 });
  await bla.start({ seed: 55 });

  expect(get(bla.state).phase).toBe('done');
  const [op, payload] = enqueue.mock.calls[0] as [string, Record<string, unknown>];
  expect(op).toBe('calc_bla');
  expect(payload.run_spec).toEqual({
    multisine: {
      n_samples: 480, k1: 10, k2: 50, p_periods: 2, t_periods: 1,
      seed: 55, amp_rms: 0.05, n_exc: 1, M: 2,
    },
    x_mode: 'commanded',
    // No measured drive, so nothing is subtracted: every captured channel is a
    // response, and the engine regenerates X analytically from the seed.
    x_channels: null,
    resp_channels: [0, 1],
    fs: FS,
  });
  const [, opts] = actions.blaCalls[0] as [unknown[], { names: string[]; channelLabels: string[] }];
  expect(opts.names).toEqual(['run BLA q1 (commanded)']);
  expect(opts.channelLabels).toEqual(['ch_0', 'ch_1']);
});

test('a preflight failure refuses the run without touching the device', async () => {
  const { bla, acquire, provider } = makeStore();
  acquire.patch({ lpfOn: true });
  await bla.start({ seed: 11 });
  expect(provider.configs).toHaveLength(0);
  expect(get(bla.state).phase).toBe('error');
  expect(get(bla.state).error).toMatch(/digital low-pass/);
  expect(get(acquire.settings).durationS).toBe(3.5);
});

test('a device running at another rate aborts the run with a clear message', async () => {
  const { bla, acquire } = makeStore({ provider: fakeProvider({ fs: 44100 }) });
  await bla.start({ seed: 12 });
  const st = get(bla.state);
  expect(st.phase).toBe('error');
  expect(st.error).toMatch(/captured at 44100 Hz but the run was designed for 48000 Hz/);
  // BROWSER path: there is no coerced-fs channel, so `fsEff` will report the
  // requested rate forever — "start the run again" would loop. The advice has
  // to be to move the requested rate onto what the browser opened.
  expect(st.error).toMatch(/set the sample rate to 44100 Hz in Setup/);
  expect(st.error).not.toMatch(/start the run again/);
  expect(get(acquire.settings).durationS).toBe(3.5);   // restored even on failure
});

test('on the bridge the same abort says to start again (the coerced rate self-heals)', async () => {
  const provider = fakeProvider({ kind: 'bridge', caps: niCaps(), fs: 44100 });
  const s = makeStore({ provider });
  await s.acquire.init();
  s.acquire.patch({ deviceId: 'nidaq:0' });
  await s.bla.start({ seed: 12 });
  const st = get(s.bla.state);
  expect(st.phase).toBe('error');
  expect(st.error).toMatch(/start the run again/);
  expect(st.error).not.toMatch(/set the sample rate/);
});

test('a refused preflight keeps the previous run\'s set ids (and its show-raw affordance)', async () => {
  const { bla, acquire, selection } = makeStore();
  await bla.start({ seed: 31 });
  const ids = get(bla.state).rawSetIds;
  const resultIds = get(bla.state).resultSetIds;
  expect(ids).toHaveLength(2);
  expect(resultIds).toHaveLength(1);

  // A NEW run that never starts must not strand the previous captures: they
  // are still hidden in the tray, and the card gates "show raw captures" on
  // exactly these ids.
  acquire.patch({ lpfOn: true });
  await bla.start({ seed: 32 });
  const st = get(bla.state);
  expect(st.phase).toBe('error');
  expect(st.error).toMatch(/digital low-pass/);
  expect(st.rawSetIds).toEqual(ids);
  expect(st.resultSetIds).toEqual(resultIds);
  // And the toggle still reaches them.
  bla.setRawVisible(true);
  const offFor = (id: number) => get(selection.setsView).find((s) => s.id === id)?.allOff;
  expect(ids.map(offFor)).toEqual([false, false]);
});

test('reset() unhides the raw captures before forgetting them', async () => {
  const { bla, selection } = makeStore();
  await bla.start({ seed: 33 });
  const ids = get(bla.state).rawSetIds;
  const offFor = (id: number) => get(selection.setsView).find((s) => s.id === id)?.allOff;
  expect(ids.map(offFor)).toEqual([true, true]);       // hidden by the run

  bla.reset();
  // The store no longer tracks them, so the card's toggle is gone — leaving
  // them hidden would put sets in the tray this card can never reveal again.
  expect(get(bla.state)).toEqual({
    phase: 'idle', m: 0, e: 0, error: '', runSpec: null,
    rawSetIds: [], resultSetIds: [], notes: [],
  });
  expect(ids.map(offFor)).toEqual([false, false]);
});

test('an engine failure surfaces on the store, not as a rejection', async () => {
  const { bla, acquire, enqueue } = makeStore();
  enqueue.mockRejectedValue(new Error('BLA input matrix is singular'));
  await expect(bla.start({ seed: 13 })).resolves.toBeUndefined();
  expect(get(bla.state).phase).toBe('error');
  expect(get(bla.state).error).toMatch(/singular/);
  expect(get(bla.state).rawSetIds).toHaveLength(2);    // the captures still landed
  expect(get(acquire.settings).durationS).toBe(3.5);   // duration restored
});

test('the live checks store skips the peak guard but still reports hard failures', () => {
  const { bla, acquire } = makeStore();
  expect(get(bla.checks)).toEqual([]);
  bla.patch({ ampRms: 10 });                       // would fail the peak guard
  expect(get(bla.checks)).toEqual([]);             // …but not in the live check
  acquire.patch({ lpfOn: true });
  expect(firstBlaError(get(bla.checks))).toMatch(/digital low-pass/);
});
