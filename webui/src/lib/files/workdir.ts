// workdir.ts — the "working directory" abstraction for load/save.
//
// A WorkDir is where Save Dataset writes and Load Data reads. Three kinds:
//
//   - 'server': the WORKING FOLDER of the pydvma-serve / dvma.launch server
//     the app is served by (pydvma.savefolder) — a real folder on the serving
//     machine, by default the one the notebook (or the CLI) was started in.
//     save() and open() go through the app's file dialog (`ServerDirDeps`),
//     which opens in the working folder and can browse elsewhere for one
//     file without moving it; the header pill moves it. Used whenever the
//     served engine offers it, ahead of the two browser kinds below.
//
//   - 'fsaccess': a real on-disk folder, via the File System Access API
//     (showDirectoryPicker). The granted directory HANDLE is persisted in
//     IndexedDB so the same folder is reused across reloads (after a
//     permission re-grant) — saves land silently in the chosen folder and
//     autosave can write `autosave.dvma` there for a durable restore.
//
//   - 'download': the universal fallback for browsers/contexts without the
//     File System Access API (Firefox, Safari, and — crucially for the e2e
//     — Playwright's Chromium, which does not expose showDirectoryPicker
//     without special flags). save() triggers an <a download>; open()
//     spins up a hidden <input type=file>. There is no persistent folder,
//     so the header chip reads "Downloads".
//
// Everything here that touches showDirectoryPicker / showOpenFilePicker is
// browser-only and cannot run under node/vitest — the FALLBACK branch is
// what the Playwright e2e exercises. sniff/autosave carry the unit tests.
import { get as idbGet, set as idbSet } from 'idb-keyval';

/** IndexedDB key under which the granted directory handle is persisted. */
const HANDLE_KEY = 'pydvma:workdir-handle';

/**
 * A place to read datasets from and write datasets to. `kind` tells the UI
 * whether a real folder is set ('fsaccess', chip shows its name) or we are
 * in download/upload mode ('download', chip shows "Downloads"). `save`
 * writes `bytes` under `name`; `open` returns the bytes + name the user
 * picked, or null if they cancelled.
 */
export interface WorkDir {
  kind: 'fsaccess' | 'download' | 'server';
  /** Display name — the folder name, or 'Downloads' in fallback mode. */
  name: string;
  /** The full folder path, when known ('server' only) — the pill's tooltip. */
  path?: string;
  /**
   * Persist `bytes` as `name` (writes to the folder, or downloads it).
   * Resolves where it went (a file name, or a full path for 'server'), or
   * null when the user cancelled the save dialog or declined a replace.
   */
  save(name: string, bytes: Uint8Array): Promise<string | null>;
  /** Let the user pick a file to load; resolves its bytes + name, or null. */
  open(): Promise<{ bytes: Uint8Array; name: string } | null>;
}

/**
 * Whether the File System Access API is available in this context. When
 * false the app uses `fallbackDir()` (download/upload) throughout. Guards
 * against SSR/node by checking `window` first.
 */
export function hasFsAccess(): boolean {
  return typeof window !== 'undefined' && 'showDirectoryPicker' in window;
}

/**
 * Prompt the user to choose a working folder. Uses showDirectoryPicker when
 * available (persisting the granted handle in IndexedDB so `restoreWorkDir`
 * can reuse it next session) and returns an 'fsaccess' WorkDir; otherwise —
 * or if the user cancels the picker — falls back to the download/upload
 * WorkDir. Never rejects on user-cancel: a cancelled picker returns the
 * fallback dir so the caller always gets a usable WorkDir.
 */
export async function pickWorkDir(): Promise<WorkDir> {
  if (!hasFsAccess()) return fallbackDir();
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const handle: FileSystemDirectoryHandle = await (window as any).showDirectoryPicker({
      mode: 'readwrite',
    });
    await idbSet(HANDLE_KEY, handle);
    return wrap(handle);
  } catch {
    // AbortError (user cancelled) or any picker failure → fall back rather
    // than leave the app without a working directory.
    return fallbackDir();
  }
}

