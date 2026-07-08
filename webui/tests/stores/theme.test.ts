import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { get } from 'svelte/store';

// The theme store (lib/stores/theme.ts) reads localStorage / matchMedia and
// stamps data-theme on <html>. The vitest env is 'node' (no DOM), so we stub
// the globals it touches BEFORE importing the module (its initial store value
// is read at import time). A fresh module is loaded per test via resetModules.

interface FakeEl {
  attrs: Record<string, string>;
  setAttribute(name: string, value: string): void;
}

function fakeDoc(): { documentElement: FakeEl } {
  const el: FakeEl = {
    attrs: {},
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
  };
  return { documentElement: el };
}

function fakeStorage(seed: Record<string, string> = {}) {
  const map = new Map<string, string>(Object.entries(seed));
  return {
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    _map: map,
  };
}

function installEnv(opts: { stored?: Record<string, string>; systemDark?: boolean }) {
  const doc = fakeDoc();
  const storage = fakeStorage(opts.stored);
  const mql = {
    matches: !!opts.systemDark,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  (globalThis as Record<string, unknown>).document = doc;
  (globalThis as Record<string, unknown>).localStorage = storage;
  (globalThis as Record<string, unknown>).window = {
    matchMedia: (_q: string) => mql,
  };
  return { doc, storage, mql };
}

afterEach(() => {
  delete (globalThis as Record<string, unknown>).document;
  delete (globalThis as Record<string, unknown>).localStorage;
  delete (globalThis as Record<string, unknown>).window;
  vi.resetModules();
});

beforeEach(() => {
  vi.resetModules();
});

test('no stored preference → follows the OS (dark) and reports system', async () => {
  installEnv({ systemDark: true });
  const m = await import('../../src/lib/stores/theme');
  expect(get(m.theme)).toBe('dark');
  expect(get(m.themePreference)).toBe('system');
});

test('no stored preference → follows the OS (light)', async () => {
  installEnv({ systemDark: false });
  const m = await import('../../src/lib/stores/theme');
  expect(get(m.theme)).toBe('light');
});

test('a stored preference WINS over the OS media query', async () => {
  installEnv({ stored: { 'pydvma-theme': 'light' }, systemDark: true });
  const m = await import('../../src/lib/stores/theme');
  expect(get(m.theme)).toBe('light'); // explicit light beats OS dark
  expect(get(m.themePreference)).toBe('light');
});

test('setThemePreference stamps data-theme on <html> and persists', async () => {
  const { doc, storage } = installEnv({ systemDark: false });
  const m = await import('../../src/lib/stores/theme');
  m.setThemePreference('dark');
  expect(get(m.theme)).toBe('dark');
  expect(doc.documentElement.attrs['data-theme']).toBe('dark');
  expect(storage.getItem('pydvma-theme')).toBe('dark');
});

test('toggleTheme flips light↔dark and records an explicit choice', async () => {
  const { doc, storage } = installEnv({ systemDark: false }); // starts light
  const m = await import('../../src/lib/stores/theme');
  m.toggleTheme(); // → dark
  expect(get(m.theme)).toBe('dark');
  expect(doc.documentElement.attrs['data-theme']).toBe('dark');
  m.toggleTheme(); // → light
  expect(get(m.theme)).toBe('light');
  expect(storage.getItem('pydvma-theme')).toBe('light');
});

test('initTheme wires the OS-change listener (system-follow live-updates)', async () => {
  const { mql } = installEnv({ systemDark: false });
  const m = await import('../../src/lib/stores/theme');
  m.initTheme();
  expect(mql.addEventListener).toHaveBeenCalledWith('change', expect.any(Function));
});
