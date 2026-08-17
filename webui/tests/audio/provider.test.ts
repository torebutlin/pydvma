// provider.test.ts — `probeServeConfig`, the same-origin `/config`
// served-ness SIGNATURE probe (`audio/provider.ts`), tested directly with a
// fake `fetch` so it never touches a real network or DOM. Distinct from
// `fetchServeConfig` (a different function, different semantics for an
// EMPTY `{}` config — see `worker/selectEngine.ts`'s `resolveEngineClient`
// docstring for why that distinction matters to a caller).
import { describe, expect, test } from 'vitest';
import { probeServeConfig } from '../../src/lib/audio/provider';

/** A minimal fake `fetch` returning a fixed status/content-type/body. */
function fakeFetch(opts: { ok: boolean; contentType?: string | null; body?: unknown }): typeof fetch {
  return (async () => ({
    ok: opts.ok,
    headers: { get: (name: string) => (name.toLowerCase() === 'content-type' ? (opts.contentType ?? null) : null) },
    json: async () => opts.body,
  })) as unknown as typeof fetch;
}

describe('probeServeConfig', () => {
  test('200 + application/json {} -> true (the serve signature, even with an EMPTY config)', async () => {
    // Deliberately the common `pydvma serve` (no --settings) case: an empty
    // object still proves something IS answering /config as pydvma serve
    // does -- unlike fetchServeConfig, this probe has no reason to treat an
    // empty config as "nothing to report".
    const f = fakeFetch({ ok: true, contentType: 'application/json; charset=utf-8', body: {} });
    await expect(probeServeConfig(f)).resolves.toBe(true);
  });

  test('200 + application/json with real settings -> true', async () => {
    const f = fakeFetch({ ok: true, contentType: 'application/json', body: { fs: 3000 } });
    await expect(probeServeConfig(f)).resolves.toBe(true);
  });

  test('200 + text/html (a static host\'s SPA-fallback index.html) -> false', async () => {
    const f = fakeFetch({ ok: true, contentType: 'text/html; charset=utf-8', body: '<html></html>' });
    await expect(probeServeConfig(f)).resolves.toBe(false);
  });

  test('404 -> false', async () => {
    const f = fakeFetch({ ok: false, contentType: 'application/json' });
    await expect(probeServeConfig(f)).resolves.toBe(false);
  });

  test('a JSON array response -> false (the signature requires a JSON OBJECT)', async () => {
    const f = fakeFetch({ ok: true, contentType: 'application/json', body: [] });
    await expect(probeServeConfig(f)).resolves.toBe(false);
  });

  test('a null JSON body -> false', async () => {
    const f = fakeFetch({ ok: true, contentType: 'application/json', body: null });
    await expect(probeServeConfig(f)).resolves.toBe(false);
  });

  test('a fetch that throws (network error / no /config route at all) -> false, not a rejection', async () => {
    const f = (async () => { throw new Error('network error'); }) as unknown as typeof fetch;
    await expect(probeServeConfig(f)).resolves.toBe(false);
  });

  test('no fetchImpl falls back to the global fetch -- a relative /config with no page origin fails closed to false, not a rejection', async () => {
    // Node's global `fetch` (always defined in this vitest environment)
    // rejects a bare relative URL with no page to resolve it against --
    // exactly the failure shape probeServeConfig's own try/catch is there
    // to swallow. Proves the "no fetchImpl" default-resolution path is
    // reached AND that a real-world failure (no /config route, network
    // down) never propagates as a rejection.
    await expect(probeServeConfig()).resolves.toBe(false);
  });
});
