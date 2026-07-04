<script lang="ts">
  /**
   * Bench shell root (Tasks 9 + 12). The chrome (header, ribbon,
   * context card, adaptive tray/rail layout) plus the analysis payload:
   * the context cards drive the engine actions, and the plot region
   * mounts `PlotSurface` fed by `buildPlotModel` reacting to the loaded
   * dataset + selection + active view.
   *
   * Shared stores are created ONCE here and passed down: `viewState`
   * (view switching), `selection` (set chips), `engine` (pyodide
   * worker), and `actions` (orchestration binding the two). `?narrow=1`
   * forces the compact layout; `?fixture=1` loads the checked-in
   * impulse.dvma so the whole pipeline can be exercised without a live
   * Load Data dialog (Task 13).
   *
   * TF Bode composes two stacked PlotSurfaces (magnitude over phase)
   * sharing x; the sonogram view draws a `<canvas>` viridis heat layer
   * beneath empty PlotSurface axes.
   */
  import { onMount } from 'svelte';
  import Header from './components/Header.svelte';
  import Ribbon from './components/Ribbon.svelte';
  import ContextCard from './components/ContextCard.svelte';
  import NarrowRail from './components/NarrowRail.svelte';
  import Tray from './components/Tray.svelte';
  import PlotSurface from './components/PlotSurface.svelte';
  import ZoomToolbar from './components/ZoomToolbar.svelte';
  import Legend from './components/Legend.svelte';
  import EngineProbe from './components/EngineProbe.svelte';
  import { createViewState } from './lib/stores/viewstate';
  import { createSelection } from './lib/stores/selection';
  import { createEngineStore } from './lib/stores/engine';
  import { createActions } from './lib/analysis/actions';
  import { buildPlotModel, type FreqMode, type SetArrays, type VisibleLine } from './lib/plot/model';
  import { dataExtent, type PlotModel } from './lib/plot/build';
  import { readDvma } from './lib/codec/dvma';
  import impulseUrl from './assets/impulse.dvma?url';

  // Shared stores — created once at app root.
  const viewState = createViewState();
  const selection = createSelection();
  const engine = createEngineStore();
  const actions = createActions(engine, selection);

  const derivedStore = actions.derived;
  const computeError = actions.computeError;
  const active = viewState.active;
  const legendEntries = selection.legendEntries;
  const sharedFreqRange = viewState.sharedFreqRange;
  const currentSlice = viewState.current;

  // Card-owned display state that lives above the plot model.
  let freqMode = $state<FreqMode>('fft');
  let dynRangeDb = $state(60);
  // The sonogram card's selected set index, lifted here so the canvas
  // heat layer renders THAT set's sonogram (not just the first computed).
  let sonoSetIdx = $state(0);
  let mode = $state<'box' | 'pan'>('box');

  // `?narrow=1` forces the narrow layout; `?fixture=1` auto-loads data.
  const params = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : new URLSearchParams();
  const forcedNarrow = params.get('narrow') === '1';
  const fixtureRequested = params.get('fixture') === '1';

  let mediaNarrow = $state(false);
  const narrow = $derived(forcedNarrow || mediaNarrow);

  onMount(() => {
    // Fixture hook: fetch the checked-in .dvma and load it into the tray.
    if (fixtureRequested) {
      fetch(impulseUrl)
        .then((r) => r.arrayBuffer())
        .then((buf) => actions.loadDataset(readDvma(new Uint8Array(buf))))
        .catch((e) => console.error('[fixture] load failed:', e));
    }

    if (forcedNarrow || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(max-width: 1000px)');
    mediaNarrow = mq.matches;
    const update = (e: MediaQueryListEvent) => (mediaNarrow = e.matches);
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  });

  // Load / Save are wired to real handlers in Task 13; here they no-op.
  const onload = () => {};
  const onsave = () => {};

  // ---- Plot model assembly (derived: dataset + selection + view) ----

  /** Decoded per-set arrays as a list, keyed for the model builder. */
  const setArrays = $derived(Object.values($derivedStore) as SetArrays[]);

  /** Visible (on/fade) lines from the legend entries (off lines omitted). */
  const visible = $derived<VisibleLine[]>(
    $legendEntries.map((e) => ({
      setId: e.setId, ch: e.ch, state: e.state === 'off' ? 'fade' : e.state, color: e.color,
    })),
  );

  const view = $derived($active);
  const range = $derived($currentSlice.range);
  const plotType = $derived($currentSlice.plotType);
  const coherence = $derived($currentSlice.coherence);
  const bode = $derived(view === 'tf' && plotType === 'bode');

  /** Single-pane model for the active view (magnitude pane when Bode). */
  const model = $derived<PlotModel>(
    buildPlotModel({
      view, sets: setArrays, visible, freqMode, tfPlotType: plotType,
      coherence, freqRange: $sharedFreqRange, range,
    }),
  );

  /** Bode's second (phase) pane — only assembled when Bode is active. */
  const phaseModel = $derived<PlotModel>(
    bode
      ? buildPlotModel({
          view, sets: setArrays, visible, tfPlotType: 'phase',
          coherence: false, freqRange: $sharedFreqRange, range,
        })
      : model,
  );

  /** Extent of the currently visible lines (for the zoom toolbar's Auto X/Y). */
  const extent = $derived({
    x: dataExtent(model.lines, 'x', 'any'),
    y: dataExtent(model.lines, 'y', 'left'),
  });

  const hasData = $derived(setArrays.length > 0);

  // ---- Sonogram heat layer (canvas beneath empty PlotSurface axes) ----

  /** 6-stop viridis-like ramp (t in [0,1] → [r,g,b]). */
  const VIRIDIS: [number, number, number][] = [
    [68, 1, 84], [59, 82, 139], [33, 145, 140],
    [94, 201, 98], [173, 220, 47], [253, 231, 37],
  ];
  function viridis(t: number): [number, number, number] {
    const x = Math.min(1, Math.max(0, t)) * (VIRIDIS.length - 1);
    const i = Math.floor(x), f = x - i;
    const a = VIRIDIS[i], b = VIRIDIS[Math.min(VIRIDIS.length - 1, i + 1)];
    return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
  }

  let sonoCanvas = $state<HTMLCanvasElement | undefined>();

  /**
   * The sonogram image of the SET the SonoCard has selected (its setId,
   * looked up via the working-set order the card indexes into), so the
   * heat layer tracks the card's set/chan choice rather than blindly
   * showing whichever set was computed first.
   */
  const sono = $derived.by(() => {
    const setId = actions.workingSets()[sonoSetIdx]?.setId;
    const chosen = setId !== undefined ? $derivedStore[setId]?.sono : undefined;
    // Fall back to any computed sonogram so a stale index still shows something.
    return chosen ?? setArrays.find((s) => s.sono)?.sono;
  });

  $effect(() => {
    if (view !== 'sono' || !sonoCanvas || !sono) return;
    const nf = sono.freqAxis.length;
    const nt = sono.timeAxis.length;
    if (nf === 0 || nt === 0) return;
    const cx = sonoCanvas.getContext('2d');
    if (!cx) return;
    sonoCanvas.width = nt;
    sonoCanvas.height = nf;
    // sono.data is (Nf, Nt) magnitude; convert to dB, clamp to dynRangeDb.
    const re = sono.data.re;
    let peak = 0;
    for (let i = 0; i < re.length; i++) if (re[i] > peak) peak = re[i];
    const peakDb = peak > 0 ? 20 * Math.log10(peak) : 0;
    const img = cx.createImageData(nt, nf);
    for (let fr = 0; fr < nf; fr++) {
      for (let t = 0; t < nt; t++) {
        const v = re[fr * nt + t];
        const db = v > 0 ? 20 * Math.log10(v) : peakDb - dynRangeDb;
        const norm = (db - (peakDb - dynRangeDb)) / dynRangeDb; // 0..1
        const [r, g, b] = viridis(norm);
        // Flip vertically so low freq is at the bottom (canvas y grows down).
        const px = ((nf - 1 - fr) * nt + t) * 4;
        img.data[px] = r; img.data[px + 1] = g; img.data[px + 2] = b; img.data[px + 3] = 255;
      }
    }
    cx.putImageData(img, 0, 0);
  });

  // Empty-lines model so PlotSurface draws sonogram axes over the canvas.
  const sonoAxisModel = $derived<PlotModel>({
    lines: [], xLabel: 'Time (s)', yLabel: 'Frequency (Hz)',
    xRange: sono ? [sono.timeAxis[0], sono.timeAxis[sono.timeAxis.length - 1]] : null,
    yRange: sono ? [sono.freqAxis[0], sono.freqAxis[sono.freqAxis.length - 1]] : null,
  });

</script>

<div class="app" class:narrow>
  <EngineProbe />
  <Header summary={hasData ? `${setArrays.length} set${setArrays.length === 1 ? '' : 's'}` : 'no data'} {onload} {onsave} />
  <Ribbon {viewState} {narrow} />
  <ContextCard {narrow} {viewState} {selection} {actions} bind:freqMode bind:dynRangeDb bind:sonoSetIdx />

  <main class="main">
    {#if narrow}
      <NarrowRail {selection} />
    {:else}
      <aside class="tray" data-testid="tray">
        <Tray {selection} />
      </aside>
    {/if}

    <section class="plot" aria-label="plot">
      {#if !hasData}
        <div class="empty-state">
          <p class="es-title">No data</p>
          <p class="es-sub">Load Data to begin</p>
        </div>
      {:else if view === 'sono'}
        <div class="plot-host">
          <canvas bind:this={sonoCanvas} data-testid="sono-canvas" class="sono-heat"></canvas>
          <PlotSurface model={sonoAxisModel} {viewState} />
          <ZoomToolbar {viewState} dataExtent={extent} bind:mode />
        </div>
      {:else if bode}
        <div class="plot-host bode">
          <div class="bode-pane">
            <PlotSurface {model} {mode} {viewState} />
            <ZoomToolbar {viewState} dataExtent={extent} bind:mode />
            <Legend {selection} {viewState} />
          </div>
          <div class="bode-pane">
            <PlotSurface model={phaseModel} {mode} {viewState} />
          </div>
        </div>
      {:else}
        <div class="plot-host">
          <PlotSurface {model} {mode} {viewState} />
          <ZoomToolbar {viewState} dataExtent={extent} bind:mode />
          <Legend {selection} {viewState} />
        </div>
      {/if}
      {#if $computeError}
        <div class="plot-err" role="alert">Compute failed: {$computeError}</div>
      {/if}
    </section>
  </main>
</div>

<style>
  .app {
    height: 100vh;
    display: grid;
    grid-template-rows: auto auto auto 1fr;
    background: var(--bg);
  }
  .main {
    display: flex;
    min-height: 0;
  }
  .tray {
    flex: 0 0 300px;
    width: 300px;
    display: flex;
    min-height: 0;
    background: var(--surface);
    border-right: 1px solid var(--border);
  }
  .plot {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    padding: 12px;
    gap: 6px;
  }
  .plot-host {
    flex: 1;
    min-height: 0;
    position: relative;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .plot-host.bode {
    display: flex;
    flex-direction: column;
    gap: 0;
  }
  .bode-pane {
    position: relative;
    flex: 1;
    min-height: 0;
  }
  .bode-pane:first-child {
    border-bottom: 1px solid var(--border);
  }
  .sono-heat {
    position: absolute;
    /* Align to PlotSurface's inner data rect (margins L58/T16/R18/B42). */
    left: 58px;
    top: 16px;
    right: 18px;
    bottom: 42px;
    width: auto;
    height: auto;
    image-rendering: pixelated;
  }
  .empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    color: var(--muted);
  }
  .es-title {
    margin: 0;
    font-weight: 650;
    font-size: 15px;
    color: var(--text);
  }
  .es-sub {
    margin: 0;
    font-size: 12.5px;
  }
  .plot-err {
    flex: 0 0 auto;
    font-size: 12px;
    color: #b91c1c;
    padding: 2px 4px;
  }
</style>
