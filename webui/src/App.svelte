<script lang="ts">
  /**
   * Bench shell root (Task 9; design spec §§1–5). This is CHROME ONLY —
   * the header, stage ribbon, context card and the adaptive
   * wide-tray / narrow-rail layout. The tray and plot regions are
   * PLACEHOLDERS: their real content lands in Tasks 10 and 12, so no
   * plot is mounted and no data model exists yet.
   *
   * The shared stores are instantiated ONCE here and passed down:
   * `createViewState()` (view switching from the ribbon) and
   * `createSelection()` (set chips in the narrow rail). The module-level
   * `stages` store is imported by the ribbon/context-card directly.
   *
   * Layout: a CSS grid of header / (ribbon + context card) / main.
   * `main` is `tray | plot` in WIDE mode; in NARROW mode the tray
   * column is replaced by the 72px `NarrowRail` and the plot takes the
   * freed width. Narrow is forced by `?narrow=1` (deterministic for
   * tests) OR a real viewport width ≤ 1000px.
   */
  import { onMount } from 'svelte';
  import Header from './components/Header.svelte';
  import Ribbon from './components/Ribbon.svelte';
  import ContextCard from './components/ContextCard.svelte';
  import NarrowRail from './components/NarrowRail.svelte';
  import Tray from './components/Tray.svelte';
  import EngineProbe from './components/EngineProbe.svelte';
  import { createViewState } from './lib/stores/viewstate';
  import { createSelection } from './lib/stores/selection';

  // Shared stores — created once at app root.
  const viewState = createViewState();
  const selection = createSelection();

  // `?narrow=1` forces the narrow layout regardless of viewport (tests);
  // otherwise a real viewport width <= 1000px triggers it.
  const forcedNarrow =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('narrow') === '1';

  let mediaNarrow = $state(false);
  const narrow = $derived(forcedNarrow || mediaNarrow);

  onMount(() => {
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
</script>

<div class="app" class:narrow>
  <EngineProbe />
  <Header summary="no data" {onload} {onsave} />
  <Ribbon {viewState} {narrow} />
  <ContextCard {narrow} />

  <main class="main">
    {#if narrow}
      <NarrowRail {selection} />
    {:else}
      <aside class="tray" data-testid="tray">
        <Tray {selection} />
      </aside>
    {/if}

    <section class="plot" aria-label="plot">
      <!-- Task 12 mounts PlotSurface here once a data model exists. -->
      <div class="empty-state">
        <p class="es-title">No data</p>
        <p class="es-sub">Load Data to begin</p>
      </div>
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
</style>
