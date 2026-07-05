/**
 * Acquisition store (Plan 2 — browser soundcard recording).
 *
 * Manages: device list, selected device, stream settings (fs, channels,
 * duration), recording lifecycle (idle → recording → done), and the
 * bridge from a completed Recording into a TimeData DvmaItem that the
 * actions pipeline can load into the dataset + tray.
 *
 * The store is created once at the app root and threaded through to the
 * SetupCard and AcquireCard components.
 */
import { writable, get } from 'svelte/store';
import {
  enumerateInputDevices,
  startRecording,
  type AudioInputDevice,
  type RecordConfig,
  type Recording,
  type RecordingHandle,
} from '../audio/source';
import type { DvmaDataset, DvmaItem } from '../model/dataset';
import { capabilities } from './stages';

// ---- types ----

export type AcquireStatus = 'idle' | 'recording' | 'done' | 'error';

export interface AcquireSettings {
  deviceId: string;     // '' = browser default
  sampleRate: number;
  channelCount: number;
  durationS: number;
}

export type AcquireStore = ReturnType<typeof createAcquireStore>;

// ---- defaults ----

const DEFAULT_SETTINGS: AcquireSettings = {
  deviceId: '',
  sampleRate: 44100,
  channelCount: 1,
  durationS: 2.0,
};

// ---- store factory ----

export function createAcquireStore() {
  const devices = writable<AudioInputDevice[]>([]);
  const settings = writable<AcquireSettings>({ ...DEFAULT_SETTINGS });
  const status = writable<AcquireStatus>('idle');
  const statusText = writable<string>('');
  const errorMsg = writable<string>('');
  const elapsed = writable<number>(0);

  let handle: RecordingHandle | null = null;
  let elapsedTimer: ReturnType<typeof setInterval> | null = null;
  /** The most recent recording result (consumed by the acquire → dataset bridge). */
  let lastRecording: Recording | null = null;

  /**
   * Refresh the device list.  Call after a user gesture to get real
   * labels (browsers hide labels until permission is granted).
   */
  async function refreshDevices(): Promise<void> {
    try {
      const list = await enumerateInputDevices();
      devices.set(list);
      // Flip the liveSource capability so Setup/Acquire tabs enable.
      if (list.length > 0) {
        capabilities.update((c) => ({ ...c, liveSource: true }));
      }
    } catch {
      // Silently degrade — devices stay empty, tabs stay disabled.
    }
  }

  /**
   * Probe for Web Audio support and kick-start device enumeration.
   * Called once at app boot.
   */
  async function init(): Promise<void> {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return;
    // Enable the liveSource gate immediately (even before enumeration
    // completes) so Setup/Acquire tabs are clickable.
    capabilities.update((c) => ({ ...c, liveSource: true }));
    await refreshDevices();
  }

  /** Start a recording with current settings. */
  async function record(): Promise<Recording> {
    const cfg = get(settings);
    status.set('recording');
    statusText.set(`Logging data for ${cfg.durationS.toFixed(1)} s…`);
    errorMsg.set('');
    elapsed.set(0);

    const rcfg: RecordConfig = {
      deviceId: cfg.deviceId || undefined,
      sampleRate: cfg.sampleRate,
      channelCount: cfg.channelCount,
      durationS: cfg.durationS,
    };

    handle = startRecording(rcfg);

    // Poll elapsed time for progress display.
    elapsedTimer = setInterval(() => {
      if (handle) elapsed.set(handle.elapsed());
    }, 100);

    try {
      const rec = await handle.promise;
      lastRecording = rec;
      status.set('done');
      statusText.set('Recording complete.');
      // Refresh device labels now that permission has been granted.
      void refreshDevices();
      return rec;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg === 'cancelled') {
        status.set('idle');
        statusText.set('Recording cancelled.');
      } else {
        status.set('error');
        statusText.set('');
        errorMsg.set(msg);
      }
      throw e;
    } finally {
      handle = null;
      if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
    }
  }

  /** Cancel a recording in progress. */
  function cancel(): void {
    handle?.cancel();
  }

  /** Patch one or more settings fields. */
  function patch(p: Partial<AcquireSettings>): void {
    settings.update((s) => ({ ...s, ...p }));
  }

  return {
    devices,
    settings,
    status,
    statusText,
    errorMsg,
    elapsed,
    init,
    refreshDevices,
    record,
    cancel,
    patch,
    /** The last successful recording, for bridge code to consume. */
    get lastRecording() { return lastRecording; },
  };
}

// ---- data bridge ----

/**
 * Convert a Recording into a DvmaItem (TimeData) suitable for
 * `actions.loadDataset` or the new `addRecordedSet`.
 *
 * The item mirrors what pydvma's Python `log_data` produces: `time_axis`
 * is a 1-D array [N], `time_data` is row-major [N, C], and `settings`
 * carries `fs`, `channels`, `stored_time`.
 */
export function recordingToItem(rec: Recording, name?: string): DvmaItem {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  const timestring = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;

  return {
    kind: 'TimeData',
    arrays: {
      time_axis: {
        shape: [rec.nSamples],
        data: rec.timeAxis,
        isComplex: false,
      },
      time_data: {
        shape: [rec.nSamples, rec.nChannels],
        data: rec.data,
        isComplex: false,
      },
    },
    meta: {
      test_name: name || `set_${timestring.replace(/[: ]/g, '_')}`,
      timestring,
    },
    settings: {
      fs: rec.fs,
      channels: rec.nChannels,
      stored_time: rec.nSamples / rec.fs,
      device_driver: 'web_audio',
    },
  };
}

/**
 * Wrap a single Recording into a full DvmaDataset (one TimeData item).
 * Used when the app has no existing dataset — the recording becomes the
 * first set.
 */
export function recordingToDataset(rec: Recording, name?: string): DvmaDataset {
  return {
    formatVersion: 2,
    pydvmaVersion: 'webui',
    items: [recordingToItem(rec, name)],
  };
}
