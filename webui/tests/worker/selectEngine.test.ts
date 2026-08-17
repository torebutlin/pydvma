// selectEngine.test.ts — the engine-host POLICY, tested as a pure function.
//
// Stage 1 (Task 8) is opt-in: only an explicit `?enginehost=` asks for the
// native host. Task 10 extends `parseEngineParam`'s caller with
// served-by-pydvma-serve auto-detection; the param's own meaning must not
// drift when it does, which is what these pin.
import { describe, expect, test, vi } from 'vitest';

// resolveEngineClient's served-probe wiring pulls in three modules this file
// mocks so the test can run in node (no `window`, no real WebSocket/Worker):
//  - `audio/provider.ts`'s `probeServeConfig` (the /config served-ness
//    signature probe itself — stubbed rather than faking a fetch response;
//    NOT `fetchServeConfig`, a different function with different
//    empty-object semantics — see selectEngine.ts's resolveEngineClient
//    docstring for why that distinction is load-bearing here);
//  - `worker/socketClient.ts`'s `createSocketEngineClient` (so a "tries
//    native" assertion never has to construct a real WebSocket);
//  - `worker/client.ts`'s `createEngineClient` (the pyodide FALLBACK path —
//    needed only by the tests below that drive a native FAILURE through to
//    completion; its real implementation eagerly constructs a Worker, which
//    node has no global for).
// vi.mock is hoisted above module init, so all three fakes are built via
// vi.hoisted (the established pattern — see provider-webaudio.test.ts).
const { probeServeConfigMock } = vi.hoisted(() => ({
  probeServeConfigMock: vi.fn(),
}));
vi.mock('../../src/lib/audio/provider', () => ({
  probeServeConfig: probeServeConfigMock,
}));

const { createSocketEngineClientMock, fakeSocketClient } = vi.hoisted(() => {
  const client = {
    // Present because SocketEngineClient declares it (see socketClient.ts) --
    // resolveEngineClient's tryNative reads it straight off the client after
    // init() resolves. null by default, same as a freshly-constructed real
    // client before its first greeting.
    pydvmaVersion: null as string | null,
    init: vi.fn().mockResolvedValue(undefined),
    call: vi.fn(),
    observe: vi.fn(),
    restart: vi.fn(),
    dispose: vi.fn(),
  };
  return { fakeSocketClient: client, createSocketEngineClientMock: vi.fn(() => client) };
});
vi.mock('../../src/lib/worker/socketClient', () => ({
  createSocketEngineClient: createSocketEngineClientMock,
}));

const { createEngineClientMock } = vi.hoisted(() => {
  const client = { init: vi.fn(), call: vi.fn(), observe: vi.fn(), restart: vi.fn(), dispose: vi.fn() };
  return { createEngineClientMock: vi.fn(() => client) };
});
vi.mock('../../src/lib/worker/client', () => ({
  createEngineClient: createEngineClientMock,
}));

import { decideEnginePolicy, parseEngineParam, resolveEngineClient } from '../../src/lib/worker/selectEngine';

describe('parseEngineParam (stage-1 opt-in policy)', () => {
  test('no param expresses no preference at all', () => {
    // null (not {kind:'pyodide'}) — Task 10 needs "unstated" to be
    // distinguishable from "explicitly asked for the browser engine".
    expect(parseEngineParam(null)).toBeNull();
    expect(parseEngineParam('')).toBeNull();
  });

  test('pyodide forces the browser worker', () => {
    expect(parseEngineParam('pyodide')).toEqual({ kind: 'pyodide' });
  });

  test('native means the same-origin /engine endpoint', () => {
    expect(parseEngineParam('native')).toEqual({ kind: 'native', url: 'same-origin' });
  });

  test('any other value is an explicit ws URL (the e2e cross-origin form)', () => {
    expect(parseEngineParam('ws://127.0.0.1:8764/engine'))
      .toEqual({ kind: 'native', url: 'ws://127.0.0.1:8764/engine' });
    expect(parseEngineParam('wss://host:9/engine'))
      .toEqual({ kind: 'native', url: 'wss://host:9/engine' });
  });
});

