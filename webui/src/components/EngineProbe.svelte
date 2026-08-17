<script lang="ts">
  /**
   * Engine boot probe (Task 11). Mounts the pyodide engine store, surfaces
   * its status in a `data-testid="engine-status"` element, and — for e2e —
   * exposes `window.__engineSelfTest()` which drives a real `calc_fft`
   * round-trip through the worker and returns the marshalled result shape.
   *
   * Boot is GATED on `?engine=1` so the fast shell e2e tests (and normal app
   * loads that don't yet use compute) never pay the multi-second pyodide boot.
   * When Task 12 wires the plot to real compute, boot will move to a lazy
   * on-first-compute trigger; until then this probe is the boot entry point.
   *
   * The status text is `idle|loading|ready|error` — the e2e waits for `ready`.
   * `data-engine-host` on the same element reports which transport answered
   * (`pyodide` | `native` | `unresolved`): this probe builds its OWN store
   * with `createEngineStore()` and no arguments, so it picks up the default
   * client factory — and therefore `?enginehost=` — for free, which is what
   * makes the native-engine e2e (Task 9) able to drive it.
   *
   * Two more e2e-only hooks exist alongside `__engineSelfTest`, both
   * carry-overs from Task 9's review (the native host has no wasm32 ceiling
   * and a real cancel path, and only a request through a REAL socket proves
   * either):
   *
   *  - `__engineLargeTest`: a ~2M-sample calc_fft (time_axis + time_data ⇒ a
   *    request frame ≳10 MB) — the round-trip the `max_size=256*1024*1024`
   *    raise in `serve.py` exists for (the old `websockets` default of 1 MiB
   *    would sever this mid-frame).
   *  - `__engineStopTest`: starts a multi-second native CWT sonogram, calls
   *    the store's `engine.stop()` shortly after it has genuinely started
   *    computing server-side, and reports how promptly the in-flight call
   *    settles plus whether a follow-up calc succeeds afterward (fresh
   *    socket + greeting). This drives the close-mid-op race end to end
   *    from the CLIENT's side, over a real socket rather than the fake
   *    transport `tests/worker/socketClient.test.ts` uses — but the
   *    SERVER-side half (close actually kills the worker's child process
   *    promptly, not after the op's full duration) is asserted separately
   *    at the unit level in
   *    `tests/test_engine_host.py::test_engine_endpoint_close_mid_op_kills_worker_promptly`,
   *    not re-measured here.
   */
  import { onMount } from 'svelte';
  import { createEngineStore, isEngineStopped, type EngineStore } from '../lib/stores/engine';

  let statusText = $state('idle');
  let hostText = $state('unresolved');

  const engineRequested =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('engine') === '1';

  onMount(() => {
    if (!engineRequested) return;
    const engine: EngineStore = createEngineStore();
    const unsub = engine.status.subscribe((s) => (statusText = s));
    const unsubHost = engine.host.subscribe((h) => (hostText = h ?? 'unresolved'));

    // e2e self-test hook: 2-channel sine, calc_fft, return shape metadata.
    (window as any).__engineSelfTest = async () => {
      await engine.whenReady();
      const fs = 1000;
      const N = 512;
      const nChannels = 2;
      const timeAxis = Float64Array.from({ length: N }, (_, i) => i / fs);
      const timeData = new Float64Array(N * nChannels); // row-major (N, nc)
      for (let i = 0; i < N; i++) {
        timeData[i * nChannels] = Math.sin((2 * Math.PI * 50 * i) / fs);
        timeData[i * nChannels + 1] = Math.sin((2 * Math.PI * 120 * i) / fs);
      }
      const res: any = await engine.enqueue('calc_fft', {
        time_axis: timeAxis,
        time_data: timeData,
        n_channels: nChannels,
        fs,
        window: null,
      });
      // toJs turns the dict into a Map; normalise to a plain result shape.
      const get = (k: string) => (res instanceof Map ? res.get(k) : res[k]);
      const freqAxis = get('freq_axis');
      const freqData = get('freq_data');
      const axisData = freqAxis instanceof Map ? freqAxis.get('data') : freqAxis.data;
      const fdData = freqData instanceof Map ? freqData.get('data') : freqData.data;
      const fdComplex = freqData instanceof Map ? freqData.get('complex') : freqData.complex;
      const fdShape = freqData instanceof Map ? freqData.get('shape') : freqData.shape;
      return {
        freqAxisLen: axisData.length,
        freqDataComplex: fdComplex,
        freqDataLen: fdData.length,
        freqDataShape: Array.from(fdShape),
        nChannels,
      };
    };

    // e2e self-test hook (Task 9 carry-over): a large calc_fft request —
    // ~2M-sample time_axis + time_data, each ~16 MB, so the request frame is
    // comfortably ≳10 MB — round-tripped through the native engine. Proves
    // the `max_size=256*1024*1024` raise in serve.py actually matters (the
    // `websockets` default 1 MiB cap would sever this mid-frame).
    (window as any).__engineLargeTest = async () => {
      await engine.whenReady();
      // Warm the worker subprocess (its one-time numpy/scipy/pydvma import)
      // with a cheap calc first, same as __engineStopTest below, so a slow
      // cold spawn (Windows especially) isn't racing the timed transfer.
      await engine.enqueue('calc_fft', {
        time_axis: Float64Array.from({ length: 64 }, (_, i) => i / 1000),
        time_data: Float64Array.from({ length: 64 }, (_, i) => Math.sin((2 * Math.PI * 50 * i) / 1000)),
        n_channels: 1,
        fs: 1000,
        window: null,
      });

      const fs = 8000;
      const N = 2_097_152; // ~2M samples; Float64Array(N).byteLength = 16 MiB
      const timeAxis = new Float64Array(N);
      const timeData = new Float64Array(N);
      for (let i = 0; i < N; i++) {
        timeAxis[i] = i / fs;
        timeData[i] = Math.sin((2 * Math.PI * 220 * i) / fs);
      }
      const nBytes = timeAxis.byteLength + timeData.byteLength;
      const res: any = await engine.enqueue('calc_fft', {
        time_axis: timeAxis,
        time_data: timeData,
        n_channels: 1,
        fs,
        window: null,
      });
      const get = (k: string) => (res instanceof Map ? res.get(k) : res[k]);
      const freqAxis = get('freq_axis');
      const freqData = get('freq_data');
      const axisData = freqAxis instanceof Map ? freqAxis.get('data') : freqAxis.data;
      const fdData = freqData instanceof Map ? freqData.get('data') : freqData.data;
      return {
        ok: axisData.length > 0 && fdData.length > 0,
        nBytes,
        nOut: fdData.length,
        freqAxisLen: axisData.length,
      };
    };

    // e2e self-test hook (Task 9 carry-over): Stop mid-compute, then
    // reconnect. Starts a multi-second native CWT sonogram, calls the
    // store's `stop()` once the op has had time to genuinely start
    // computing server-side (not just be queued), and reports:
    //  - whether the in-flight call actually rejected with the stop error,
    //    and how long that took (client-visible latency — should be tiny
    //    next to the calc's multi-second solo duration, since restart()
    //    rejects the pending call synchronously rather than waiting on the
    //    server's kill+respawn);
    //  - how long the client-visible stop() call itself took to resolve
    //    (close the old socket, open a fresh one, wait for its greeting) —
    //    this does NOT measure the server's own cancel/kill of the OLD
    //    connection's worker, which proceeds independently; that latency is
    //    asserted separately at the unit level (see the module docstring);
    //  - whether a follow-up calc over the reconnected socket succeeds.
    (window as any).__engineStopTest = async () => {
      await engine.whenReady();
      // Warm the worker subprocess (its one-time numpy/scipy/pydvma import)
      // with a cheap calc first so the timed CWT below isn't measuring that
      // instead of the compute itself.
      await engine.enqueue('calc_fft', {
        time_axis: Float64Array.from({ length: 64 }, (_, i) => i / 1000),
        time_data: Float64Array.from({ length: 64 }, (_, i) => Math.sin((2 * Math.PI * 50 * i) / 1000)),
        n_channels: 1,
        fs: 1000,
        window: null,
      });

      const fs = 8000;
      const N = 800_000; // bench (dev session): ~5 s solo on the CWT path
      const timeAxis = new Float64Array(N);
      const timeData = new Float64Array(N);
      for (let i = 0; i < N; i++) {
        timeAxis[i] = i / fs;
        timeData[i] = Math.sin((2 * Math.PI * 200 * i) / fs) + 0.3 * Math.sin((2 * Math.PI * 833 * i) / fs);
      }

      const longCalc = engine.enqueue('calc_sono', {
        time_axis: timeAxis,
        time_data: timeData,
        n_channels: 1,
        fs,
        ch: 0,
        nperseg: 256,
        noverlap: 128,
        method: 'cwt',
        voices_per_octave: 32,
        w0: 6.0,
      });

      // Let the request actually reach the server and start computing
      // before stopping it — this is what exercises the server's
      // close-interrupts-the-op race (engine_host.handle_connection's
      // asyncio.wait) rather than cancelling something still queued.
      await new Promise((resolve) => setTimeout(resolve, 500));

      const stopCalledAt = performance.now();
      const stopPromise = engine.stop();
      let calcStopped = false;
      let calcErrorName: string | null = null;
      try {
        await longCalc;
      } catch (e: any) {
        calcStopped = isEngineStopped(e);
        calcErrorName = e?.name ?? null;
      }
      const calcSettledMs = performance.now() - stopCalledAt;

      await stopPromise; // full reboot: fresh socket + greeting
      const rebootMs = performance.now() - stopCalledAt;

      let reconnectOk = false;
      let reconnectError: string | null = null;
      try {
        const res: any = await engine.enqueue('calc_fft', {
          time_axis: Float64Array.from({ length: 256 }, (_, i) => i / 1000),
          time_data: Float64Array.from({ length: 256 }, (_, i) => Math.sin((2 * Math.PI * 50 * i) / 1000)),
          n_channels: 1,
          fs: 1000,
          window: null,
        });
        reconnectOk = res != null;
      } catch (e: any) {
        reconnectError = e?.message ?? String(e);
      }

      return { calcStopped, calcErrorName, calcSettledMs, rebootMs, reconnectOk, reconnectError };
    };

    engine.boot();
    return () => {
      unsub();
      unsubHost();
      // `?.` — on the factory path the client does not exist until boot()
      // resolves one, so an unmount mid-boot has nothing to dispose.
      engine.client?.dispose();
      delete (window as any).__engineSelfTest;
      delete (window as any).__engineLargeTest;
      delete (window as any).__engineStopTest;
    };
  });
</script>

<!-- Visually hidden status line; present so e2e can read the boot state (text)
     and which transport answered (data-engine-host). -->
<span data-testid="engine-status" class="sr-only" data-engine-host={hostText}>{statusText}</span>

<style>
  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
</style>
