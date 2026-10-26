<script lang="ts">
  /**
   * The served app's file dialog: Save, Load and the working-folder pill.
   *
   * Only used when the app is served by `pydvma-serve` / `dvma.launch` and
   * the server offers its working folder (`filesAvailable()`), so the dialog
   * browses the SERVING MACHINE's disk through the engine's `files_list` op.
   * Three modes:
   *
   *   - **save**: a file name, saved in the working folder. **Choose
   *     location…** opens a folder navigator to save this one file somewhere
   *     else; the working folder itself does not move (lab feedback,
   *     2026-10: choosing a location must not change the default).
   *   - **open**: the navigator, opening in the working folder; pick a file
   *     to load. Browsing does not move the working folder either.
   *   - **folder**: the navigator, to choose a new working folder (the
   *     header pill). This is the only mode that moves it, via the caller.
   *
   * DUMB about the disk: it lists through `list` and reports the chosen path
   * (absolute) through `onconfirm`; writing, reading, replace confirmation
   * and moving the working folder belong to the caller (App / `serverDir`).
   */
  import { untrack } from 'svelte';
  import type { FolderListing } from '../lib/stores/engine';
  import { extensionOf, joinPath, withExtension } from '../lib/files/workdir';

  let {
    mode,
    title,
    workingDir,
    suggested = '',
    extensions = undefined,
    list,
    onconfirm,
    oncancel,
  }: {
    mode: 'save' | 'open' | 'folder';
    title: string;
    /** The working folder: where the dialog opens. */
    workingDir: { dir: string; name: string; sep: string };
    /** Save mode: the proposed file name (its extension is kept if dropped). */
    suggested?: string;
    /**
     * Save mode: the extensions a typed name may carry as it is (e.g.
     * ['.png', '.pdf'] for a figure, so `beam.pdf` stays `beam.pdf`); a name
     * with none of them gets the suggested name's extension. Default: just
     * the suggested name's own.
     */
    extensions?: string[];
    /** List a folder (absolute path; omitted = the working folder). */
    list: (dir?: string) => Promise<FolderListing>;
    /** The chosen absolute path: a file (save/open) or a folder (folder). */
    onconfirm: (path: string) => void;
    oncancel: () => void;
  } = $props();

  const sep = $derived(workingDir.sep || '/');
  const ext = $derived(extensionOf(suggested));

  // svelte-ignore state_referenced_locally
  let name = $state(suggested);
  // Save mode starts collapsed on the working folder; the other modes are
  // all about browsing, so they start open.
  // svelte-ignore state_referenced_locally
  let browsing = $state(mode !== 'save');
  let listing = $state<FolderListing | null>(null);
  let pathInput = $state('');
  let error = $state('');
  let loading = $state(false);
  let pathEl = $state<HTMLInputElement>();
  let selectedFile = $state<string | null>(null);

  /** The folder a save/open lands in: the browsed one, else the working folder. */
  const targetDir = $derived(browsing && listing ? listing.dir : workingDir.dir);
  const inWorkingDir = $derived(targetDir === workingDir.dir);

  const accepted = $derived(extensions ?? (ext ? [ext] : []));
  /** The accepted extension `n` already ends with ('' when none). */
  function typedExtension(n: string): string {
    return accepted.find((e) => n.toLowerCase().endsWith(e.toLowerCase())) ?? '';
  }
  /** Save: the file name as it will be written (extension restored). */
  const finalName = $derived(typedExtension(name.trim()) ? name.trim() : withExtension(name.trim(), ext));
  /** Save: whether that name is already a file in the target folder. */
  const willReplace = $derived(
    mode === 'save' && !!listing && listing.dir === targetDir
      && listing.files.some((f) => f.toLowerCase() === finalName.toLowerCase()),
  );

  async function go(dir?: string): Promise<void> {
    loading = true;
    try {
      const l = await list(dir);
      listing = l;
      pathInput = l.dir;
      error = '';
      selectedFile = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      if (listing) pathInput = listing.dir;
    } finally {
      loading = false;
    }
  }

  // Show the END of a long path (the folder you are in), not its root —
  // whenever the folder changes, and when the box first appears (save mode
  // mounts it only on "Choose location…").
  $effect(() => {
    void listing;
    const el = pathEl;
    if (el) requestAnimationFrame(() => { el.scrollLeft = el.scrollWidth; });
  });

  // Open on the working folder (save mode too, so a clash can be flagged
  // before the server is asked).
  $effect(() => { void go(workingDir.dir); });

  function openFolder(f: string): void {
    if (listing) void go(joinPath(listing.dir, f, sep));
  }

  function pickFile(f: string): void {
    if (mode === 'save') name = f;
    else selectedFile = f;
  }

  const canConfirm = $derived(
    mode === 'save' ? finalName.length > typedExtension(finalName).length
      : mode === 'open' ? !!selectedFile && !!listing
        : !!listing,
  );

  function confirm(): void {
    if (!canConfirm) return;
    if (mode === 'save') onconfirm(joinPath(targetDir, finalName, sep));
    else if (mode === 'open') onconfirm(joinPath(listing!.dir, selectedFile!, sep));
    else onconfirm(listing!.dir);
  }

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') oncancel();
  }

  const confirmLabel = $derived(mode === 'save' ? 'Save' : mode === 'open' ? 'Load' : 'Use this folder');

  let nameInput = $state<HTMLInputElement>();
  // Focus the name and select its stem ONCE, when the box appears, so typing
  // replaces the proposed name but keeps the extension. `name` is read
  // untracked: tracked, every keystroke re-ran this and re-selected what was
  // typed, so each letter replaced the one before (lab report, 2026-10-26).
  $effect(() => {
    if (mode !== 'save' || !nameInput) return;
    const el = nameInput;
    untrack(() => {
      el.focus();
      el.setSelectionRange(0, name.length - typedExtension(name).length);
    });
  });