/**
 * Re-establish last session's working folder, if any. Reads the persisted
 * directory handle from IndexedDB and, if the browser still grants (or the
 * user re-grants) read/write permission, wraps it as an 'fsaccess' WorkDir.
 * Returns null when there is no saved handle, permission is denied, or the
 * API is unavailable — the caller then defaults to `fallbackDir()`. Called
 * once on boot so a returning user keeps their folder without re-picking.
 */
export async function restoreWorkDir(): Promise<WorkDir | null> {
  if (!hasFsAccess()) return null;
  try {
    const handle = (await idbGet(HANDLE_KEY)) as FileSystemDirectoryHandle | undefined;
    if (!handle) return null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const h = handle as any;
    const opts = { mode: 'readwrite' as const };
    let perm: string = await h.queryPermission?.(opts);
    if (perm !== 'granted') perm = await h.requestPermission?.(opts);
    if (perm !== 'granted') return null;
    return wrap(handle);
  } catch {
    return null;
  }
}

/**
 * Wrap a granted directory handle as an 'fsaccess' WorkDir. save() creates
 * (or truncates) `name` in the folder and streams `bytes` to it; open()
 * pops a showOpenFilePicker scoped to .dvma/.npy/.mat and returns the
 * chosen file's bytes, or null if cancelled.
 */
export function wrap(handle: FileSystemDirectoryHandle): WorkDir {
  return {
    kind: 'fsaccess',
    name: handle.name,
    async save(name: string, bytes: Uint8Array): Promise<string | null> {
      const fileHandle = await handle.getFileHandle(name, { create: true });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const writable = await (fileHandle as any).createWritable();
      // createWritable() opens against a temp copy that only replaces the real
      // file on close(). If write/close throws mid-way we MUST abort() —
      // otherwise the partial write can still be committed, silently replacing
      // a good file with a truncated one. Matters most on the autosave path,
      // where the failure is only console.warn'd. Copy into a fresh
      // ArrayBuffer-backed view first so we never hand the writer a
      // SharedArrayBuffer-backed slice.
      try {
        await writable.write(bytes.slice());
        await writable.close();
        return name;
      } catch (e) {
        try {
          await writable.abort();
        } catch {
          /* abort is best-effort; surface the original error below */
        }
        throw e;
      }
    },
    async open(): Promise<{ bytes: Uint8Array; name: string } | null> {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const [fileHandle] = await (window as any).showOpenFilePicker({
          types: [
            {
              description: 'pydvma datasets',
              accept: { 'application/octet-stream': ['.dvma', '.npy', '.mat', '.csv'] },
            },
          ],
          multiple: false,
        });
        const file: File = await fileHandle.getFile();
        return { bytes: new Uint8Array(await file.arrayBuffer()), name: file.name };
      } catch {
        return null; // user cancelled the picker
      }
    },
  };
}

/**
 * The download/upload WorkDir — the universal fallback when the File System
 * Access API is unavailable. save() triggers an anchor download of `bytes`
 * (the browser routes it to the user's Downloads folder / save dialog);
 * open() creates a hidden `<input type=file>`, clicks it, and resolves with
 * the picked file's bytes. Because there is no durable folder handle, its
 * `name` is the literal "Downloads" and autosave persists to IndexedDB
 * instead of writing a file here.
 */
