<script lang="ts">
  /**
   * Bench header (design spec §1; visuals ported from
   * dev/mockups/round2-bench.html `.app-header`). The `<header>` element
   * is the page's banner landmark (implicit `role="banner"`).
   *
   * Left: the product mark ("pydvma" + "web logger") and a summary
   * chip showing the current acquisition settings (`fs · N sets`).
   * Right: prominent Load Data (blue-outline) + Save Dataset (green)
   * actions, which invoke the `onload` / `onsave` callbacks — wired to
   * real handlers in Task 13; here they just emit.
   *
   * The flex slot between the mark and the actions holds the working-dir
   * chip (Task 13): it shows the chosen folder's name (File System Access
   * API) or "Downloads" in the download/upload fallback, and clicking it
   * fires `onpickdir` to (re)pick a folder. The live level meters / CLIP
   * indicator (Plan 2) will share this slot later — left as an empty
   * placeholder for now (no fake meters or data).
   */
  let {
    summary = 'no data',
    workdirName = 'Downloads',
    onload = () => {},
    onsave = () => {},
    onsavefigure = () => {},
    onpickdir = () => {},
    canSaveFigure = false,
  }: {
    /** Summary-chip text, e.g. "44.1 kHz · 2 sets"; "no data" when empty. */
    summary?: string;
    /** Working-directory chip label: folder name, or "Downloads" (fallback). */
    workdirName?: string;
    /** Fired by the Load Data button (App wires the load pipeline). */
    onload?: () => void;
    /** Fired by the Save Dataset button (App wires the save pipeline). */
    onsave?: () => void;
    /** Fired by Save Figure — opens the export flow for the ACTIVE view. */
    onsavefigure?: () => void;
    /** Fired by the working-dir chip to (re)pick a folder. */
    onpickdir?: () => void;
    /** Enables Save Figure (a dataset is loaded, so there's a plot). */
    canSaveFigure?: boolean;
  } = $props();

  // Light/dark theme toggle (round-5 item 11). The store is a module
  // singleton (persists the choice + follows the OS otherwise); the button
  // shows the theme you'd switch TO.
  import { theme, toggleTheme } from '../lib/stores/theme';
</script>

<header class="app-header">
  <div class="brand">pydvma<small>web logger</small></div>
  <button
    class="chipbtn"
    title="Current acquisition settings — editing arrives in Setup (Plan 2)"
  >{summary}</button>

  <!-- Working-directory chip: click to pick a folder (or download fallback). -->
  <button
    class="chipbtn dir"
    data-testid="workdir-chip"
    title="Working folder — where Save Dataset writes and autosave persists. Click to choose."
    onclick={onpickdir}
  ><span class="dir-ico" aria-hidden="true">▾</span>{workdirName}</button>

  <!-- Reserved: level meters / CLIP indicator (Plan 2). -->
  <div class="hdr-slot" aria-hidden="true"></div>

  <div class="hdr-right">
    <button
      class="theme-toggle"
      data-testid="theme-toggle"
      title={$theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      aria-label={$theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      aria-pressed={$theme === 'dark'}
      onclick={toggleTheme}
    >{$theme === 'dark' ? '☀' : '☾'}</button>
    <button class="btn blue-o" title="Load a dataset (.dvma)" onclick={onload}>Load Data</button>
    <button
      class="btn"
      title="Export the current plot as a figure (PNG / PDF)"
      disabled={!canSaveFigure}
      onclick={onsavefigure}
    >Save Figure</button>
    <button class="btn green" title="Save everything to a .dvma dataset" onclick={onsave}>Save Dataset</button>
  </div>
</header>

<style>
  .app-header {
    height: 52px;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 16px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }
  .brand {
    font-weight: 700;
    font-size: 15.5px;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  .brand small {
    font-weight: 500;
    color: var(--muted);
    font-size: 11.5px;
    margin-left: 7px;
  }
  .chipbtn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 26px;
    max-width: 250px;
    padding: 0 10px;
    border-radius: 13px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    font: 12px var(--font-mono);
    color: var(--text);
    cursor: pointer;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chipbtn:hover {
    border-color: var(--border-strong);
    background: var(--control-bg);
  }
  .chipbtn.dir {
    font: 12px var(--font-mono);
    max-width: 200px;
  }
  .dir-ico {
    font-size: 9px;
    color: var(--muted);
  }
  /* Reserved flex slot — grows to push actions right until Plan 2/Task 13 fill it. */
  .hdr-slot {
    flex: 1 1 auto;
    min-width: 0;
  }
  .hdr-right {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }
  /* Compact sun/moon theme toggle (round-5 item 11). */
  .theme-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 28px;
    border-radius: 7px;
    border: 1px solid var(--border);
    background: var(--control-bg);
    color: var(--muted);
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
    flex: 0 0 auto;
  }
  .theme-toggle:hover {
    border-color: var(--border-strong);
    background: var(--hover-bg);
    color: var(--text);
  }
  .theme-toggle:active {
    transform: translateY(1px);
  }
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 11px;
    border-radius: 7px;
    border: 1px solid var(--border);
    background: var(--control-bg);
    color: var(--text);
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    font-family: inherit;
  }
  .btn:hover {
    border-color: var(--border-strong);
    background: var(--hover-bg);
  }
  .btn:active {
    transform: translateY(1px);
  }
  .btn:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .btn:disabled:hover {
    border-color: var(--border);
    background: var(--control-bg);
  }
  .btn.blue-o {
    color: var(--blue);
    border-color: var(--blue-border);
    font-weight: 600;
  }
  .btn.blue-o:hover {
    background: var(--blue-soft);
  }
  .btn.green {
    background: var(--green);
    border-color: var(--green);
    color: #fff;
    font-weight: 600;
    height: 30px;
    padding: 0 15px;
  }
  .btn.green:hover {
    background: var(--green-hover);
  }

  @media (max-width: 1000px) {
    .app-header {
      gap: 8px;
    }
    .chipbtn {
      max-width: 150px;
    }
  }
</style>
