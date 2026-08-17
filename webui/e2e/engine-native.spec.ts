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
 *    cleanly. This drives the close-mid-op race end to end from the
 *    CLIENT's side (prompt settle, then a working reconnect); the
 *    server-side half — close actually kills the worker's child process
 *    promptly, not after the op's full duration — is asserted at the unit
 *    level in `tests/test_engine_host.py::
 *    test_engine_endpoint_close_mid_op_kills_worker_promptly`, not
 *    re-measured here (`__engineStopTest`).
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
// See bridge.spec.ts: `python3` is the MS-Store stub on Windows.
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
// Port claimants across every BRIDGE_E2E-gated spec that spawns its own
// `pydvma serve` (each needs a DISJOINT default — a combined run without
// --workers=1 starts every file's beforeAll concurrently):
//   8763  bridge.spec.ts        (main describe, BRIDGE_PORT)
//   8764  bridge.spec.ts        (--settings describe, BRIDGE_SETTINGS_PORT)
//   8765  bla.spec.ts           (bridge-run describe, BLA_BRIDGE_PORT)
//   8766  engine-native.spec.ts (this file, ENGINE_PORT)
// A collision is NASTIER than a bind error here: a mock `pydvma serve`
// answers both /ws and /engine, so the loser's tests can silently run
// against the winner's server instead of failing to start.
const PORT = Number(process.env.ENGINE_PORT ?? 8766);
const ENGINE_URL = `ws://127.0.0.1:${PORT}/engine`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

let server: ChildProcessWithoutNullStreams | undefined;

// Buffered (not drained-to-nothing) spawned-server output: the last
// MAX_OUTPUT_LINES lines of stdout+stderr combined, so a failure to start
// (wrong PYDVMA_PYTHON, no `websockets` installed, EADDRINUSE from a port
// collision — see the PORT comment above) is SELF-REPORTING in the
// waitForPort rejection instead of a bare "never opened" with the actual
// cause sitting silently in a stream nobody read. This is also what a
// Windows run needs: the MS-Store `python3` stub and a missing `websockets`
// extra both fail silently today, printing their reason only to a stream
// bridge.spec.ts (and, until now, this file) discarded.
const MAX_OUTPUT_LINES = 50;
const serverOutputLines: string[] = [];

function ingestServerOutput(chunk: Buffer | string): void {
  for (const line of chunk.toString().split('\n')) {
    if (!line) continue;
    serverOutputLines.push(line);
    if (serverOutputLines.length > MAX_OUTPUT_LINES) serverOutputLines.shift();
  }
}

