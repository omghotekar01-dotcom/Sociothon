import {useState} from 'react';
import {Badge} from './components';
import {ReportPage} from './ReportPage';
import type {Bootstrap} from './api';

type OfflinePermit={schema:1;userId:string;language:'en'|'mr'};
function readPermit():OfflinePermit|null{
  try{
    const value=JSON.parse(localStorage.getItem('civic-offline-citizen-v1')||'null');
    if(value?.schema===1&&typeof value.userId==='string'&&value.userId.length>0&&value.userId.length<=160&&['en','mr'].includes(value.language))return value;
  }catch{}
  return null;
}

export function OfflineCitizenEntry({retry}:{retry:()=>void}) {
  const [permit]=useState(readPermit);
  const [language,setLanguage]=useState<'en'|'mr'>(permit?.language||'en');
  const mr=language==='mr';
  if(!permit)return <main className="offline-entry"><section className="panel"><Badge type="amber">{mr?'स्थानिक ऑफलाइन प्रवेश':'LOCAL OFFLINE ENTRY'}</Badge><div className="offline-language"><button className="button secondary" onClick={()=>setLanguage(mr?'en':'mr')}>{mr?'English':'मराठी'}</button></div><h1>{mr?'सध्या CivicSignal सर्व्हर उपलब्ध नाही':'CivicSignal is not available right now'}</h1><p>{mr?'या उपकरणावर ऑफलाइन अहवाल सुरू करण्याची संमती जतन केलेली नाही. जोडणी परत आल्यावर प्रवेश करा, अहवाल पृष्ठ उघडा आणि ऑफलाइन वापरासाठी तयार ठेवा हा पर्याय निवडा.':'This device has not been set up for offline citizen reporting. When the server is available, sign in, open the report page and enable “Keep citizen reporting ready on this device.”'}</p><button className="button primary" onClick={retry}>{mr?'पुन्हा जोडण्याचा प्रयत्न करा':'Try connecting again'}</button></section></main>;
  const data={user:{id:permit.userId,role:'citizen',settings:{language:permit.language}},zones:[{id:'river',name:'River Ward'},{id:'market',name:'Market Ward'},{id:'hill',name:'Hill Ward'}]} as Bootstrap;
  return <main className="offline-entry" lang={language}>
    <section className="offline-banner panel"><div><Badge type="amber">{mr?'स्थानिक मसुदा मोड':'LOCAL DRAFT MODE'}</Badge><h1>{mr?'सर्व्हर सध्या जोडलेला नाही':'The server is not reachable'}</h1><p>{mr?'आपण आधी जतन केलेला मसुदा पुन्हा उघडू किंवा नवीन अहवाल उपकरणावर जतन करू शकता. पाठवणे किंवा स्थिती तपासणे जोडणी परत आल्यावरच शक्य आहे.':'Restore a saved draft or save a new report on this device. You can submit it or check its status after the server reconnects.'}</p></div><div className="offline-banner-actions"><button className="button secondary" onClick={()=>setLanguage(mr?'en':'mr')}>{mr?'English':'मराठी'}</button><button className="button secondary" onClick={retry}>{mr?'पुन्हा जोडण्याचा प्रयत्न करा':'Try connecting again'}</button></div></section>
    <ReportPage data={data} notify={()=>{}} go={()=>{}} refresh={async()=>{}} offlineOnly onLanguageChange={setLanguage}/>
    <p className="offline-entry-note">{mr?'हे स्थानिक मसुदे आहेत. पाठवलेले असल्याची पुष्टी जोडणीशिवाय दिसत नाही.':'These are local drafts. Without a connection, the app cannot confirm a submission.'}</p>
  </main>;
}