describe('decideEnginePolicy (stage-2: served-by-pydvma-serve default)', () => {
  test('explicit param wins in both directions, regardless of served-ness', () => {
    // pyodide explicitly requested even though served -- an explicit opt-out
    // must always win over auto-detection.
    expect(decideEnginePolicy('pyodide', true)).toEqual({ kind: 'pyodide' });
    // native explicitly requested even though NOT served (e.g. the e2e's
    // cross-origin vite-served-page-pointed-at-a-spawned-serve form).
    expect(decideEnginePolicy('native', false)).toEqual({ kind: 'native', url: 'same-origin' });
    expect(decideEnginePolicy('ws://127.0.0.1:8764/engine', false))
      .toEqual({ kind: 'native', url: 'ws://127.0.0.1:8764/engine' });
    expect(decideEnginePolicy('ws://127.0.0.1:8764/engine', true))
      .toEqual({ kind: 'native', url: 'ws://127.0.0.1:8764/engine' });
  });

  test('no param + served by pydvma-serve -> native at same-origin', () => {
    expect(decideEnginePolicy(null, true)).toEqual({ kind: 'native', url: 'same-origin' });
    expect(decideEnginePolicy('', true)).toEqual({ kind: 'native', url: 'same-origin' });
  });

  test('no param + not served (Pages / vite dev) -> pyodide', () => {
    expect(decideEnginePolicy(null, false)).toEqual({ kind: 'pyodide' });
    expect(decideEnginePolicy('', false)).toEqual({ kind: 'pyodide' });
  });
});

/** Reset the shared socketClient/probeServeConfig fakes to a clean slate. */
function resetFakes(): void {
  probeServeConfigMock.mockReset();
  probeServeConfigMock.mockResolvedValue(true); // default: "served"
  createSocketEngineClientMock.mockClear();
  fakeSocketClient.init.mockReset();
  fakeSocketClient.init.mockResolvedValue(undefined); // default: connects fine
  fakeSocketClient.pydvmaVersion = null;
}

describe('resolveEngineClient (served-probe wiring, off-window / no real transport)', () => {
  test('no explicit param + a served /config -> probes once, then tries native at the default same-origin URL', async () => {
    resetFakes();

    const resolved = await resolveEngineClient();

    // engineHostParam() reads window.location.search, which is undefined
    // off-window -> no explicit preference -> the probe actually runs.
    expect(probeServeConfigMock).toHaveBeenCalledTimes(1);
    // defaultEngineWsUrl()'s off-window fallback -- the same one
    // socketClient's own tests connect to.
    expect(createSocketEngineClientMock).toHaveBeenCalledWith('ws://127.0.0.1:8760/engine');
    expect(fakeSocketClient.init).toHaveBeenCalledTimes(1);
    expect(resolved).toEqual({ client: fakeSocketClient, host: 'native' });
  });

  test('the greeted client.pydvmaVersion is carried into the resolved ResolvedEngine', async () => {
    resetFakes();
    fakeSocketClient.pydvmaVersion = '2.3.0';

    const resolved = await resolveEngineClient();

    expect(resolved.host).toBe('native');
    expect(resolved.pydvmaVersion).toBe('2.3.0');
  });

  // ---- note: only for the auto-detected-native-then-failed case (item 2),
  // and probeServeConfig is skipped entirely for an explicit param (item 4b)
  // -- both need a REAL `window` so `engineHostParam()` actually reads a
  // `?enginehost=` value; `vi.stubGlobal` supplies just enough of it
  // (`location.search`) without pulling in jsdom. ----

  test('no param + served, but native init() fails -> note IS set (a silent capability downgrade)', async () => {
    resetFakes();
    fakeSocketClient.init.mockRejectedValueOnce(new Error('native engine connect failed'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.stubGlobal('window', { location: { search: '' } }); // states no preference

    try {
      const resolved = await resolveEngineClient();
      expect(probeServeConfigMock).toHaveBeenCalledTimes(1); // param null -> probe ran
      expect(resolved.host).toBe('pyodide');
      expect(resolved.note).toMatch(/native engine unavailable/);
    } finally {
      vi.unstubAllGlobals();
      warn.mockRestore();
    }
  });

  test('explicit ?enginehost=native that fails -> note is undefined AND probeServeConfig is never called', async () => {
    resetFakes();
    fakeSocketClient.init.mockRejectedValueOnce(new Error('native engine connect failed'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.stubGlobal('window', {
      location: { search: '?enginehost=' + encodeURIComponent('ws://127.0.0.1:8764/engine') },
    });

    try {
      const resolved = await resolveEngineClient();
      expect(resolved.host).toBe('pyodide');
      expect(resolved.note).toBeUndefined(); // the user asked for this host; console-only
      // item 4b: an explicit param short-circuits BEFORE `served` is ever
      // consulted -- probeServeConfig must not have been called at all.
      expect(probeServeConfigMock).not.toHaveBeenCalled();
      expect(warn).toHaveBeenCalled(); // still diagnosable from the console
    } finally {
      vi.unstubAllGlobals();
      warn.mockRestore();
    }
  });

  test('explicit ?enginehost=pyodide -> resolves pyodide directly, probeServeConfig never called', async () => {
    resetFakes();
    vi.stubGlobal('window', { location: { search: '?enginehost=pyodide' } });
    try {
      const resolved = await resolveEngineClient();
      expect(resolved.host).toBe('pyodide');
      expect(probeServeConfigMock).not.toHaveBeenCalled();
      expect(createSocketEngineClientMock).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
