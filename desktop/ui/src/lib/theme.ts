import type { ThemeMode } from './types';
import { patch } from './store';

export const THEME_CACHE_KEY = 'geolock-theme';

export function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'light' || mode === 'dark') return mode;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** Applies the theme to <html>, caches the choice for the next start, and tells the store. */
export function applyTheme(mode: ThemeMode): void {
  const resolved = resolveTheme(mode);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  try {
    localStorage.setItem(THEME_CACHE_KEY, mode);
  } catch {
    /* storage can be unavailable; the setting still lives on the backend */
  }
  patch({ themeResolved: resolved });
}

/** Follows the OS theme while the setting is "System". */
export function watchSystemTheme(getMode: () => ThemeMode | undefined): void {
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener('change', () => {
    if ((getMode() ?? 'system') === 'system') applyTheme('system');
  });
}
