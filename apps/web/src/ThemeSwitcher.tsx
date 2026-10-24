import {useEffect,useState} from 'react';
import {Moon,Sun} from 'lucide-react';
import {send} from './api';
import {applyThemePreference,readThemePreference,resolveTheme,THEME_EVENT} from './theme';
export function ThemeSwitcher({user}:{user?:{id?:string}|null}){
 const [preference,setPreference]=useState(readThemePreference);
 const [saveError,setSaveError]=useState(false);
 useEffect(()=>{
  const sync=()=>setPreference(readThemePreference());
  const media=window.matchMedia?.('(prefers-color-scheme: dark)');
  const onDevice=()=>{if(readThemePreference()==='system')applyThemePreference('system')};
  window.addEventListener(THEME_EVENT,sync);window.addEventListener('storage',sync);
  media?.addEventListener?.('change',onDevice);
  return()=>{window.removeEventListener(THEME_EVENT,sync);window.removeEventListener('storage',sync);media?.removeEventListener?.('change',onDevice)};
 },[]);
 const actual=resolveTheme(preference);
 const next=actual==='light'?'dark':'light';
 const toggle=()=>{applyThemePreference(next);setPreference(next);setSaveError(false);if(user?.id)void send('/settings',{display:next},'PATCH').catch(()=>setSaveError(true))};
 return <><button type="button" className="theme-toggle" onClick={toggle} aria-label={'Switch to '+next+' theme'} title={'Switch to '+next+' theme'} aria-pressed={actual==='dark'}>
 {actual==='light'?<Moon size={15}/>:<Sun size={15}/>}<span>{actual==='light'?'Dark mode':'Light mode'}</span>
 </button>{saveError&&<span className="theme-save-error" role="status">Theme changed locally; account sync failed. Retry in Settings.</span>}</>;
}
