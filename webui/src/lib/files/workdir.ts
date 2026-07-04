// workdir.ts — the "working directory" abstraction for load/save.
//
// A WorkDir is where Save Dataset writes and Load Data reads. Two kinds:
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
  kind: 'fsaccess' | 'download';
  /** Display name — the folder name, or 'Downloads' in fallback mode. */
  name: string;
  /** Persist `bytes` as `name` (writes to the folder, or downloads it). */
  save(name: string, bytes: Uint8Array): Promise<void>;
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
    async save(name: string, bytes: Uint8Array): Promise<void> {
      const fileHandle = await handle.getFileHandle(name, { create: true });
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const writable = await (fileHandle as any).createWritable();
      // Copy into a fresh ArrayBuffer-backed view so we never hand the
      // writer a SharedArrayBuffer-backed slice.
      await writable.write(bytes.slice());
      await writable.close();
    },
    async open(): Promise<{ bytes: Uint8Array; name: string } | null> {
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const [fileHandle] = await (window as any).showOpenFilePicker({
          types: [
            {
              description: 'pydvma datasets',
              accept: { 'application/octet-stream': ['.dvma', '.npy', '.mat'] },
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
    async save(name: string, bytes: Uint8Array): Promise<void> {
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
    },
    open(): Promise<{ bytes: Uint8Array; name: string } | null> {
      return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.dvma,.npy,.mat';
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