</script>

<svelte:window on:keydown={onKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  class="overlay"
  data-testid="file-dialog"
  data-mode={mode}
  role="dialog"
  aria-modal="true"
  aria-label={title}
  tabindex="-1"
  onclick={(e) => { if (e.target === e.currentTarget) oncancel(); }}
>
  <div class="modal">
    <div class="modal-title">{title}</div>

    {#if mode === 'save'}
      <label class="row">
        <span class="lab">Name</span>
        <input
          class="txt"
          type="text"
          bind:this={nameInput}
          bind:value={name}
          data-testid="file-dialog-name"
          aria-label="file name"
          onkeydown={(e) => { if (e.key === 'Enter') confirm(); }}
        />
      </label>
      <div class="row">
        <span class="lab">In</span>
        <!-- RTL box so a long path is cut at its START; the LTR inner span keeps
             the path itself in order (a bare RTL box moves a leading "/" to the end). -->
        <span class="where" title={targetDir}><span dir="ltr" data-testid="file-dialog-target">{targetDir}</span></span>
        {#if inWorkingDir}<span class="tag">working folder</span>{/if}
        {#if !browsing}
          <button class="btn sm" data-testid="file-dialog-choose" onclick={() => (browsing = true)}>
            Choose location…
          </button>
        {/if}
      </div>
    {:else if mode === 'folder'}
      <p class="note">
        Save and Load open here. Currently <span class="mono">{workingDir.dir}</span>.
      </p>
    {/if}

    {#if browsing}
      <div class="nav" data-testid="file-dialog-nav">
        <div class="navbar">
          <button class="btn sm" aria-label="parent folder" title="Parent folder"
            data-testid="file-dialog-up"
            disabled={!listing?.parent || loading}
            onclick={() => listing?.parent && go(listing.parent)}>↑</button>
          <input
            class="txt path"
            type="text"
            bind:value={pathInput}
            bind:this={pathEl}
            aria-label="folder path"
            data-testid="file-dialog-path"
            onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void go(pathInput); } }}
          />
          <button class="btn sm" onclick={() => go(pathInput)} disabled={loading}>Go</button>
          <button class="btn sm" title={workingDir.dir} data-testid="file-dialog-home"
            disabled={loading || listing?.dir === workingDir.dir}
            onclick={() => go(workingDir.dir)}>Working folder</button>
        </div>
        <ul class="entries" data-testid="file-dialog-entries">
          {#if listing}
            {#each listing.folders as f (f)}
              <li>
                <button class="entry folder" data-testid="file-dialog-folder"
                  onclick={() => openFolder(f)}><span class="ico" aria-hidden="true">▸</span>{f}</button>
              </li>
            {/each}
            {#each listing.files as f (f)}
              <li>
                <button
                  class="entry file"
                  class:sel={mode === 'open' ? selectedFile === f : name === f}
                  class:dim={mode === 'folder'}
                  disabled={mode === 'folder'}
                  data-testid="file-dialog-file"
                  onclick={() => pickFile(f)}
                  ondblclick={() => { pickFile(f); confirm(); }}
                ><span class="ico" aria-hidden="true"></span>{f}</button>
              </li>
            {/each}
            {#if listing.folders.length === 0 && listing.files.length === 0}
              <li class="empty">{mode === 'open' ? 'No data files here.' : 'Empty folder.'}</li>
            {/if}
          {/if}
        </ul>
      </div>
    {/if}

    {#if error}
      <p class="err" role="alert" data-testid="file-dialog-error">{error}</p>
    {:else if willReplace}
      <p class="warn" data-testid="file-dialog-replace">{finalName} is already there — saving replaces it.</p>
    {/if}

    <div class="mrow end">
      <button class="btn" data-testid="file-dialog-cancel" onclick={oncancel}>Cancel</button>
      <button class="btn indigo" data-testid="file-dialog-confirm" disabled={!canConfirm}
        onclick={confirm}>{confirmLabel}</button>
    </div>
  </div>
</div>

<style>
  /* Same overlay/modal surface as CalibrateDialog (the house modal). */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 330;
    background: var(--scrim);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }
  .modal {
    width: min(560px, 100%);
    max-height: calc(100vh - 32px);
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-radius: 12px;
    padding: 16px 18px 14px;
    box-shadow: 0 24px 70px rgba(16, 24, 40, 0.35);
  }
  .modal-title {
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 12px;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    min-width: 0;
  }
  .lab {
    flex: 0 0 40px;
    font-size: 12px;
    color: var(--muted);
  }
  .txt {
    flex: 1 1 auto;
    min-width: 0;
    height: 28px;
    border: 1px solid var(--border);
    border-radius: 7px;
    padding: 0 8px;
    background: var(--control-bg);
    color: var(--text);
    font: 12.5px var(--font-body, system-ui, sans-serif);
  }
  .txt:focus {
    outline: none;
    border-color: var(--accent-soft-border);
  }
  .txt.path {
    font-family: var(--font-mono);
    font-size: 11.5px;
  }
  .where {
    flex: 1 1 auto;
    min-width: 0;
    font: 11.5px var(--font-mono);
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    direction: rtl;          /* keep the END of a long path visible */
    text-align: left;
  }
  .tag {
    flex: 0 0 auto;
    font-size: 10.5px;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 1px 7px;
  }
  .note {
    font-size: 12px;
    color: var(--muted);
    margin: 0 0 10px;
    overflow-wrap: anywhere;
  }
  .mono {
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--text);
  }
  .nav {
    display: flex;
    flex-direction: column;
    min-height: 0;
    flex: 1 1 auto;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px;
    margin-bottom: 6px;
  }
  .navbar {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }
  .entries {
    list-style: none;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    min-height: 120px;
    max-height: 280px;
  }
  .entry {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    border: 0;
    background: transparent;
    color: var(--text);
    font: 12.5px var(--font-body, system-ui, sans-serif);
    text-align: left;
    padding: 4px 6px;
    border-radius: 5px;
    cursor: pointer;
  }
  .entry:hover:not(:disabled) {
    background: var(--hover-bg);
  }
  .entry.sel {
    background: var(--accent-soft);
    color: var(--indigo);
  }
  .entry.dim {
    color: var(--muted);
    cursor: default;
  }
  .ico {
    flex: 0 0 12px;
    color: var(--muted);
    font-size: 10px;
  }
  .empty {
    font-size: 12px;
    color: var(--muted);
    padding: 6px;
  }
  .err, .warn {
    font-size: 12px;
    margin: 4px 0 0;
    overflow-wrap: anywhere;
  }
  .err { color: var(--danger); }
  .warn { color: var(--muted); }
  .mrow {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .mrow.end {
    justify-content: flex-end;
    margin-top: 12px;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 28px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--control-bg);
    color: var(--text);
    font-family: inherit;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn.sm {
    height: 26px;
    padding: 0 9px;
    font-size: 12px;
  }
  .btn:hover:not(:disabled) {
    border-color: var(--border-strong);
    background: var(--hover-bg);
  }
  .btn:disabled {
    opacity: 0.45;
    cursor: default;
  }
  .btn.indigo {
    background: var(--indigo, #4f46e5);
    border-color: var(--indigo, #4f46e5);
    color: #fff;
    font-weight: 600;
  }
  .btn.indigo:hover:not(:disabled) {
    background: var(--indigo-hover);
  }
</style>
