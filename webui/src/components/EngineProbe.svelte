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
   */
  import { onMount } from 'svelte';
  import { createEngineStore, type EngineStore } from '../lib/stores/engine';

  let statusText = $state('idle');

  const engineRequested =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('engine') === '1';

  onMount(() => {
    if (!engineRequested) return;
    const engine: EngineStore = createEngineStore();
    const unsub = engine.status.subscribe((s) => (statusText = s));

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

    engine.boot();
    return () => {
      unsub();
      engine.client.dispose();
      delete (window as any).__engineSelfTest;
    };
  });
</script>

<!-- Visually hidden status line; present so e2e can read the boot state. -->
<span data-testid="engine-status" class="sr-only">{statusText}</span>

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
