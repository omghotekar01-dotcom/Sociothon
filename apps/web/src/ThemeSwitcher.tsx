import {useEffect,useState} from 'react';
import {Moon,Sun} from 'lucide-react';

type Theme='light'|'dark';
function readTheme():Theme {
  try{return localStorage.getItem('sociothon-ui-theme')==='dark'?'dark':'light'}catch{return 'light'}
}
export function ThemeSwitcher(){
  const [theme,setTheme]=useState<Theme>(readTheme);
  useEffect(()=>{document.documentElement.dataset.theme=theme;try{localStorage.setItem('sociothon-ui-theme',theme)}catch{}},[theme]);
  const next=theme==='light'?'dark':'light';
  return <button type="button" className="theme-toggle" onClick={()=>setTheme(next)}
    aria-label={'Switch to '+next+' theme'} title={'Switch to '+next+' theme'} aria-pressed={theme==='dark'}>
    {theme==='light'?<Moon size={15}/>:<Sun size={15}/>}
    <span>{theme==='light'?'Dark mode':'Light mode'}</span>
  </button>;
}
