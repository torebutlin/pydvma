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
    onpickdir = () => {},
  }: {
    /** Summary-chip text, e.g. "44.1 kHz · 2 sets"; "no data" when empty. */
    summary?: string;
    /** Working-directory chip label: folder name, or "Downloads" (fallback). */
    workdirName?: string;
    /** Fired by the Load Data button (App wires the load pipeline). */
    onload?: () => void;
    /** Fired by the Save Dataset button (App wires the save pipeline). */
    onsave?: () => void;
    /** Fired by the working-dir chip to (re)pick a folder. */
    onpickdir?: () => void;
  } = $props();
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
    <button class="btn blue-o" title="Load a dataset (.dvma)" onclick={onload}>Load Data</button>
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
    background: #f8f9fb;
    font: 12px var(--font-mono);
    color: var(--text);
    cursor: pointer;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .chipbtn:hover {
    border-color: #c6cbd6;
    background: #fff;
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
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 11px;
    border-radius: 7px;
    border: 1px solid var(--border);
    background: #fff;
    color: var(--text);
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    font-family: inherit;
  }
  .btn:hover {
    border-color: #c6cbd6;
    background: #fafbfc;
  }
  .btn:active {
    transform: translateY(1px);
  }
  .btn.blue-o {
    color: #2563eb;
    border-color: #93c5fd;
    font-weight: 600;
  }
  .btn.blue-o:hover {
    background: #eff6ff;
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
    background: #15803d;
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