/** Poll the loopback TCP port until the server accepts a connection. */
function waitForPort(port: number, timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() > deadline) {
          const tail = serverOutputLines.length
            ? serverOutputLines.join('\n')
            : '(no server output captured)';
          reject(new Error(`engine port ${port} never opened. serve output:\n${tail}`));
        } else {
          setTimeout(attempt, 200);
        }
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
  server.stdout.on('data', ingestServerOutput);
  server.stderr.on('data', ingestServerOutput);
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

    // Port 1 is on Chromium's restricted-ports list (net::ERR_UNSAFE_PORT):
    // the browser's network stack refuses the connection attempt outright,
    // so it never even reaches TCP (this is NOT an OS "privileged port"
    // thing — connecting out to a low port needs no special privilege;
    // only binding/listening on one does). That makes this a fast,
    // deterministic native-probe failure rather than relying on the 5 s
    // greeting-timeout path a real closed/filtered port would hit instead.
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
    // Generous: this waits on a cold worker-subprocess spawn + numpy/scipy/
    // pydvma import (the hook now warms it first, but a slow machine — esp.
    // Windows — still wants headroom) plus the ~30 MB transfer itself.
    test.setTimeout(120_000);
    await page.goto(`/?engine=1&enginehost=${encodeURIComponent(ENGINE_URL)}`);
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 30000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');

    const result = await page.evaluate(() => (window as any).__engineLargeTest());
    expect(result.ok).toBe(true);
    // nBytes is the FIXTURE's raw array size (time_axis + time_data), not a
    // measurement of anything on the wire — it just pins that this fixture
    // is actually big enough to exercise the "≳10 MB" carry-over bar (well
    // past the old 1 MiB websockets default, safely inside the serve.py
    // max_size=256*1024*1024 raise the round-trip depends on).
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

    // Phase 2: stop() itself (closing the old socket, opening a fresh one,
    // waiting for its greeting) completed at all, in a sane bound. This is
    // the CLIENT's reconnect timing, not a measurement of the server's own
    // cancel/kill of the old connection's worker — that proceeds
    // independently and is asserted separately (see the comment above).
    expect(result.rebootMs).toBeLessThan(30_000);

    // Phase 3: a normal calc over the reconnected socket succeeds, and the
    // session is still on the native host (stop()/boot() keep the resolved
    // transport — see stores/engine.ts's handleTransportLost comment).
    expect(result.reconnectError).toBeNull();
    expect(result.reconnectOk).toBe(true);
    await expect(page.getByTestId('engine-status')).toHaveText('ready');
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');

    // Cheap server-side corroboration, now that stderr is buffered instead
    // of drained to nothing: a clean close-mid-op must not log a
    // `websockets` "connection handler failed" traceback — the phrase it
    // emits specifically when our OWN `handle_connection` coroutine leaks an
    // unhandled exception (asyncio/server.py's `connection.logger.error
    // ("connection handler failed", ...)`; see engine_host.py's docstring,
    // which already names this exact string). Deliberately NOT a bare
    // "Traceback" match: `waitForPort`'s raw TCP probe above (connect, then
    // destroy() before any HTTP bytes go out — the same idiom bridge.spec.ts
    // and bla.spec.ts use) reliably makes `websockets` log an UNRELATED,
    // harmless "opening handshake failed" traceback of its own once per
    // spawned server; a bare "Traceback" match flags that every time and
    // says nothing about the close-mid-op path this test actually cares
    // about. This check does NOT re-prove the kill itself completes
    // promptly — that bound is the unit test's job (see the comment above).
    const serverIssues = serverOutputLines.filter((l) => l.includes('connection handler failed'));
    expect(serverIssues, `unexpected serve-side error output:\n${serverIssues.join('\n')}`).toEqual([]);
  });

  // ---- Task 10: the default flip -- served by pydvma-serve means native,
  // with no `?enginehost=` param at all ----

  test('served by pydvma-serve → native engine by default (no param)', async ({ page }) => {
    // Deliberately an ABSOLUTE goto to the spawned serve's own origin, NOT
    // `page.goto('/?engine=1')` (which would hit Playwright's `baseURL` --
    // the vite dev/preview server). `resolveEngineClient`'s served-detection
    // is a same-origin `/config` probe: the page has to actually be SERVED
    // BY `pydvma serve` (this spawned mock-driver instance, serving its own
    // vendored `webui/dist`) for that probe to see the serve signature and
    // default to native. A vite-served page pointed at this same backend
    // would probe vite's own (nonexistent) `/config` and get null -> pyodide,
    // which is exactly the "not served" case Task 10 must NOT trip here.
    await page.goto(`http://127.0.0.1:${PORT}/?engine=1`);
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 30000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'native');

    const result = await page.evaluate(() => (window as any).__engineSelfTest());
    expect(result.freqDataComplex).toBe(true);
  });

  test('?enginehost=pyodide forces the browser engine even when served', async ({ page }) => {
    // Same served origin as the default-flip test above, but the explicit
    // param must still win over auto-detection (decideEnginePolicy's first
    // branch) -- pins the "opt-out always available" half of the policy
    // against a REAL serve, not just the unit-level decideEnginePolicy matrix.
    test.setTimeout(240_000); // real pyodide boot dominates, as elsewhere in this file
    await page.goto(`http://127.0.0.1:${PORT}/?engine=1&enginehost=pyodide`);
    await expect(page.getByTestId('engine-status')).toHaveText('ready', { timeout: 200_000 });
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-engine-host', 'pyodide');

    const result = await page.evaluate(() => (window as any).__engineSelfTest());
    expect(result.freqDataComplex).toBe(true);
  });
});
