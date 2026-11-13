import { storage } from './storage';
export type Theme = 'light' | 'dark' | 'system';
const KEY = 'agentforge.theme';
export const getTheme = (): Theme => (storage.get(KEY) as Theme) || 'dark';
export function applyTheme(t: Theme = getTheme()) {
  const dark = t === 'dark' || (t === 'system' && typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
}
export function setTheme(t: Theme) {
  storage.set(KEY, t);
  applyTheme(t);
}
