// selectEngine.test.ts — the engine-host POLICY, tested as a pure function.
//
// Stage 1 (Task 8) is opt-in: only an explicit `?enginehost=` asks for the
// native host. Task 10 extends `parseEngineParam`'s caller with
// served-by-pydvma-serve auto-detection; the param's own meaning must not
// drift when it does, which is what these pin.
import { describe, expect, test, vi } from 'vitest';

// resolveEngineClient's served-probe wiring pulls in two modules this file
// mocks so the test can run in node (no `window`, no real WebSocket/Worker):
//  - `audio/provider.ts`'s `probeServeConfig` (the /config served-ness
//    signature probe itself — stubbed rather than faking a fetch response;
//    NOT `fetchServeConfig`, a different function with different
//    empty-object semantics — see selectEngine.ts's resolveEngineClient
//    docstring for why that distinction is load-bearing here);
//  - `worker/socketClient.ts`'s `createSocketEngineClient` (so a "tries
//    native" assertion never has to construct a real WebSocket).
// vi.mock is hoisted above module init, so both fakes are built via
// vi.hoisted (the established pattern — see provider-webaudio.test.ts).
const { probeServeConfigMock } = vi.hoisted(() => ({
  probeServeConfigMock: vi.fn(),
}));
vi.mock('../../src/lib/audio/provider', () => ({
  probeServeConfig: probeServeConfigMock,
}));

const { createSocketEngineClientMock, fakeSocketClient } = vi.hoisted(() => {
  const client = {
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

describe('resolveEngineClient (served-probe wiring, off-window / no real transport)', () => {
  test('no explicit param + a served /config -> probes once, then tries native at the default same-origin URL', async () => {
    probeServeConfigMock.mockClear();
    probeServeConfigMock.mockResolvedValueOnce(true); // "served" signature, incl. an EMPTY {} config
    createSocketEngineClientMock.mockClear();
    fakeSocketClient.init.mockClear();

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
  // The "not served" fallback branch (`createEngineClient()`) is NOT unit
  // tested here: it eagerly constructs a real ES-module Worker
  // (`client.ts`'s `defaultWorkerFactory`), which node has no global for --
  // mocking `./client` too just to dodge that would contort this test past
  // the value it adds. That branch is already covered at the pure-function
  // level (`decideEnginePolicy(null, false)` above) and end-to-end by every
  // pre-existing e2e test that boots through plain vite (no `pydvma serve`).
});