export function fallbackDir(): WorkDir {
  return {
    kind: 'download',
    name: 'Downloads',
    async save(name: string, bytes: Uint8Array): Promise<string | null> {
      const blob = new Blob([bytes.slice()], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      // Revoke on the next tick so the click's navigation has fired.
      setTimeout(() => URL.revokeObjectURL(url), 0);
      return name;
    },
    open(): Promise<{ bytes: Uint8Array; name: string } | null> {
      return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.dvma,.npy,.mat,.csv';
        // Exposed for the e2e: Playwright targets this input via a testid
        // (or the filechooser event) to drive the fallback load path.
        input.setAttribute('data-testid', 'file-input');
        input.style.position = 'fixed';
        input.style.left = '-9999px';
        let settled = false;
        const done = (v: { bytes: Uint8Array; name: string } | null) => {
          if (settled) return;
          settled = true;
          input.remove();
          resolve(v);
        };
        input.addEventListener('change', async () => {
          const file = input.files?.[0];
          if (!file) return done(null);
          done({ bytes: new Uint8Array(await file.arrayBuffer()), name: file.name });
        });
        // If the dialog is dismissed there is no reliable 'cancel' event in
        // all browsers; the 'cancel' event fires in Chromium. Best-effort.
        input.addEventListener('cancel', () => done(null));
        document.body.appendChild(input);
        input.click();
      });
    },
  };
}

// ---- 'server': the served app's working folder ------------------------------

/** Whether `p` is an absolute path on Windows (`C:\`, `\\server`) or POSIX (`/`). */
export function isAbsolutePath(p: string): boolean {
  return /^([A-Za-z]:[\\/]|[\\/])/.test(p);
}

/**
 * `name` placed in folder `dir`: `name` itself when it is already an
 * absolute path, else `dir` + `sep` + `name` (no doubled separator).
 */
export function joinPath(dir: string, name: string, sep: string): string {
  if (isAbsolutePath(name)) return name;
  const d = dir.endsWith('/') || dir.endsWith('\\') ? dir.slice(0, -1) : dir;
  return d + sep + name;
}

/** `name` with extension `ext` (e.g. '.dvma') appended unless it already ends so. */
export function withExtension(name: string, ext: string): string {
  if (!ext) return name;
  return name.toLowerCase().endsWith(ext.toLowerCase()) ? name : name + ext;
}

/** The extension of a file name ('.dvma'), or '' when it has none. */
export function extensionOf(name: string): string {
  const m = /\.[A-Za-z0-9]+$/.exec(name);
  return m ? m[0] : '';
}

/** What a 'server' WorkDir needs from the app (the engine ops and its dialogs). */
export interface ServerDirDeps {
  /** The working folder (`files_info`). */
  info: { dir: string; name: string; sep: string };
  /** `files_save`: never replaces unless `overwrite`. */
  save(path: string, bytes: Uint8Array, overwrite: boolean): Promise<{ path: string; saved: boolean; exists: boolean }>;
  /** `files_read`. */
  read(path: string): Promise<{ name: string; bytes: Uint8Array }>;
  /** Open the Save dialog for `suggested`; resolves the chosen path, or null. */
  askSave(suggested: string): Promise<string | null>;
  /** Open the Load dialog; resolves the chosen file's path, or null. */
  askOpen(): Promise<string | null>;
  /** Ask before replacing an existing file at `path`. */
  confirmReplace(path: string): boolean | Promise<boolean>;
}

/**
 * The served app's working folder as a WorkDir. `save` asks where (the Save
 * dialog, opening in the working folder) and refuses to replace a file
 * without asking; `open` asks which file (the Load dialog). Neither moves the
 * working folder — only the header pill does (`files_set_dir`).
 */
export function serverDir(deps: ServerDirDeps): WorkDir {
  return {
    kind: 'server',
    name: deps.info.name,
    path: deps.info.dir,
    async save(name: string, bytes: Uint8Array): Promise<string | null> {
      const target = await deps.askSave(name);
      if (!target) return null;
      let r = await deps.save(target, bytes, false);
      if (!r.saved && r.exists) {
        if (!(await deps.confirmReplace(r.path))) return null;
        r = await deps.save(target, bytes, true);
      }
      return r.path;
    },
    async open(): Promise<{ bytes: Uint8Array; name: string } | null> {
      const path = await deps.askOpen();
      if (!path) return null;
      const r = await deps.read(path);
      return { bytes: r.bytes, name: r.name };
    },
  };
}
