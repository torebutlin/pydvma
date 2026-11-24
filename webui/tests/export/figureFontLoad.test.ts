import { afterEach, expect, it, vi } from 'vitest';
import { loadFigureFontBase64 } from '../../src/lib/export/figureFont';

afterEach(() => { vi.unstubAllGlobals(); });

// The font is fetched once and cached for every later Save Figure. A failed
// fetch must not be cached with it, or one transient failure would make every
// later save fail until the page is reloaded.
it('retries the font fetch after a failure, then keeps the good result', async () => {
  const fetchMock = vi.fn()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(new Response(new Uint8Array([65, 66, 67]))); // "ABC"
  vi.stubGlobal('fetch', fetchMock);
  await expect(loadFigureFontBase64()).rejects.toThrow('offline');
  await expect(loadFigureFontBase64()).rejects.toThrow('503');
  await expect(loadFigureFontBase64()).resolves.toBe('QUJD');
  await expect(loadFigureFontBase64()).resolves.toBe('QUJD');
  expect(fetchMock).toHaveBeenCalledTimes(3);
});
