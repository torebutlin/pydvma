// theme.ts — light/dark theme preference, persisted, with a system-follow
// default (round-5 item 11).
//
// The EFFECTIVE theme ('light' | 'dark') is always stamped as
// `data-theme` on <html>; app.css keys its dark token override off
// `:root[data-theme='dark']`. Resolution order:
//
//   1. an explicit user choice (localStorage 'pydvma-theme' = 'light'|'dark'),
//      set by the Header toggle — WINS and persists across sessions; else
//   2. the OS `prefers-color-scheme` media query — followed live (a runtime
//      OS switch re-stamps) until the user makes an explicit choice.
//
// index.html carries a tiny inline boot script that does the very first stamp
// (before first paint, so there is no light-flash); `initTheme()` here then
// reconciles the store state and wires the live OS listener. All DOM / storage
// access is guarded so the module is import-safe under the node test env.

import { writable } from 'svelte/store';

export type Theme = 'light' | 'dark';
/** A stored preference, or 'system' when the user has made no explicit choice. */
export type ThemePreference = Theme | 'system';

/** localStorage key holding the explicit preference ('light' | 'dark'). */
export const THEME_KEY = 'pydvma-theme';

/** The OS-preferred theme right now (defaults to light when unknown). */
export function systemTheme(): Theme {
  try {
    return typeof window !== 'undefined' &&
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  } catch {
    return 'light';
  }
}

/** The persisted preference, or 'system' when none/invalid is stored. */
export function storedPreference(): ThemePreference {
  try {
    const v = globalThis.localStorage?.getItem(THEME_KEY);
    return v === 'dark' || v === 'light' ? v : 'system';
  } catch {
    return 'system';
  }
}

/** Resolve a preference to a concrete theme (system → current OS theme). */
export function resolve(pref: ThemePreference): Theme {
  return pref === 'system' ? systemTheme() : pref;
}

/** Stamp the effective theme on <html> so the CSS token override applies. */
function stamp(theme: Theme): void {
  try {
    globalThis.document?.documentElement?.setAttribute('data-theme', theme);
  } catch {
    /* no DOM (tests) — nothing to stamp */
  }
}

const initialPref = storedPreference();

/** The current effective theme — subscribe to react (e.g. canvas redraws). */
export const theme = writable<Theme>(resolve(initialPref));
/** The current preference ('light' | 'dark' | 'system'). */
export const themePreference = writable<ThemePreference>(initialPref);

let currentPref: ThemePreference = initialPref;
let mql: MediaQueryList | undefined;
let listening = false;

/** Re-follow the OS when (and only when) no explicit choice is in force. */
function onSystemChange(): void {
  if (currentPref !== 'system') return;
  const t = systemTheme();
  stamp(t);
  theme.set(t);
}

/**
 * Set the preference: persist an explicit choice (or clear it for 'system'),
 * stamp the resolved theme, and update the stores. Safe to call repeatedly.
 */
export function setThemePreference(pref: ThemePreference): void {
  currentPref = pref;
  try {
    if (pref === 'system') globalThis.localStorage?.removeItem(THEME_KEY);
    else globalThis.localStorage?.setItem(THEME_KEY, pref);
  } catch {
    /* storage blocked (private mode) — the in-memory choice still applies */
  }
  const t = resolve(pref);
  stamp(t);
  theme.set(t);
  themePreference.set(pref);
}

/** Flip to the opposite of the current effective theme (an explicit choice). */
export function toggleTheme(): void {
  setThemePreference(resolve(currentPref) === 'dark' ? 'light' : 'dark');
}

/**
 * Idempotent boot: reconcile the store with the persisted preference, stamp
 * the effective theme (the inline boot script already did the first stamp;
 * this covers the store + any race), and attach the live OS listener once.
 * Call from the app root's onMount.
 */
export function initTheme(): void {
  currentPref = storedPreference();
  const t = resolve(currentPref);
  stamp(t);
  theme.set(t);
  themePreference.set(currentPref);
  if (!listening && typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    try {
      mql = window.matchMedia('(prefers-color-scheme: dark)');
      mql.addEventListener('change', onSystemChange);
      listening = true;
    } catch {
      /* matchMedia unavailable — system-follow simply won't live-update */
    }
  }
}
