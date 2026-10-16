import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles.css';
import './sociothon-light.css';
try{document.documentElement.dataset.theme=localStorage.getItem('sociothon-ui-theme')==='dark'?'dark':'light'}catch{document.documentElement.dataset.theme='light'}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
if('serviceWorker' in navigator&&location.protocol!=='file:')window.addEventListener('load',()=>{void navigator.serviceWorker.register('/sw.js').catch(()=>{});});
