import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import {readThemePreference, resolveTheme} from './theme';
import './styles.css';
import './sociothon-light.css';
document.documentElement.dataset.theme = resolveTheme(readThemePreference());
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
if('serviceWorker' in navigator&&location.protocol!=='file:')window.addEventListener('load',()=>{void navigator.serviceWorker.register('/sw.js').catch(()=>{});});
