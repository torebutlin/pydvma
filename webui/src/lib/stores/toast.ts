// toast.ts — a minimal bottom-right toast queue for the bench shell.
//
// Task 13 introduced the first user-facing transient messages (load
// errors, "restore last session?", save confirmations), so this is the
// shared, dependency-free toast store the shell renders through
// `ToastHost.svelte`. Toasts are either plain (auto-dismiss after a
// timeout) or ACTIONABLE (carry labelled buttons, e.g. Restore / Dismiss,
// and stay until the user acts or explicitly dismisses).
import { writable } from 'svelte/store';

/** One button on an actionable toast. `run` fires, then the toast closes. */
export interface ToastAction {
  label: string;
  run: () => void;
}

/** Severity → styling hook (border/accent colour in ToastHost). */
export type ToastLevel = 'info' | 'error' | 'success';

/** A live toast. `actions` present ⇒ it will not auto-dismiss. */
export interface Toast {
  id: number;
  message: string;
  level: ToastLevel;
  actions?: ToastAction[];
}

/** Options for `push`. `timeout` (ms) applies only to non-actionable toasts. */
export interface ToastOptions {
  level?: ToastLevel;
  actions?: ToastAction[];
  timeout?: number;
}

let nextId = 1;

/**
 * Create a toast store. `push` enqueues a toast and returns its id;
 * `dismiss` removes a toast by id. Info/success toasts auto-dismiss
 * after `timeout` ms (default 4000); toasts that carry actions pin open
 * until acted on, and **error toasts pin open until the user closes
 * them** (round-10, JW's feedback: an error vanished before he could
 * read or copy it) — pass an explicit `timeout` to make an error
 * transient. Actionable toasts self-dismiss after their action's `run`
 * completes.
 */
export function createToasts() {
  const toasts = writable<Toast[]>([]);

  function dismiss(id: number): void {
    toasts.update((list) => list.filter((t) => t.id !== id));
  }

  function push(message: string, opts: ToastOptions = {}): number {
    const id = nextId++;
    const level = opts.level ?? 'info';
    // Actions on the toast fire then close it (so Restore/Dismiss both end it).
    const actions = opts.actions?.map((a) => ({
      label: a.label,
      run: () => {
        try {
          a.run();
        } finally {
          dismiss(id);
        }
      },
    }));
    toasts.update((list) => [...list, { id, message, level, actions }]);
    if (!actions) {
      // Errors stay until dismissed via × (unless the caller passes an
      // explicit timeout) so they can be read and copied.
      const timeout = opts.timeout ?? (level === 'error' ? null : 4000);
      if (timeout !== null) setTimeout(() => dismiss(id), timeout);
    }
    return id;
  }

  return { toasts, push, dismiss };
}

export type Toasts = ReturnType<typeof createToasts>;
