/** Shared runtime appearance state for theme switcher and Settings. */
export type ThemePreference='light'|'dark'|'system';
export const THEME_KEY='sociothon-ui-theme';
export const THEME_EVENT='civic-theme-change';
export function readThemePreference():ThemePreference{
  try{const v=localStorage.getItem(THEME_KEY);if(v==='light'||v==='dark'||v==='system')return v}catch{}
  return 'light';
}
export function resolveTheme(v:ThemePreference):'light'|'dark'{
  if(v!=='system')return v;
  return typeof window!=='undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches?'dark':'light';
}
export function applyThemePreference(v:ThemePreference):void{
  document.documentElement.dataset.theme=resolveTheme(v);
  document.documentElement.dataset.themePreference=v;
  try{localStorage.setItem(THEME_KEY,v)}catch{}
  window.dispatchEvent(new Event(THEME_EVENT));
}
