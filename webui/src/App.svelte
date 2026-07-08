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
  import { onMount, onDestroy } from 'svelte';
  import Header from './components/Header.svelte';
  import Ribbon from './components/Ribbon.svelte';
  import ContextCard from './components/ContextCard.svelte';
  import NarrowRail from './components/NarrowRail.svelte';
  import Tray from './components/Tray.svelte';
  import PlotSurface from './components/PlotSurface.svelte';
  import ZoomToolbar from './components/ZoomToolbar.svelte';
  import NyquistBrush from './components/NyquistBrush.svelte';
  import Legend from './components/Legend.svelte';
  import EngineProbe from './components/EngineProbe.svelte';
  import ToastHost from './components/ToastHost.svelte';
  import { activeStage, capabilities } from './lib/stores/stages';
  import { createViewState, type ViewId } from './lib/stores/viewstate';
  import { createSelection } from './lib/stores/selection';
  import { createAnalysisSettings } from './lib/stores/analysisSettings';
  import { createEngineStore } from './lib/stores/engine';
  import { createToasts } from './lib/stores/toast';
  import { createActions } from './lib/analysis/actions';
  import { createModalStore } from './lib/stores/modal';
  import { buildPlotModel, type FreqMode, type SetArrays, type VisibleLine } from './lib/plot/model';
  import { tfTransformEntries } from './lib/plot/tfChannels';
  import { csdPairEntries } from './lib/plot/csdChannels';
  import type { LegendEntry } from './lib/stores/selection';
  import { readable, get } from 'svelte/store';
  import { dataExtent, type PlotModel } from './lib/plot/build';
  import { readDvma, writeDvma } from './lib/codec/dvma';
  import { sniffFormat } from './lib/files/sniff';
  import { fallbackDir, pickWorkDir, restoreWorkDir, type WorkDir } from './lib/files/workdir';
  import { autosave, clearAutosave, restoreOffer } from './lib/files/autosave';
  import type { DvmaDataset } from './lib/model/dataset';
  import { createAcquireStore } from './lib/stores/acquire';
  import { createMonitorStore } from './lib/stores/monitor';
  import { initTheme } from './lib/stores/theme';
  import { selectProvider } from './lib/audio/provider';
  import MiniMonitor from './components/MiniMonitor.svelte';
  import LiveScope from './components/LiveScope.svelte';
  import FitChip from './components/FitChip.svelte';
  import impulseUrl from './assets/impulse.dvma?url';
  // 3-channel fixture (Task R4) for exercising the TF out/in remap end to
  // end; loaded ONLY under `?fixture=3ch` so shipped `?fixture=1` stays the
  // 2-channel impulse. Imported as a bundled URL from the test fixtures.
  import impulse3chUrl from '../tests/fixtures/impulse3ch.dvma?url';

  // Shared stores — created once at app root.
  const viewState = createViewState();
  const selection = createSelection();
  // Per-set analysis settings (Task R1): keyed by setId, target-driven
  // dropdown-follows-tray. Created before actions so calc* can read it.
  const analysisSettings = createAnalysisSettings(selection);
  const engine = createEngineStore();
  const toasts = createToasts();
  // Modal-fit state (Task A1): one model per dataset, owned here and shared
  // with the actions (which run the stateless calc_fit and push results in)
  // and the Fit card (controls) + the plot recon overlay.
  const modal = createModalStore();
  const actions = createActions(engine, selection, analysisSettings, modal, toasts);
  // Acquisition store (Plan 2): manages Web Audio device enumeration +
  // recording lifecycle; the liveSource capability gate flips on init.
  const acquire = createAcquireStore();
  // Monitor store (Plan 2 Live): real-time oscilloscope feed. Created
  // here and passed to both LiveCard (controls) and OscCanvas (render).
  // Reads device config from the acquire store so Setup configures both.
  const monitor = createMonitorStore(acquire);

  // Monitor lifecycle (round-2 redesign): the monitor is a PERSISTENT
  // bottom-left mini-oscilloscope that lives across all stages, with its
  // own start/stop (MiniMonitor + LiveCard). It is NO LONGER auto-stopped
  // when leaving the Live stage — that C1 fix conflicted with the desired
  // design. Instead the mic is released only when the USER stops it or the
  // whole app tears down: onDestroy below, plus pagehide/beforeunload
  // handlers registered in onMount for real browser navigation/close. The
  // I2/I3 start-race guards and the C2 setup-throw stream release still
  // apply inside the store + source layer.
  onDestroy(() => monitor.stop());

  // ---- File I/O state (Task 13): working directory + autosave ----
  // The working directory is where Save writes and autosave persists.
  // Null until restored/picked → the pipeline falls back to download/upload.
  let workdir = $state<WorkDir | null>(null);
  const workdirName = $derived(workdir?.name ?? 'Downloads');
  // Autosave defaults ON; every dataset mutation schedules a debounced write.
  let autosaveEnabled = $state(true);
  // The current dataset (subscribed below to drive autosave).
  const datasetStore = actions.dataset;

  const derivedStore = actions.derived;
  const computeErrors = actions.computeErrors;
  const active = viewState.active;
  const setsViewStore = selection.setsView;
  const legendEntries = selection.legendEntries;
  const legendRows = selection.legendRows;       // off-inclusive (legend display)
  /**
   * Ids of the modal-fit pseudo-set(s) (round-5 item 13). Their recon lines
   * flow through the normal visible-line pipeline but must draw DASHED (the fit
   * signature) — see `visible`. Kept as a set for O(1) membership.
   */
  const fitSetIds = $derived(new Set($setsViewStore.filter((s) => s.role === 'fit').map((s) => s.id)));
  const channelLabel = selection.channelLabel;   // custom per-line labels (R5)
  const sharedFreqRange = viewState.sharedFreqRange;
  const currentSlice = viewState.current;

  // Display state derived from the per-set settings store, keyed to the
  // current analysis target (Task R1): the plot's spectral quantity and
  // the sonogram heat-map range now follow the FOCUSED set's settings
  // rather than App-owned local state.
  const analysisTarget = analysisSettings.analysisTarget;
  const settingsMap = analysisSettings.map;   // subscribe so the deriveds re-run on patch
  const freqMode = $derived<FreqMode>(
    (void $settingsMap, analysisSettings.settingFor($analysisTarget, 'freq').mode),
  );
  const dynRangeDb = $derived(
    (void $settingsMap, analysisSettings.settingFor($analysisTarget, 'sono').dynRangeDb),
  );
  let mode = $state<'box' | 'pan'>('box');

  // Reference to the CURRENTLY MOUNTED primary PlotSurface (single / Bode
  // magnitude / sono axes), bound in each plot branch below. The Export card
  // reads its <svg> via `getSvg` to serialise the figure. One ref suffices:
  // only one primary plot is mounted at a time (the branches are mutually
  // exclusive), and it is re-bound as the view switches.
  let plotRef = $state<PlotSurface | undefined>();
  /** Active plot's root <svg>, or undefined when no plot is mounted. */
  const getSvg = (): SVGSVGElement | undefined => plotRef?.getSvgElement();

  // `?narrow=1` forces the narrow layout; `?fixture=1` auto-loads the
  // 2-channel impulse; `?fixture=3ch` auto-loads the 3-channel fixture
  // (TF out/in e2e). Any recognised fixture flag opens the e2e hooks below.
  const params = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : new URLSearchParams();
  const forcedNarrow = params.get('narrow') === '1';
  const fixtureParam = params.get('fixture');
  const fixtureRequested = fixtureParam === '1' || fixtureParam === '3ch';
  const fixtureUrl = fixtureParam === '3ch' ? impulse3chUrl : impulseUrl;
  // `?fixture=1` also opens a read-only e2e test hook: `window.__viewState`
  // exposes the live view-state store so Playwright can assert on the
  // active view's range and zoom-history length without brittle DOM
  // scraping. Gated on the fixture flag so it never exists in normal runs.
  if (typeof window !== 'undefined' && fixtureRequested) {
    (window as unknown as { __viewState?: typeof viewState }).__viewState = viewState;
  }

  let mediaNarrow = $state(false);
  const narrow = $derived(forcedNarrow || mediaNarrow);

  onMount(() => {
    // Reconcile the theme store + wire the live OS-preference listener (the
    // inline boot script in index.html already stamped data-theme pre-paint).
    initTheme();

    // Fixture hook: fetch the selected checked-in .dvma into the tray.
    if (fixtureRequested) {
      fetch(fixtureUrl)
        .then((r) => r.arrayBuffer())
        .then((buf) => loadAndFocus(readDvma(new Uint8Array(buf))))
        .catch((e) => console.error('[fixture] load failed:', e));
    }

    // Select the acquisition backend, then boot the acquire store. Wave B:
    // when the app is opened through `pydvma serve` (a `?bridge=ws://…`
    // param, an injected `window.__pydvma_bridge`, or a same-origin
    // `/config` document) the BridgeProvider drives real hardware over a
    // WebSocket; otherwise the WebAudioProvider keeps the browser-soundcard
    // path. `init` then flips the liveSource gate + enumerates devices for
    // whichever backend was chosen (mirrors the old inline `acquire.init`).
    void (async () => {
      try {
        acquire.setProvider(await selectProvider());
      } catch (e) {
        console.warn('[bridge] provider selection failed, using Web Audio:', e);
      }
      await acquire.init();
    })();

    // Release the mic if the browser tab is closed or navigated away while
    // the monitor is live (onDestroy covers in-app teardown; these cover
    // real page unload, where Svelte's onDestroy may not run).
    const onUnload = () => monitor.stop();
    window.addEventListener('pagehide', onUnload);
    window.addEventListener('beforeunload', onUnload);
    const cleanupUnload = () => {
      window.removeEventListener('pagehide', onUnload);
      window.removeEventListener('beforeunload', onUnload);
    };

    // Restore last session's working folder (File System Access API), then
    // offer to restore an autosaved session if one is waiting in IndexedDB.
    // Both are best-effort and never block the shell. Skipped under
    // ?fixture=1 so the e2e fixture load is not clobbered by a restore.
    if (!fixtureRequested) void bootFileRestore();

    // Autosave: on every dataset mutation, schedule a debounced write. Pass a
    // THUNK, not bytes — writeDvma (a full zip serialize) then runs once when
    // the 2 s debounce fires, not eagerly on every store emission (and a fresh
    // loadDataset / Restore no longer re-serializes the bytes just loaded).
    // stampUiState is called inside the thunk so channel labels + analysis
    // settings are captured at serialization time (Plan 2 persistence).
    const unsubDataset = datasetStore.subscribe((ds) => {
      if (!ds) return;
      autosave(() => { actions.stampUiState(); return writeDvma(ds); }, workdir, autosaveEnabled);
    });

    if (forcedNarrow || typeof window.matchMedia !== 'function') {
      return () => { unsubDataset(); cleanupUnload(); };
    }
    const mq = window.matchMedia('(max-width: 1000px)');
    mediaNarrow = mq.matches;
    const update = (e: MediaQueryListEvent) => (mediaNarrow = e.matches);
    mq.addEventListener('change', update);
    return () => {
      unsubDataset();
      mq.removeEventListener('change', update);
      cleanupUnload();
    };
  });

  /**
   * Boot-time file restore: reconnect last session's working folder, then
   * — if an autosave is waiting — show a "Restore last session?" toast.
   * Restore parses the autosaved bytes and loads them; Dismiss clears the
   * autosave so it never re-offers.
   */
  async function bootFileRestore(): Promise<void> {
    try {
      const dir = await restoreWorkDir();
      if (dir) workdir = dir;
    } catch (e) {
      console.warn('[workdir] restore failed:', e);
    }
    let saved: Uint8Array | null = null;
    try {
      saved = await restoreOffer();
    } catch (e) {
      console.warn('[autosave] restore read failed:', e);
    }
    if (!saved) return;
    const bytes = saved;
    toasts.push('Restore last session?', {
      level: 'info',
      actions: [
        {
          label: 'Restore',
          run: () => {
            try {
              loadAndFocus(readDvma(bytes));
            } catch (e) {
              toasts.push(`Restore failed: ${e instanceof Error ? e.message : e}`, { level: 'error' });
            }
          },
        },
        { label: 'Dismiss', run: () => void clearAutosave() },
      ],
    });
  }

  // ---- Load / Save pipeline (Task 13) ----

  /**
   * Load a dataset and jump the active view to one that HAS data (round-4
   * bug 4). `actions.loadDataset` seeds every populated view's slices and
   * returns the populated views in priority order (time → frequency → tf →
   * sono). If the current view already has data we keep it; otherwise we
   * switch to the first populated view — so a TF-only file lands on TF, a
   * frequency-only file on Frequency, etc. Both the plot view and the
   * ribbon stage move together so the context card follows. Shared by every
   * load entry point (Load Data, fixture, session restore).
   */
  function loadAndFocus(ds: DvmaDataset): void {
    const views = actions.loadDataset(ds);
    if (views.length && !views.includes(get(active) as ViewId)) {
      viewState.activate(views[0]);
      activeStage.set(views[0]);
    }
  }

  /**
   * Convert loaded file bytes to a DvmaDataset by format. `.dvma` reads
   * directly; legacy `.npy` and JW-logger `.mat` go through the engine
   * (glue.py converts them to a .dvma container which `readDvma` then
   * parses). The engine call boots pyodide lazily on first use.
   */
  async function toDataset(bytes: Uint8Array, name: string): Promise<DvmaDataset> {
    const fmt = sniffFormat(bytes, name);
    if (fmt === 'dvma') return readDvma(bytes);
    if (fmt === 'npy' || fmt === 'mat') {
      engine.boot(); // idempotent; the conversion op needs a live engine
      const op = fmt === 'npy' ? 'legacy_to_dvma' : 'mat_to_dvma';
      const payloadKey = fmt === 'npy' ? 'npy_bytes' : 'mat_bytes';
      // A cold-engine conversion pays the full pyodide boot (seconds of
      // silence) — show a transient "Converting…" toast so the wait doesn't
      // read as a hang, and clear it once the conversion settles.
      const convertingId = toasts.push(`Converting ${name}…`, { level: 'info', timeout: 600_000 });
      try {
        const res = await engine.enqueue<{ dvma: Uint8Array } | Map<string, Uint8Array>>(op, {
          [payloadKey]: bytes,
        });
        const dvma = res instanceof Map ? res.get('dvma')! : res.dvma;
        return readDvma(dvma instanceof Uint8Array ? dvma : new Uint8Array(dvma));
      } finally {
        toasts.dismiss(convertingId);
      }
    }
    throw new Error(`unrecognised file "${name}" (not a .dvma, legacy .npy, or .mat)`);
  }

  /** Load Data: open a file via the working dir (or fallback), parse, load. */
  const onload = async () => {
    const dir = workdir ?? fallbackDir();
    let picked: { bytes: Uint8Array; name: string } | null;
    try {
      picked = await dir.open();
    } catch (e) {
      toasts.push(`Could not open file: ${e instanceof Error ? e.message : e}`, { level: 'error' });
      return;
    }
    if (!picked) return; // user cancelled
    try {
      const ds = await toDataset(picked.bytes, picked.name);
      loadAndFocus(ds);
      toasts.push(`Loaded ${picked.name}`, { level: 'success' });
    } catch (e) {
      toasts.push(`Load failed: ${e instanceof Error ? e.message : e}`, { level: 'error' });
    }
  };

  /** Default save filename: pydvma_YYYY-MM-DD_HHMM.dvma from the clock. */
  function defaultSaveName(now: Date): string {
    const p = (n: number) => String(n).padStart(2, '0');
    const stamp = `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}_${p(now.getHours())}${p(now.getMinutes())}`;
    return `pydvma_${stamp}.dvma`;
  }

  /** Save Dataset: prompt a name, write the .dvma, persist via the working dir. */
  const onsave = async () => {
    const ds = $datasetStore;
    if (!ds) {
      toasts.push('Nothing to save yet — load or acquire data first.', { level: 'info' });
      return;
    }
    const suggested = defaultSaveName(new Date());
    const name = window.prompt('Save dataset as…', suggested);
    if (!name) return; // cancelled
    const filename = name.toLowerCase().endsWith('.dvma') ? name : `${name}.dvma`;
    try {
      actions.stampUiState();        // persist channel labels + analysis settings
      const bytes = writeDvma(ds);
      const dir = workdir ?? fallbackDir();
      await dir.save(filename, bytes);
      await clearAutosave(); // a clean save supersedes any pending autosave
      toasts.push(`Saved ${filename}`, { level: 'success' });
    } catch (e) {
      toasts.push(`Save failed: ${e instanceof Error ? e.message : e}`, { level: 'error' });
    }
  };

  /** Working-dir chip: (re)pick a folder (or fall back to download mode). */
  const onpickdir = async () => {
    workdir = await pickWorkDir();
    if (workdir.kind === 'fsaccess') {
      toasts.push(`Working folder: ${workdir.name}`, { level: 'success' });
    }
  };

  // ---- Plot model assembly (derived: dataset + selection + view) ----

  /** Decoded per-set arrays as a list, keyed for the model builder. */
  const setArrays = $derived(Object.values($derivedStore) as SetArrays[]);

  /**
   * Real time-series accessor for tray sparklines: channel `ch` of set
   * `setId`, extracted from the decoded TimeData (row-major (Ns, Nc), same
   * as the time-view builder). Rebuilt as a fresh closure whenever the
   * decoded store changes, so previews go live as data loads or is cleaned.
   */
  const channelSeries = $derived.by(() => {
    const store = $derivedStore;
    return (setId: number, ch: number): Float64Array | undefined => {
      const t = store[setId]?.time;
      if (!t) return undefined;
      const cols = t.data.shape[1] ?? 1;
      if (ch >= cols) return undefined;
      const n = t.axis.length;
      const out = new Float64Array(n);
      for (let i = 0; i < n; i++) out[i] = t.data.re[i * cols + ch];
      return out;
    };
  });

  const view = $derived($active);

  /**
   * Compute-error kind for the ACTIVE view (Round-3 item 2): the under-plot
   * banner shows only the error belonging to what is on screen, so a failed
   * TF never bleeds its message onto the frequency/sono plots. The frequency
   * view maps to 'fft' or 'psd' by the current spectral mode; the time view
   * maps to the clean-impulse op.
   */
  const activeErrorKind = $derived(
    view === 'tf' ? 'tf'
    : view === 'sono' ? 'sono'
    : view === 'time' ? 'clean'
    : freqMode === 'fft' ? 'fft' : 'psd',
  );

  /**
   * Per-set TF input channel (Task R4): the `chIn` the set's TF was
   * computed with, read off its decoded `tf` slice. `undefined` before
   * Calc TF (or for a set with no TF), or `null` for an ORPHAN TF whose
   * columns are the lines (round-5 item 3) → the transform leaves that
   * set's entries untouched (plain per-channel labels). One accessor feeds
   * BOTH the legend transform and the visible-line list so plot and legend
   * stay in lock-step.
   */
  const tfChInFor = $derived((setId: number): number | null | undefined => $derivedStore[setId]?.tf?.chIn);

  /**
   * PLOT-facing entries for the ACTIVE view (off lines dropped). For TF,
   * the raw per-channel entries are transformed to the out/in form
   * (input dropped, lines labelled `ch_out/ch_in`) so what is DRAWN
   * matches the R4 remap; every other view uses the raw entries. This
   * feeds `visible` below; the legend LISTS the off-inclusive
   * `legendRows` instead (see `tfLegend`), so a line toggled off leaves
   * the plot but stays in the legend struck-through. The custom channel
   * labels (R5) are threaded in as the `label` accessor so a renamed
   * line reads e.g. `hammer/accel` in the out/in label; the non-TF views
   * already carry the custom label through `legendEntries`.
   */
  const viewEntries = $derived<LegendEntry[]>(
    view === 'tf'
      ? tfTransformEntries($legendEntries, tfChInFor, $channelLabel)
      : $legendEntries,
  );

  /**
   * A store wrapper so `Legend` can take the TF entries as an override.
   * Built from the OFF-INCLUSIVE `legendRows` (not `viewEntries`) so an
   * off TF line stays listed struck-through and can be cycled back on —
   * same round-2 fix the non-TF legend got. The transform still drops
   * the input channel (it has no TF line, off or on) and preserves each
   * row's tri-state through the spread.
   */
  const tfLegend = $derived(
    view === 'tf'
      ? readable(tfTransformEntries($legendRows, tfChInFor, $channelLabel))
      : undefined,
  );

  /**
   * Per-set CSD pair (round-5 item 7): the `(i, j)` channels the set's
   * cross-spectrum plots, read off its decoded `csd` slice. `undefined` before
   * Calc CSD (or for a set with no CSD) → the legend transform leaves that
   * set's rows untouched.
   */
  const csdPairFor = $derived((setId: number): { i: number; j: number } | undefined => {
    const c = $derivedStore[setId]?.csd;
    return c ? { i: c.i ?? 0, j: c.j ?? 1 } : undefined;
  });

  /**
   * CSD legend override — collapses each set's per-channel rows to the single
   * pair row `S(x,y)` the plot draws (round-5 item 7), so the legend and the
   * one-line-per-set cross-spectrum agree. Built from the off-inclusive
   * `legendRows` so an off pair line stays listed struck-through, like TF.
   * Only active in CSD mode; the model self-selects the pair line regardless,
   * so `visible` needs no CSD filter.
   */
  const csdLegend = $derived(
    view === 'frequency' && freqMode === 'csd'
      ? readable(csdPairEntries($legendRows, csdPairFor, $channelLabel))
      : undefined,
  );

  /** The active view's legend override (TF out/in, or CSD pair), else none. */
  const legendOverride = $derived(tfLegend ?? csdLegend);

  /**
   * Visible (on/fade) lines fed to the plot model, derived from the SAME
   * `viewEntries` the legend shows (off lines already omitted). For TF
   * this means the input channel is dropped here too, so a stale render
   * can never show a line the legend hides. The model still remaps each
   * surviving source channel to its output column via the tf slice's
   * `chIn` — this list only decides WHICH channels appear.
   */
  const visible = $derived<VisibleLine[]>(
    viewEntries.map((e) => ({
      setId: e.setId, ch: e.ch, state: e.state === 'off' ? 'fade' : e.state, color: e.color,
      // A modal-fit pseudo-set's recon lines draw dashed (round-5 item 13).
      dashed: fitSetIds.has(e.setId),
    })),
  );

  const range = $derived($currentSlice.range);
  const plotType = $derived($currentSlice.plotType);
  const coherence = $derived($currentSlice.coherence);
  // Per-view axis-scale toggles (R3): frequency x lin↔log, magnitude
  // dB↔linear. Threaded into the model so buildPlotModel branches the
  // magnitude maths / y-label and buildPlot picks the log-x mapping.
  const xScale = $derived($currentSlice.xScale);
  const yScale = $derived($currentSlice.yScale);
  const bode = $derived(view === 'tf' && plotType === 'bode');
  const nyquist = $derived(view === 'tf' && plotType === 'nyquist');
  // Round-5 axis-nav aux state: Nyquist Real/Imag window, Bode phase-pane y,
  // coherence right-axis mode. All live on the tf view slice.
  const nyquistRange = $derived($currentSlice.nyquistRange);
  const phaseRange = $derived($currentSlice.phaseRange);
  const coherenceAuto = $derived($currentSlice.coherenceAuto);

  // Which axis toggles to surface in the toolbar (R3). x-log applies
  // where x IS frequency: the frequency view, and the tf view except
  // Nyquist (whose x is Real(H), not frequency). y (dB↔lin) applies to
  // MAGNITUDE panes only: frequency fft/psd (csd is a coherence, not a
  // dB magnitude), and tf mag/bode (not phase/real/imag/nyquist).
  const showXScale = $derived(
    view === 'frequency' || (view === 'tf' && plotType !== 'nyquist'),
  );
  const showYScale = $derived(
    (view === 'frequency' && (freqMode === 'fft' || freqMode === 'psd'))
    || (view === 'tf' && (plotType === 'mag' || plotType === 'bode')),
  );

  /**
   * Ephemeral LOCAL reconstruction overlay (Task A1; round-5 item 13). Drawn
   * ONLY on the Fit stage (which reuses view 'tf') — the transient pink
   * "just-fitted" feedback, not a dataset. The GLOBAL reconstruction is NO
   * LONGER an App-level overlay: it is now the modal-fit PSEUDO-SET (a tray
   * card whose dashed lines flow through the normal visible pipeline; see
   * `syncModal` in actions), so it gets tri-state / solo / legend for free.
   * We therefore pass ONLY `local` here (global omitted, showGlobal false) so
   * the model draws just the pink overlay and never double-draws the global.
   */
  const modalState = modal;   // subscribe with $modalState
  const reconArg = $derived.by(() => {
    if ($activeStage !== 'fit') return null;
    const m = $modalState;
    if (m.setId === null || !m.local) return null;
    return {
      setId: m.setId, chIn: m.chIn, nChannels: m.nChannels,
      // Local overlay honours its own visibility toggle (round-4 item 9).
      local: m.showLocal ? m.local : undefined,
      global: undefined,        // global recon is the pseudo-set now
      showGlobal: false,
    };
  });

  /** Single-pane model for the active view (magnitude pane when Bode). */
  const model = $derived<PlotModel>(
    buildPlotModel({
      view, sets: setArrays, visible, freqMode, tfPlotType: plotType,
      coherence, coherenceAuto, freqRange: $sharedFreqRange, range, xScale, yScale,
      nyquistRange, recon: reconArg,
    }),
  );

  /**
   * Bode's second (phase) pane — only assembled when Bode is active. It shares
   * the magnitude pane's frequency x (`range.x`) but takes its OWN y from the
   * phase slice (`phaseRange`, default ±180° lock) so a magnitude-pane zoom
   * never distorts the phase axis (round-5 item 5).
   */
  const phaseModel = $derived<PlotModel>(
    bode
      ? buildPlotModel({
          view, sets: setArrays, visible, tfPlotType: 'phase',
          coherence: false, freqRange: $sharedFreqRange,
          range: { x: range.x, y: phaseRange.y }, xScale,
        })
      : model,
  );

  /**
   * Full-extent magnitude model for the Nyquist frequency brush (round-5 item
   * 4): the |H|(f) lines over the WHOLE frequency axis (no window, no committed
   * range), reusing the TF-mag builder so the column remap + cal ratio match
   * the plot. The brush renders these decimated + a draggable band = the
   * committed freq window.
   */
  const nyquistMagModel = $derived<PlotModel | null>(
    nyquist
      ? buildPlotModel({
          view: 'tf', sets: setArrays, visible, tfPlotType: 'mag',
          coherence: false, freqRange: null, range: { x: null, y: null }, xScale, yScale: 'log',
        })
      : null,
  );
  /** Full frequency extent spanned by the Nyquist brush strip. */
  const freqExtent = $derived<[number, number] | undefined>(
    nyquistMagModel && nyquistMagModel.lines.length > 0
      ? dataExtent(nyquistMagModel.lines, 'x', 'any')
      : undefined,
  );
  /** The band the brush highlights: the committed window, or the full extent. */
  const brushBand = $derived<[number, number] | undefined>(
    freqExtent ? ($sharedFreqRange ?? freqExtent) : undefined,
  );

  /** Extent of the currently visible lines (for the zoom toolbar's Auto X/Y). */
  const extent = $derived({
    x: dataExtent(model.lines, 'x', 'any'),
    y: dataExtent(model.lines, 'y', 'left'),
  });

  const hasData = $derived(setArrays.length > 0);

  /**
   * Flip the `fitEngine` capability once a TF result first exists (Task A1;
   * mirrors how `acquire.init` flips `liveSource`). The Fit stage stays
   * greyed until there is a transfer function to fit; it then latches on
   * (like liveSource) — a TF is the only prerequisite. `setArrays` is
   * derived from the decoded store, so this re-runs as results land.
   */
  const anyTf = $derived(setArrays.some((s) => s.tf));
  $effect(() => {
    if (anyTf) capabilities.update((c) => (c.fitEngine ? c : { ...c, fitEngine: true }));
  });

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
   * The sonogram image of the SET the analysis target names (its setId;
   * 'all' shows the first working set), so the heat layer tracks the
   * dataset dropdown rather than blindly showing whichever set was
   * computed first.
   */
  const sono = $derived.by(() => {
    const setId = $analysisTarget === 'all' ? actions.workingSets()[0]?.setId : $analysisTarget;
    const chosen = setId !== undefined ? $derivedStore[setId]?.sono : undefined;
    // Fall back to any computed sonogram so a stale target still shows something.
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
  <Header
    summary={hasData ? `${setArrays.length} set${setArrays.length === 1 ? '' : 's'}` : 'no data'}
    {workdirName}
    {onload}
    {onsave}
    onsavefigure={() => activeStage.set('export')}
    canSaveFigure={hasData}
    {onpickdir}
  />
  <Ribbon {viewState} {narrow} />
  <ContextCard
    {narrow}
    {viewState}
    {selection}
    {actions}
    {analysisSettings}
    {acquire}
    {monitor}
    {modal}
    {getSvg}
    {workdir}
    {onsave}
    {toasts}
    {hasData}
    bind:autosaveEnabled
  />

  <main class="main">
    {#if narrow}
      <NarrowRail {selection} {modal} {monitor} {channelSeries} onDeleteFit={actions.clearFit} />
    {:else}
      <aside class="tray" data-testid="tray">
        <div class="tray-scroll">
          <!-- Calibration handlers passed explicitly (they take precedence
               over the calibrationController fallback bridge inside Tray). -->
          <Tray {selection} {modal} channelData={channelSeries}
            getCalibration={actions.getCalibration}
            applyCalibration={actions.setCalFactors}
            onDeleteFit={actions.clearFit} />
        </div>
        <MiniMonitor {monitor} />
      </aside>
    {/if}

    <section class="plot" aria-label="plot">
      {#if $activeStage === 'live'}
        <div class="plot-host">
          <LiveScope {monitor} />
        </div>
      {:else if !hasData}
        <div class="empty-state">
          <p class="es-title">No data</p>
          <p class="es-sub">Load Data to begin</p>
        </div>
      {:else if view === 'sono'}
        <div class="plot-host">
          <canvas bind:this={sonoCanvas} data-testid="sono-canvas" class="sono-heat"></canvas>
          <PlotSurface bind:this={plotRef} model={sonoAxisModel} {viewState} overlay />
          <ZoomToolbar {viewState} dataExtent={extent} bind:mode />
        </div>
      {:else if nyquist}
        <!-- Nyquist (round-5 item 4): a frequency-band brush over the square
             Real/Imag locus. The brush scrubs the shared committed freq window;
             the toolbar's x/y become Real/Imag with a linked freq group. -->
        <div class="plot-host nyquist">
          {#if freqExtent && brushBand && nyquistMagModel}
            <NyquistBrush
              lines={nyquistMagModel.lines}
              fullExtent={freqExtent}
              band={brushBand}
              {xScale}
              onchange={(lo, hi) => viewState.setRange('tf', { x: [lo, hi], y: range.y })}
              onfull={() => { if (freqExtent) viewState.setRange('tf', { x: [freqExtent[0], freqExtent[1]], y: range.y }); }}
            />
          {/if}
          <div class="nyq-plot">
            <PlotSurface bind:this={plotRef} {model} {mode} {viewState} />
            <ZoomToolbar {viewState} dataExtent={extent} bind:mode nyquist {freqExtent} />
            <Legend {selection} {viewState} entriesOverride={legendOverride} />
            {#if $activeStage === 'fit'}<FitChip {modal} {actions} />{/if}
          </div>
        </div>
      {:else if bode}
        <div class="plot-host bode">
          <div class="bode-pane">
            <PlotSurface bind:this={plotRef} {model} {mode} {viewState} />
            <ZoomToolbar {viewState} dataExtent={extent} bind:mode {showXScale} {showYScale}
              phaseControl coherenceControl={!!model.y2Range} />
            <Legend {selection} {viewState} entriesOverride={legendOverride} />
          </div>
          <div class="bode-pane">
            <!-- Phase pane: shares x, owns its y. Route gestures to phaseRange
                 so a phase box-zoom never distorts the magnitude pane (item 5). -->
            <PlotSurface model={phaseModel} {mode} {viewState}
              onCommit={(r) => viewState.setBodePhaseRange(r.x, r.y)}
              onAutoFit={() => viewState.setPhaseRange({ x: null, y: null })} />
          </div>
        </div>
      {:else}
        <div class="plot-host">
          <PlotSurface bind:this={plotRef} {model} {mode} {viewState} />
          <ZoomToolbar {viewState} dataExtent={extent} bind:mode {showXScale} {showYScale}
            coherenceControl={!!model.y2Range} />
          <Legend {selection} {viewState} entriesOverride={legendOverride} />
          {#if $activeStage === 'fit'}<FitChip {modal} {actions} />{/if}
        </div>
      {/if}
      {#if $computeErrors[activeErrorKind]}
        <div class="plot-err" role="alert">Compute failed: {$computeErrors[activeErrorKind]}</div>
      {/if}
    </section>
  </main>

  <ToastHost {toasts} />
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
    flex-direction: column;
    min-height: 0;
    background: var(--surface);
    border-right: 1px solid var(--border);
  }
  /* The tray body scrolls; the MiniMonitor is pinned to the tray foot
     (flex:0 0 auto) so it stays visible on every stage. */
  .tray-scroll {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
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
  /* Nyquist: the brush strip + the square plot stack; each carries its own
     surface/border, so the outer host is a transparent column. */
  .plot-host.nyquist {
    display: flex;
    flex-direction: column;
    background: transparent;
    border: none;
    box-shadow: none;
    overflow: visible;
  }
  .nyq-plot {
    position: relative;
    flex: 1;
    min-height: 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
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
    /* Align to PlotSurface's inner data rect (margins L58/T16/R18/B42).
       A <canvas> is a REPLACED element, so `width/height:auto` resolves to
       its intrinsic buffer size (nt×nf, e.g. 38×257) instead of stretching
       to the L/T/R/B inset box — leaving a tiny sliver. Size it explicitly to
       the data rect so the buffer scales up to fill it. */
    left: 58px;
    top: 16px;
    width: calc(100% - 58px - 18px);
    height: calc(100% - 16px - 42px);
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
    color: var(--danger);
    padding: 2px 4px;
  }
</style>
