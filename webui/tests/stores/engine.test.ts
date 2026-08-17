// engine.test.ts — the store-level surface added by the Task 10 review
// follow-ups: `hostNote` (a one-time user-facing notice from factory
// resolution) and `pydvmaVersion` (the native host's greeted pydvma
// release), plus the pure helpers behind the version-skew warning.
//
// The worker/client transport itself is mocked with a minimal fake — this
// file cares about what `createEngineStore`'s `boot()` does with a resolved
// `ResolvedEngine`, not about a real Worker or socket.
import { describe, expect, test, vi } from 'vitest';
import { get } from 'svelte/store';
import {
  createEngineStore,
  ENGINE_WHEELS,
  pydvmaVersionFromWheelFilename,
  warnOnPydvmaVersionMismatch,
} from '../../src/lib/stores/engine';
import type { EngineClient } from '../../src/lib/worker/client';
import type { ResolvedEngine } from '../../src/lib/worker/selectEngine';

function fakeClient(): EngineClient {
  return {
    init: vi.fn().mockResolvedValue(undefined),
    call: vi.fn(),
    observe: vi.fn(),
    restart: vi.fn(),
    dispose: vi.fn(),
  };
}

describe('pydvmaVersionFromWheelFilename', () => {
  test('parses the version out of a standard wheel filename', () => {
    expect(pydvmaVersionFromWheelFilename('pydvma-2.3.0-py3-none-any.whl')).toBe('2.3.0');
  });

  test('null for a filename that does not match the expected shape', () => {
    expect(pydvmaVersionFromWheelFilename('PeakUtils-1.3.5-py3-none-any.whl')).toBeNull();
    expect(pydvmaVersionFromWheelFilename('not-a-wheel-at-all')).toBeNull();
  });
});

describe('warnOnPydvmaVersionMismatch', () => {
  test('warns when the native release differs from ENGINE_WHEELS[0]', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    warnOnPydvmaVersionMismatch('9.9.9');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain('9.9.9');
    warn.mockRestore();
  });

  test('no warning when the native release matches ENGINE_WHEELS[0]', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const matching = pydvmaVersionFromWheelFilename(ENGINE_WHEELS[0]);
    warnOnPydvmaVersionMismatch(matching);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  test('no-op for a null/undefined actual version (unknown, nothing to compare)', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    warnOnPydvmaVersionMismatch(null);
    warnOnPydvmaVersionMismatch(undefined);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('createEngineStore: hostNote / pydvmaVersion surfaced from factory resolution', () => {
  test('a resolved pydvmaVersion is exposed as a readable; no note when none was set', async () => {
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'native', pydvmaVersion: '2.3.0' };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(get(store.host)).toBe('native');
    expect(get(store.pydvmaVersion)).toBe('2.3.0');
    expect(get(store.hostNote)).toBeNull();
  });

  test('a resolved note (the silent-fallback case) is exposed via hostNote', async () => {
    const note = 'native engine unavailable — using browser engine (see console)';
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'pyodide', note };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(get(store.host)).toBe('pyodide');
    expect(get(store.hostNote)).toBe(note);
  });

  test('boot() warns on a native pydvmaVersion mismatch, exactly once', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'native', pydvmaVersion: '9.9.9' };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });

  test('boot() does NOT warn on a native pydvmaVersion match', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const matching = pydvmaVersionFromWheelFilename(ENGINE_WHEELS[0])!;
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'native', pydvmaVersion: matching };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  test('a pyodide resolution never triggers the version-mismatch warn, even with pydvmaVersion unset', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const resolved: ResolvedEngine = { client: fakeClient(), host: 'pyodide' };
    const store = createEngineStore(async () => resolved);
    await store.boot();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  test('a directly-injected client (no factory) never sets hostNote/pydvmaVersion', () => {
    // Every pre-Task-10 caller and most tests take this path -- host reads
    // 'pyodide' immediately (see createEngineStore's own docstring) and the
    // factory branch inside boot() never runs at all.
    const store = createEngineStore(fakeClient());
    expect(get(store.host)).toBe('pyodide');
    expect(get(store.hostNote)).toBeNull();
    expect(get(store.pydvmaVersion)).toBeNull();
  });
});
