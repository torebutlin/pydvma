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
  resolveBlaPeriod,
  roundForPeriodBox,
  blaRunBaseName,
  markBlaCapture,
  plannedCaptures,
  blaRemainingS,
  BLA_BRIDGE_PEAK_MARGIN,
  BLA_CAPTURE_MARGIN_SAMPLES,
  type BlaActions,
  type BlaCapture,
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
 * `removeBlaRun` is a spy over the real `selection.removeSet`, which is all
 * the store's replace path can observe of it.
 */
function fakeActions(selection: ReturnType<typeof createSelection>, nChannels: number) {
  const landed: string[] = [];
  const actions: BlaActions & {
    landed: string[];
    blaCalls: unknown[][];
    removed: number[][];
  } = {
    landed,
    blaCalls: [],
    removed: [],
    addRecordedSet: (item, o) => {
      const name = String(item.meta.test_name);
      landed.push(name);
      return selection.addSet(
        { name, nChannels, durationS: 0, timestamp: '' },
        { hidden: !!o?.hidden },
      );
    },
    addBlaSets: (results, o) => {
      actions.blaCalls.push([results, o]);
      const names = o?.names ?? [];
      return results.map((_, q) =>
        selection.addSet({
          name: names[q] ?? `bla${q}`, nChannels: 1, durationS: 0, timestamp: '',
        }));
    },
    removeBlaRun: (ids) => {
      actions.removed.push([...ids]);
      for (const id of ids) selection.removeSet(id);
      return ids.length;
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

// ---- the linked Δf <-> period pair (round-11 P6) ----

test('editing Δf resolves the period; editing the period resolves Δf', () => {
  // Δf is echoed back verbatim (the user's typed intent stays in its box),
  // and the period follows from the rounded sample count.
  expect(resolveBlaPeriod('df', 100, FS)).toEqual({ periodSamples: 480, dfHz: 100, periodS: 0.01 });
  // The other direction: a typed period is quantised to whole samples FIRST,
  // and BOTH readouts then come from that N.
  const t = resolveBlaPeriod('period', 0.01, FS);
  expect(t.periodSamples).toBe(480);
  expect(t.dfHz).toBeCloseTo(100, 12);
  expect(t.periodS).toBeCloseTo(0.01, 12);
});

test('a period that is not a whole number of samples rounds, and reports what it got', () => {
  // 0.0101 s at 48 kHz is 484.8 samples -> 485, so the achievable Δf is
  // fs/485, NOT 1/0.0101. The card shows both resolved numbers, so the user
  // sees the quantisation instead of discovering it in the result.
  const r = resolveBlaPeriod('period', 0.0101, FS);
  expect(r.periodSamples).toBe(485);
  expect(r.dfHz).toBeCloseTo(FS / 485, 12);
  expect(r.periodS).toBeCloseTo(485 / FS, 12);
});

test('the linked pair round-trips through the values the card DISPLAYS', () => {
  // The real risk in a two-box control: the displayed period is rounded for
  // legibility, so committing the box without editing it must not move N.
  for (const [fs, dfHz] of [[48000, 100], [44100, 7], [8000, 5], [96000, 0.5]] as const) {
    const forward = resolveBlaPeriod('df', dfHz, fs);
    const shown = roundForPeriodBox(forward.periodS);
    expect(resolveBlaPeriod('period', shown, fs).periodSamples).toBe(forward.periodSamples);
    // …and back again: the Δf the period box produces re-reads the same N.
    const back = roundForPeriodBox(resolveBlaPeriod('period', shown, fs).dfHz);
    expect(resolveBlaPeriod('df', back, fs).periodSamples).toBe(forward.periodSamples);
  }
});

test('a nonsensical period or Δf resolves to N = 0, never NaN or Infinity', () => {
  for (const bad of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
    expect(resolveBlaPeriod('df', bad, FS).periodSamples).toBe(0);
    const p = resolveBlaPeriod('period', bad, FS);
    expect(p).toEqual({ periodSamples: 0, dfHz: 0, periodS: 0 });
  }
  // No rate yet (nothing chosen in Setup) — same answer from either box.
  expect(resolveBlaPeriod('df', 5, 0).periodSamples).toBe(0);
  expect(resolveBlaPeriod('period', 0.2, 0).periodSamples).toBe(0);
  // A sub-sample period is not a period at all.
  expect(resolveBlaPeriod('period', 1e-9, FS).periodSamples).toBe(0);
});

test('setPeriod writes ONE design field from either box', () => {
  const { bla } = makeStore();
  bla.setPeriod('df', 200);
  expect(get(bla.design).dfHz).toBe(200);
  expect(get(bla.values).periodSamples).toBe(240);

  bla.setPeriod('period', 0.02);                      // 960 samples at 48 kHz
  expect(get(bla.values).periodSamples).toBe(960);
  expect(get(bla.design).dfHz).toBeCloseTo(50, 6);
  expect(get(bla.values).periodS).toBeCloseTo(0.02, 12);
});

// ---- run naming (keep-both) ----

test('a run takes the next free #n only when its name is already in the tray', () => {
  expect(blaRunBaseName('bla', [])).toBe('bla');
  expect(blaRunBaseName('bla', ['bla r1e1', 'bla BLA q1 (via ch0)'])).toBe('bla#2');
  expect(blaRunBaseName('bla', ['bla r1e1', 'bla#2 r1e1'])).toBe('bla#3');
  // Gaps do not get reused — the next run is always above the highest.
  expect(blaRunBaseName('bla', ['bla#5 r1e1'])).toBe('bla#6');
  // A CHANGED test name collides with nothing, so it is used verbatim: a
  // rename is the explicit way to say "this is a different run".
  expect(blaRunBaseName('sweep', ['bla r1e1', 'bla#2 r1e1'])).toBe('sweep');
  // Prefix, not substring: `bla` must not claim `blast`'s sets, and the base
  // has to be followed by a separator.
  expect(blaRunBaseName('bla', ['blast r1e1', 'blade BLA q1'])).toBe('bla');
  // Unrelated sets in the tray (a loaded file, a manual capture) are ignored.
  expect(blaRunBaseName('bla', ['guitar_string4', 'capture_1'])).toBe('bla');
});

// ---- the progress grid ----

test('plannedCaptures lays the run out in (m, e) order, all pending', () => {
  const cells = plannedCaptures(3, 2);
  expect(cells).toHaveLength(6);
  expect(cells.map((c) => [c.m, c.e])).toEqual([[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]);
  expect(cells.every((c) => c.status === 'pending')).toBe(true);
  expect(plannedCaptures(0, 2)).toEqual([]);
});

test('markBlaCapture touches exactly one cell and returns a new array', () => {
  const cells = plannedCaptures(2, 2);
  const next = markBlaCapture(cells, 1, 0, 'running');
  expect(next).not.toBe(cells);
  expect(cells.every((c) => c.status === 'pending')).toBe(true);      // input untouched
  expect(next.filter((c) => c.status === 'running')).toEqual([{ m: 1, e: 0, status: 'running' }]);
});

test('the remaining-time estimate counts whole captures plus the one in flight', () => {
  const cells: BlaCapture[] = [
    { m: 0, e: 0, status: 'done' },
    { m: 1, e: 0, status: 'running' },
    { m: 2, e: 0, status: 'pending' },
  ];
  // 2 captures left of 1 s each, 0.4 s already spent on the running one.
  expect(blaRemainingS(cells, 1, 0.4)).toBeCloseTo(1.6, 12);
  // An overrunning capture floors at the two remaining, never goes negative.
  expect(blaRemainingS(cells, 1, 5)).toBeCloseTo(1, 12);
  // Nothing in flight (between captures) ⇒ no partial credit.
  expect(blaRemainingS(cells.map((c) => (c.status === 'running' ? { ...c, status: 'pending' as const } : c)), 1, 9))
    .toBeCloseTo(2, 12);
  expect(blaRemainingS([], 1, 0)).toBe(0);
  expect(blaRemainingS(cells, 0, 0)).toBe(0);          // no design yet
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

test('commanded x is refused on EVERY path until start sync is proven', () => {
  // A routed AI sample clock locks the RATE but not the START: the
  // 2026-08-11 hardware run (dev/bridge_hw_check.py check G) measured a
  // random per-capture AO start offset on the routed-clock 6212 — the BLA
  // mean collapses by 1/sqrt(M). So even the once-admissible path is
  // refused (BLA_COMMANDED_X_START_SYNC_PROVEN = false) until the
  // acquisition path gains an AO/AI shared start trigger.
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
  // cDAQ chassis: phase-coherent through the chassis timebase, never
  // sample-accurate.
  expect(bridged({ caps: chassisCaps() })?.ok).toBe(false);
  // Unknown hardware (no product_type reported) cannot PROVE sync.
  const bare = niCaps();
  bare.devices.nidaq[0].product_type = '';
  delete bare.device_caps!['nidaq:0'].product_type;
  expect(bridged({ caps: bare })?.ok).toBe(false);
  // M-series, same device, matched rate — the formerly-allowed path — is
  // now refused too, with the measured-drive guidance.
  expect(bridged({ caps: niCaps() })?.ok).toBe(false);
  expect(bridged({ caps: niCaps() })?.reason).toMatch(/Measure the drive/);
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

test('the capture grid fills pending → running → done, one cell in flight', async () => {
  const { bla } = makeStore({ design: misoDesign({ M: 2 }), channelCount: 3 });
  /** Grid snapshots, one per emit, as compact status strings. */
  const seen: string[] = [];
  const unsub = bla.state.subscribe((s) => {
    if (!s.captures.length) return;
    const txt = s.captures.map((c) => c.status[0]).join('');
    if (seen[seen.length - 1] !== txt) seen.push(txt);
    // INVARIANT, checked on every single emit: the loop is sequential, so at
    // most one capture can ever be in flight.
    expect(s.captures.filter((c) => c.status === 'running').length).toBeLessThanOrEqual(1);
  });
  await bla.start({ seed: 41 });
  unsub();

  // p = pending, r = running, d = done — the grid marches through (m, e).
  expect(seen).toEqual([
    'pppp', 'rppp', 'dppp', 'drpp', 'ddpp', 'ddrp', 'dddp', 'dddr', 'dddd',
  ]);
  expect(get(bla.state).captures).toHaveLength(4);
});

test('the grid is planned in full at Start, so the run length is known up front', async () => {
  const { bla } = makeStore({ design: misoDesign({ M: 3 }), channelCount: 3 });
  let firstGrid: string | null = null;
  const unsub = bla.state.subscribe((s) => {
    if (firstGrid === null && s.captures.length) firstGrid = s.captures.map((c) => c.status[0]).join('');
  });
  await bla.start({ seed: 42 });
  unsub();
  expect(firstGrid).toBe('pppppp');               // 3 × 2, every cell pending
  expect(get(bla.state).runStartedAt).toBeGreaterThan(0);
});

test('cancelling keeps the done cells and leaves nothing stuck mid-fill', async () => {
  const { bla } = makeStore({ design: misoDesign({ M: 3 }), channelCount: 3 });
  const unsub = bla.state.subscribe((s) => {
    if (s.phase === 'running' && s.rawSetIds.length === 2) bla.cancel();
  });
  await bla.start({ seed: 43 });
  unsub();
  const st = get(bla.state);
  expect(st.phase).toBe('cancelled');
  expect(st.captures.map((c) => c.status))
    .toEqual(['done', 'done', 'pending', 'pending', 'pending', 'pending']);
  expect(st.captures.some((c) => c.status === 'running')).toBe(false);
});

test('a failed capture releases its cell rather than leaving it running forever', async () => {
  const provider = fakeProvider();
  const inner = provider.startRecording.bind(provider);
  provider.startRecording = (cfg) => ({
    ...inner(cfg),
    promise: Promise.reject(new Error('device went away')),
  });
  const { bla } = makeStore({ provider });
  await bla.start({ seed: 44 });
  const st = get(bla.state);
  expect(st.phase).toBe('error');
  expect(st.captures.every((c) => c.status === 'pending')).toBe(true);
});

// ---- run semantics: replace vs keep both (round-11 P6) ----

test('a second run REPLACES the first by default, naming itself the same', async () => {
  const { bla, actions, selection } = makeStore();
  await bla.start({ seed: 51 });
  const first = [...get(bla.state).rawSetIds, ...get(bla.state).resultSetIds];
  expect(first).toHaveLength(3);                   // 2 captures + 1 BLA set
  expect(get(bla.hasPreviousRun)).toBe(true);

  await bla.start({ seed: 52 });
  // Exactly the previous run's ids went to removeBlaRun — nothing else in the
  // tray is the BLA stage's to delete.
  expect(actions.removed).toEqual([first]);
  expect(get(selection.sets).map((s) => s.id)).not.toEqual(expect.arrayContaining(first));
  // …and with the old sets gone, the new run keeps the plain test name.
  expect(actions.landed.slice(2)).toEqual(['run r1e1', 'run r2e1']);
});

test('keep-both leaves the first run alone and suffixes the second', async () => {
  const { bla, actions, selection } = makeStore();
  await bla.start({ seed: 53 });
  const first = [...get(bla.state).rawSetIds, ...get(bla.state).resultSetIds];

  bla.runMode.set('keep');
  await bla.start({ seed: 54 });
  expect(actions.removed).toEqual([]);                       // nothing removed
  const ids = get(selection.sets).map((s) => s.id);
  expect(ids).toEqual(expect.arrayContaining(first));        // the first run survives
  // The second run's sets are named apart, raw captures AND results, so the
  // two runs are distinguishable in the tray and the legend.
  expect(actions.landed).toEqual(['run r1e1', 'run r2e1', 'run#2 r1e1', 'run#2 r2e1']);
  const [, opts] = actions.blaCalls[1] as [unknown[], { names: string[] }];
  expect(opts.names).toEqual(['run#2 BLA q1 (via ch0)']);
  // A THIRD run climbs again rather than colliding with either.
  await bla.start({ seed: 55 });
  expect(actions.landed.slice(4)).toEqual(['run#3 r1e1', 'run#3 r2e1']);
});

test('hasPreviousRun follows the TRAY, so hand-deleted sets stop offering a replace', async () => {
  const { bla, selection } = makeStore();
  expect(get(bla.hasPreviousRun)).toBe(false);          // nothing run yet
  await bla.start({ seed: 56 });
  expect(get(bla.hasPreviousRun)).toBe(true);
  for (const id of [...get(bla.state).rawSetIds, ...get(bla.state).resultSetIds]) {
    selection.removeSet(id);
  }
  expect(get(bla.hasPreviousRun)).toBe(false);
});

test('a re-run after a CANCEL replaces the partial run it is retrying', async () => {
  const { bla, actions } = makeStore({ design: misoDesign({ M: 3 }), channelCount: 3 });
  const unsub = bla.state.subscribe((s) => {
    if (s.phase === 'running' && s.rawSetIds.length === 2) bla.cancel();
  });
  await bla.start({ seed: 57 });
  unsub();
  const partial = get(bla.state).rawSetIds;
  expect(partial).toHaveLength(2);
  expect(get(bla.state).phase).toBe('cancelled');

  // Retrying the same design is the common case after a cancel, and the two
  // partial captures are of no use — replace is exactly right here.
  await bla.start({ seed: 58 });
  expect(actions.removed).toEqual([partial]);
  expect(get(bla.state).phase).toBe('done');
  expect(get(bla.state).captures.every((c) => c.status === 'done')).toBe(true);
  expect(actions.landed.slice(2)).toEqual([
    'run r1e1', 'run r1e2', 'run r2e1', 'run r2e2', 'run r3e1', 'run r3e2',
  ]);
});

test('a store built without removeBlaRun never replaces (it keeps both instead)', async () => {
  // The dependency is optional so a caller can wire the store without the
  // actions helper; the fallback has to be the SAFE one — keep the data.
  const provider = fakeProvider();
  const acquire = createAcquireStore(provider);
  acquire.patch({ sampleRate: FS, channelCount: 2, durationS: 3.5 });
  const selection = createSelection();
  const full = fakeActions(selection, 2);
  const { removeBlaRun: _drop, ...thin } = full;
  const { engine } = fakeEngine(blaResult());
  const bla = createBlaStore({ acquire, actions: thin as BlaActions, engine, selection });
  bla.design.set(testDesign());

  await bla.start({ seed: 59 });
  await bla.start({ seed: 60 });
  expect(full.landed).toEqual(['run r1e1', 'run r2e1', 'run#2 r1e1', 'run#2 r2e1']);
  expect(get(selection.sets)).toHaveLength(6);       // nothing was deleted
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
  // Round-11 P6: a BLA set's columns are the RESPONSE channels, a subset of
  // the capture's — a bare `ch_1` on the second column would read as input
  // channel 1 when it is channel 2, so the label names the role AND the
  // source channel.
  expect(opts.channelLabels).toEqual(['resp ch 2']);
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
  expect(get(bla.state).error).toMatch(/Commanded drive is disabled/);
  expect(provider.configs).toHaveLength(0);
  expect(enqueue).not.toHaveBeenCalled();
  expect(actions.blaCalls).toHaveLength(0);
});

test('a commanded run is refused even on the routed-clock bridge path', async () => {
  // Before 2026-08-11 this test asserted the full commanded wire format
  // (x_mode 'commanded', x_channels null, every input a response — see git
  // history) — reinstate that when BLA_COMMANDED_X_START_SYNC_PROVEN can be
  // flipped back. Until then the run must refuse before touching the device.
  const design = testDesign({
    outputs: [{ aoChannel: 0, enabled: true, xMode: 'commanded', xChannel: null }],
  });
  const { bla, actions, enqueue, provider } = await makeBridgeStore({ design, channelCount: 2 });
  await bla.start({ seed: 55 });

  expect(get(bla.state).phase).toBe('error');
  expect(get(bla.state).error).toMatch(/Commanded drive is disabled/);
  expect(enqueue).not.toHaveBeenCalled();
  expect(actions.blaCalls).toHaveLength(0);
  expect(provider.configs).toHaveLength(0);            // no capture ever started
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
    phase: 'idle', m: 0, e: 0, captures: [], runStartedAt: 0, error: '', runSpec: null,
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
