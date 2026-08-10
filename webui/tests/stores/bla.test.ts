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
import type { BridgeCaps, BridgeConfig, SourceProvider } from '../../src/lib/audio/provider';

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

/** A fake provider that returns a synthetic capture of the requested length. */
function fakeProvider(opts: { kind?: 'webaudio' | 'bridge'; fs?: number } = {}) {
  const configs: RecordConfig[] = [];
  const provider: SourceProvider & { configs: RecordConfig[]; bridgeConfig: BridgeConfig } = {
    kind: opts.kind ?? 'webaudio',
    configs,
    bridgeConfig: {},
    capabilities: async () => null,
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

test('commanded x is refused unless the caps prove an NI shared clock', () => {
  const design = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'commanded', xChannel: null }],
  });
  const values = deriveBla(design, FS, 2);
  const reason = (over: Partial<BlaPreflightInput>) =>
    preflightBla(baseInput({ design, values, ...over })).find((c) => c.code === 'commanded-sync');

  // Browser / soundcard: no sync possible.
  expect(reason({})?.ok).toBe(false);
  // Software-timed AO (USB-6003) — cannot share the AI clock.
  const sw = niCaps();
  sw.devices.nidaq[0].product_type = 'USB-6003';
  sw.device_caps!['nidaq:0'].product_type = 'USB-6003';
  expect(reason({ providerKind: 'bridge', caps: sw, inputDeviceId: 'nidaq:0' })?.ok).toBe(false);
  // Right hardware, but the AO rate is clamped away from fs.
  expect(reason({
    providerKind: 'bridge', caps: niCaps(), inputDeviceId: 'nidaq:0', stagedOutputFs: 5000,
  })?.ok).toBe(false);
  // Right hardware, matched rate ⇒ allowed.
  expect(reason({ providerKind: 'bridge', caps: niCaps(), inputDeviceId: 'nidaq:0' }))
    .toBeUndefined();
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

test('the NI output rail drives the peak limit; other paths use ±1', () => {
  const caps = niCaps();
  expect(outputRailFor('webaudio', null, {}, '')).toBe(1);
  expect(outputRailFor('bridge', caps, {}, 'nidaq:0')).toBe(10);            // device ao_vmax
  expect(outputRailFor('bridge', caps, { outputVmaxNI: 4.24 }, 'nidaq:0')).toBe(4.24);
  expect(outputRailFor('bridge', caps, {}, 'soundcard:0')).toBe(1);         // VmaxSC default
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

test('commanded runs send x_channels: null and name their sets accordingly', async () => {
  const design = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'commanded', xChannel: null }],
  });
  const { bla, actions, enqueue } = makeStore({ design, channelCount: 2 });
  // Commanded x is refused on the browser path, so this run must not start.
  await bla.start({ seed: 2 });
  expect(get(bla.state).phase).toBe('error');
  expect(get(bla.state).error).toMatch(/hardware-synced NI output/);
  expect(enqueue).not.toHaveBeenCalled();
  expect(actions.blaCalls).toHaveLength(0);
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
  expect(get(acquire.settings).durationS).toBe(3.5);   // restored even on failure
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
