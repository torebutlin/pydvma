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
import type {
  AudioInputDevice,
  RecordConfig,
  Recording,
  RecordingHandle,
} from '../audio/source';
import {
  WebAudioProvider,
  type SourceProvider,
  type BridgeCaps,
  type BridgeConfig,
} from '../audio/provider';
import type { DvmaDataset, DvmaItem } from '../model/dataset';
import { capabilities } from './stages';

// ---- types ----

export type AcquireStatus = 'idle' | 'recording' | 'done' | 'error';

export interface AcquireSettings {
  deviceId: string;     // '' = browser default
  sampleRate: number;
  channelCount: number;
  durationS: number;
  /**
   * getUserMedia DSP constraints — see source.ts `buildAudioConstraints`.
   * All default OFF: the browser enables them for voice, but each
   * corrupts a measurement signal, so pydvma opts out unless the user
   * turns one on in Setup's "full" panel.
   */
  echoCancellation: boolean;
  noiseSuppression: boolean;
  autoGainControl: boolean;
  /**
   * Optional input-latency HINT in seconds (Setup "full" → timing).  `0`
   * or undefined = let the browser choose; a positive value is passed to
   * getUserMedia as an `ideal` latency constraint.
   */
  latency?: number;
}

/** A [min, max] capability range as reported by `getCapabilities`. */
export interface DeviceCapRange {
  min?: number;
  max?: number;
}

/**
 * Best-effort capabilities + current settings of the granted input device,
 * read from the track's `getCapabilities()` / `getSettings()`.  Everything
 * is optional — browsers report a variable subset (Chromium is the richest;
 * Firefox/Safari report little).  Consumed by Setup's "full" panel to show
 * the device's supported ranges and to constrain the fs/channel inputs.
 */
export interface DeviceCaps {
  /** Supported channel-count range. */
  channelCount?: DeviceCapRange;
  /** Supported sample-rate range (Hz). */
  sampleRate?: DeviceCapRange;
  /** Supported latency range (seconds), where reported. */
  latency?: DeviceCapRange;
  /** The track's CURRENT settings once the stream opened. */
  current?: { sampleRate?: number; channelCount?: number; latency?: number };
}

export type AcquireStore = ReturnType<typeof createAcquireStore>;

// ---- defaults ----

const DEFAULT_SETTINGS: AcquireSettings = {
  deviceId: '',
  sampleRate: 44100,
  channelCount: 1,
  durationS: 2.0,
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: false,
};

// ---- store factory ----

