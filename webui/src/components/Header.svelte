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
   * The flex slot between the mark and the actions is RESERVED for the
   * live level meters / CLIP indicator that arrive in Plan 2, and the
   * autosave + working-dir chips that arrive in Task 13. They are left
   * as empty placeholders on purpose — no fake meters or data.
   */
  let {
    summary = 'no data',
    onload = () => {},
    onsave = () => {},
  }: {
    /** Summary-chip text, e.g. "44.1 kHz · 2 sets"; "no data" when empty. */
    summary?: string;
    /** Fired by the Load Data button (real handler wired in Task 13). */
    onload?: () => void;
    /** Fired by the Save Dataset button (real handler wired in Task 13). */
    onsave?: () => void;
  } = $props();
</script>

<header class="app-header">
  <div class="brand">pydvma<small>web logger</small></div>
  <button
    class="chipbtn"
    title="Current acquisition settings — editing arrives in Setup (Plan 2)"
  >{summary}</button>

  <!-- Reserved: level meters / CLIP (Plan 2), autosave + working-dir chips (Task 13). -->
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
