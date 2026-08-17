import { expect, test } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Native-engine e2e (Task 9): the `EngineProbe` self-test driven through the
 * `SocketEngineClient` against a REAL spawned `pydvma serve` (mock driver) —
 * the socket-transport counterpart of `engine.spec.ts`'s in-worker pyodide
 * round-trip. Pattern copied from `bridge.spec.ts` (spawn/waitForPort/SIGINT
 * teardown) and `engine.spec.ts` (the `?engine=1` probe page + 'ready' wait).
 *
 * SKIPPED unless `BRIDGE_E2E` is set (needs pydvma + websockets). Run:
 *
 *     BRIDGE_E2E=1 npx playwright test e2e/engine-native.spec.ts --workers=1
 *
 * Two of the four tests are carry-overs from Task 3/8's review, both only
 * provable against a REAL socket (not the fake-transport unit tests):
 *
 *  - the `max_size=256*1024*1024` raise in `serve.py` exists so a request
 *    frame carrying a full capture doesn't get severed by the `websockets`
 *    default 1 MiB inbound cap — exercised here with a ~2M-sample calc_fft
 *    whose request frame is ≳10 MB (`__engineLargeTest`);
 *  - Stop must interrupt a call that is genuinely mid-compute on the SERVER
 *    (not just queued client-side) and the socket must then reconnect
 *    cleanly — the real-socket version of the unit-level teardown tests,
 *    exercising `engine_host.handle_connection`'s close-interrupts-the-op
 *    race end to end (`__engineStopTest`).
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
// See bridge.spec.ts: `python3` is the MS-Store stub on Windows.
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
const PORT = Number(process.env.ENGINE_PORT ?? 8764);
const ENGINE_URL = `ws://127.0.0.1:${PORT}/engine`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

let server: ChildProcessWithoutNullStreams | undefined;

/** Poll the loopback TCP port until the server accepts a connection. */
function waitForPort(port: number, timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() > deadline) reject(new Error(`engine port ${port} never opened`));
        else setTimeout(attempt, 200);
      });
    };
    attempt();
  });
}

test.beforeAll(async () => {
  if (!BRIDGE_E2E) return;
  server = spawn(PYTHON, ['-m', 'pydvma.serve', '--driver', 'mock', '--port', String(PORT)], {
    cwd: REPO_ROOT,
    stdio: 'pipe',
  });
  server.stdout.on('data', () => { /* drain */ });
  server.stderr.on('data', () => { /* drain */ });
  await waitForPort(PORT);
});

test.afterAll(async () => {
  if (!server) return;
  server.kill('SIGINT');
  await new Promise((r) => setTimeout(r, 300));
});

test.describe('native engine', () => {
  test.skip(!BRIDGE_E2E, 'set BRIDGE_E2E=1 (needs pydvma + websockets; spawns python3 -m pydvma.serve)');

  test('probe self-test runs calc_fft through the socket client', async ({ page }) => {
    await page.goto(`/?engine=1&enginehost=${encodeURIComponent(ENGINE_URL)}`);

    // Native init needs no pyodide boot — connect + greeting only, so this
    // should land in seconds, not the pyodide test's 200 s ceiling below.
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 30000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');

    const result = await page.evaluate(() => (window as any).__engineSelfTest());
    // Same real shape engine.spec.ts asserts for the pyodide path — the
    // wire protocol (frames.ts <-> engine_host.py) marshals identically.
    expect(result.freqAxisLen).toBeGreaterThan(0);
    expect(result.freqDataComplex).toBe(true);
    expect(result.freqDataLen).toBe(2 * result.freqAxisLen * result.nChannels);
    expect(result.freqDataShape).toEqual([result.freqAxisLen, result.nChannels]);
  });

  test('an unreachable enginehost falls back to pyodide silently', async ({ page }) => {
    // Real pyodide boot dominates this one (see engine.spec.ts) — give the
    // whole test, not just the status wait, matching headroom.
    test.setTimeout(240_000);

    // Port 1 refuses the connection immediately (no listener, and it's a
    // privileged port besides) — a fast, deterministic native-probe failure
    // rather than relying on the 5 s greeting-timeout path.
    await page.goto('/?engine=1&enginehost=ws://127.0.0.1:1/engine');

    // Falls through to a real pyodide boot — the long ceiling from
    // engine.spec.ts applies here too.
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 200_000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'pyodide');

    const result = await page.evaluate(() => (window as any).__engineSelfTest());
    expect(result.freqAxisLen).toBeGreaterThan(0);
    expect(result.freqDataComplex).toBe(true);
    expect(result.freqDataLen).toBe(2 * result.freqAxisLen * result.nChannels);
  });

  test('a ~30 MB request frame round-trips through the native engine', async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto(`/?engine=1&enginehost=${encodeURIComponent(ENGINE_URL)}`);
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 30000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');

    const result = await page.evaluate(() => (window as any).__engineLargeTest());
    expect(result.ok).toBe(true);
    // time_axis + time_data together, well past the old 1 MiB websockets
    // default and comfortably past the "≳10 MB" carry-over bar — this is
    // what the serve.py max_size=256*1024*1024 raise exists for.
    expect(result.nBytes).toBeGreaterThan(10 * 1024 * 1024);
    expect(result.freqAxisLen).toBeGreaterThan(0);
    expect(result.nOut).toBeGreaterThan(0);
  });

  test('Stop interrupts an in-flight native calc promptly and the socket reconnects', async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto(`/?engine=1&enginehost=${encodeURIComponent(ENGINE_URL)}`);
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 30000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');

    const result = await page.evaluate(() => (window as any).__engineStopTest());

    // Phase 1: the in-flight CWT sonogram actually rejected with the stop
    // error (not e.g. silently resolved with a stale/partial result).
    expect(result.calcStopped).toBe(true);
    expect(result.calcErrorName).toBe('EngineStopped');
    // Phase 1 latency: the calc was sized (bench: dev session) for several
    // seconds solo, and restart() rejects the pending call synchronously
    // client-side (dev measurement: sub-millisecond) rather than waiting on
    // the server's cancel/kill/respawn — 1 s is a generous ceiling that
    // still catches a regression to "wait for the server" (kill()'s own
    // proc.join has a 2 s cap).
    expect(result.calcSettledMs).toBeLessThan(1000);

    // Phase 2: the full stop() (server-side cancel+kill, fresh socket,
    // fresh greeting) completed at all, in a sane bound.
    expect(result.rebootMs).toBeLessThan(30_000);

    // Phase 3: a normal calc over the reconnected socket succeeds, and the
    // session is still on the native host (stop()/boot() keep the resolved
    // transport — see stores/engine.ts's handleTransportLost comment).
    expect(result.reconnectError).toBeNull();
    expect(result.reconnectOk).toBe(true);
    await expect(page.getByTestId('engine-status')).toHaveText('ready');
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');
  });
});
