// progress.ts — worker-side plumbing for mid-compute progress frames (P7).
//
// The engine protocol is strict request/response and pyodide runs SYNCHRONOUSLY
// inside the worker: while a compute op is executing, the worker cannot RECEIVE
// anything (no cancel message, and SharedArrayBuffer is out — GitHub Pages
// sends no COOP/COEP headers). It can, however, still POST. So a long CWT
// reports itself: pydvma calls a `progress_callback` once per wavelet scale,
// pydvma.engine forwards it to the hook installed here, and this poster
// stamps the frame with the ACTIVE call id and ships it to the main thread.
//
// Two jobs, both of which is why this lives in its own module rather than
// inline in engine.worker.ts (which imports pyodide and pyimports
// pydvma.engine from the installed wheel, and so cannot be loaded by the
// node test runner):
//   1. ARMING — the callback knows only (done, total); the id it belongs to is
//      worker state, set around each op. A frame that arrives while nothing is
//      armed is dropped, never mis-attributed to the previous call.
//   2. THROTTLING — a 5000-scale transform would otherwise post 5000 messages.
//      Frames are rate-limited to one per `intervalMs` (~10 Hz), except the
//      FIRST frame of a call (which carries the total, so the UI can go
//      determinate immediately) and the LAST (done === total), so a bar always
//      reaches its end rather than freezing at 96 %.

/** Throttle interval for progress frames — ~10 Hz, comfortably under a repaint. */
export const PROGRESS_THROTTLE_MS = 100;

/** Wire shape of a progress frame (worker -> main thread). */
export interface ProgressMessage {
  type: 'progress';
  /** The request id the frame belongs to (matches `{id}` of the pending call). */
  callId: number;
  done: number;
  total: number;
}

export interface ProgressPoster {
  /** Attribute subsequent frames to `callId` and reset the throttle. */
  arm(callId: number): void;
  /** Stop reporting (call settled) — later frames are dropped. */
  disarm(): void;
  /** The hook handed to pydvma.engine; safe to call from the compute hot loop. */
  postProgress(done: number, total: number): void;
}

/**
 * Create the progress poster. `post` is the raw message sink (the worker's
 * `postMessage`), `now` and `intervalMs` are injectable so the throttle is
 * testable without timers.
 */
export function createProgressPoster(
  post: (message: ProgressMessage) => void,
  now: () => number = () => Date.now(),
  intervalMs: number = PROGRESS_THROTTLE_MS,
): ProgressPoster {
  let callId: number | null = null;
  let lastAt = -Infinity;

  return {
    arm(id: number) {
      callId = id;
      lastAt = -Infinity;         // the first frame of a call always goes out
    },
    disarm() {
      callId = null;
    },
    postProgress(done: number, total: number) {
      if (callId === null) return;
      const t = now();
      // Always let the terminal frame through, so the bar completes.
      if (done < total && t - lastAt < intervalMs) return;
      lastAt = t;
      post({ type: 'progress', callId, done, total });
    },
  };
}