export function createAcquireStore(initialProvider?: SourceProvider) {
  const devices = writable<AudioInputDevice[]>([]);
  const settings = writable<AcquireSettings>({ ...DEFAULT_SETTINGS });
  const status = writable<AcquireStatus>('idle');
  const statusText = writable<string>('');
  const errorMsg = writable<string>('');
  const elapsed = writable<number>(0);
  /** Capabilities of the granted device (populated after permission). */
  const deviceCaps = writable<DeviceCaps | null>(null);
  /**
   * The acquisition backend (Wave B).  Defaults to Web Audio so nothing
   * changes when no `pydvma serve` bridge is present; App.svelte swaps in
   * a BridgeProvider via {@link setProvider} before `init` when one is
   * detected.  Mutable so the swap is a single reassignment the
   * monitor store (which reads `acquire.provider`) picks up on its next
   * `start()`.
   */
  let provider: SourceProvider = initialProvider ?? new WebAudioProvider();
  /** Bridge capability document (null for Web Audio or a dead bridge). */
  const bridgeCaps = writable<BridgeCaps | null>(null);
  /** Bridge-only NI/driver kwargs (SetupCard's NI group edits these). */
  const bridgeConfig = writable<BridgeConfig>({});

  let handle: RecordingHandle | null = null;
  let elapsedTimer: ReturnType<typeof setInterval> | null = null;
  /** The most recent recording result (consumed by the acquire → dataset bridge). */
  let lastRecording: Recording | null = null;

  /**
   * Swap the acquisition backend (App.svelte mode selection).  Re-applies
   * any staged bridge config to the new provider so a SetupCard edit made
   * before the swap is not lost.
   */
  function setProvider(p: SourceProvider): void {
    provider = p;
    p.setConfig?.(get(bridgeConfig));
  }

  /**
   * Patch the bridge NI/driver config and forward it to the provider so
   * it is merged into the next `configure` message.  A no-op on Web Audio
   * (the provider has no `setConfig`).
   */
  function patchBridge(p: Partial<BridgeConfig>): void {
    bridgeConfig.update((c) => ({ ...c, ...p }));
    provider.setConfig?.(get(bridgeConfig));
  }

  /**
   * Refresh the device list.  Call after a user gesture to get real
   * labels (browsers hide labels until permission is granted).
   */
  async function refreshDevices(): Promise<void> {
    try {
      const list = await provider.enumerateInputDevices();
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
   * Explicitly request microphone permission so device labels + real
   * capabilities become available WITHOUT starting a recording.  Opens a
   * throwaway stream (which triggers the browser's permission prompt),
   * reads the granted track's capabilities/settings for the Setup "full"
   * panel's device details, stops the stream, then re-enumerates so the
   * dropdown shows real device names.  Called from Setup's "Allow
   * microphone access" hint — never on app load.
   */
  async function requestPermission(): Promise<void> {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      try {
        const track = stream.getAudioTracks()[0];
        // `latency` isn't in every TS DOM lib's MediaTrack* types yet, so
        // augment the casts to read it without an `any` escape hatch.
        const caps = track?.getCapabilities?.() as
          (MediaTrackCapabilities & { latency?: { min?: number; max?: number } }) | undefined;
        const set = track?.getSettings?.() as
          (MediaTrackSettings & { latency?: number }) | undefined;
        const range = (r?: { min?: number; max?: number }): DeviceCapRange | undefined =>
          r && (r.min != null || r.max != null) ? { min: r.min, max: r.max } : undefined;
        deviceCaps.set({
          channelCount: range(caps?.channelCount),
          sampleRate: range(caps?.sampleRate),
          latency: range(caps?.latency),
          current: {
            sampleRate: set?.sampleRate,
            channelCount: set?.channelCount,
            latency: set?.latency,
          },
        });
      } catch {
        // getCapabilities/getSettings are optional — details just stay hidden.
      }
      stream.getTracks().forEach((t) => t.stop());
    } catch {
      // Permission denied or no device — labels stay hidden, hint remains.
    }
    await refreshDevices();
  }

  /**
   * Probe the active backend and kick-start device enumeration.  Called
   * once at app boot (after App.svelte has selected the provider).
   *
   * - Bridge: fetch `capabilities()`; on success flip the liveSource gate,
   *   store the caps (SetupCard reads them for the NI group), and
   *   enumerate the bridge devices.  A dead bridge (null caps) leaves the
   *   gate off so the app degrades gracefully.
   * - Web Audio: require `getUserMedia`, flip the gate immediately (before
   *   enumeration completes so the tabs are clickable), then enumerate.
   */
  async function init(): Promise<void> {
    if (provider.kind === 'bridge') {
      const caps = await provider.capabilities();
      bridgeCaps.set(caps);
      if (caps) {
        capabilities.update((c) => ({ ...c, liveSource: true }));
        await refreshDevices();
      }
      return;
    }
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
      echoCancellation: cfg.echoCancellation,
      noiseSuppression: cfg.noiseSuppression,
      autoGainControl: cfg.autoGainControl,
      latency: cfg.latency,
    };

    handle = provider.startRecording(rcfg);

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
    deviceCaps,
    /** Bridge capability document (null for Web Audio / a dead bridge). */
    bridgeCaps,
    /** Bridge-only NI/driver config (SetupCard's NI group edits these). */
    bridgeConfig,
    init,
    refreshDevices,
    requestPermission,
    record,
    cancel,
    patch,
    patchBridge,
    setProvider,
    /** The active acquisition backend (Web Audio or the serve bridge). */
    get provider() { return provider; },
    /** True while a `pydvma serve` bridge is the active backend. */
    get isBridge() { return provider.kind === 'bridge'; },
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
