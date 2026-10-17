import {useEffect,useState} from 'react';
import {AlertCircle,ArrowRight,BookOpen,CheckCircle2,ClipboardCheck,CloudOff,Lightbulb,RefreshCw,ShieldCheck,Sparkles,Target} from 'lucide-react';
import {api,send,type CivicCase} from './api';
import {domainInfo,statusName} from './components';

type Focus='evidence'|'water'|'cross_domain';
type Insight={label:string;explanation:string;source_ids:string[]};
type Report={case_id:string;case_version:number;focus:Focus;model:string;source_catalog:Record<string,string>;result:{overview:string;hypotheses:Insight[];missing_evidence:Insight[];next_checks:Insight[]};disclaimer:string};
const modes:{id:Focus;title:string;desc:string}[]=[
{id:'evidence',title:'Evidence review',desc:'Competing explanations and next checks'},
{id:'water',title:'Water context',desc:'Supply, meter and operating context'},
{id:'cross_domain',title:'Connected signals',desc:'Other visible cases in this zone'}
];
function InsightList({title,icon:Icon,items,sourceCatalog}:{title:string;icon:typeof Lightbulb;items:Insight[];sourceCatalog:Record<string,string>}){
 return <section className="ai-result-group"><h3><Icon size={17}/>{title}</h3><div className="ai-insight-list">{items.map((item,i)=><article key={i} className="ai-insight"><strong>{item.label}</strong><p>{item.explanation}</p>{item.source_ids.length>0&&<div className="ai-cites" aria-label="Evidence references">{item.source_ids.map(src=><span title={sourceCatalog[src]} key={src}>{src.replaceAll('_',' ')}</span>)}</div>}</article>)}</div></section>;
}
export function AIInvestigator({cases,onOpenCase}:{cases:CivicCase[];onOpenCase:(item:CivicCase)=>void}){
 const [selected,setSelected]=useState('');
 const [focus,setFocus]=useState<Focus>('evidence');
 const [ready,setReady]=useState<{configured:boolean;model:string}|null>(null);
 const [report,setReport]=useState<Report|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const selection=cases.find(c=>c.id===selected)||cases[0];
 useEffect(()=>{let live=true;api('/ai/status').then(data=>{if(live)setReady(data)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[]);
 const analyze=async()=>{
  if(!selection)return;
  setBusy(true);setError('');setReport(null);
  try{const response=await send('/ai/investigate',{case_id:selection.id,focus});setReport(response)}
  catch(e){setError(e instanceof Error?e.message:'Analysis unavailable.')}
  finally{setBusy(false)}
 };
 const changeCase=(id:string)=>{setSelected(id);setReport(null);setError('')};
 const changeFocus=(mode:Focus)=>{setFocus(mode);setReport(null);setError('')};
 return <div className="ai-desk">
  <div className="ai-hero"><div className="ai-hero-icon"><Sparkles size={23}/></div><div><span className="ai-kicker">CIVICSIGNAL INTELLIGENCE</span><h2>Investigate with context.</h2><p>Let Gemini suggest hypotheses, evidence gaps, and human-safe next checks—grounded in the case metadata available to your role.</p></div></div>
  <div className="ai-privacy"><ShieldCheck size={17}/><span><strong>Private by design.</strong> No names, complaint descriptions, photos, addresses, or field notes are sent. Pressing Analyze shares selected coded metadata with Google Gemini.</span></div>
  <div className="ai-panel">
   <div className="ai-panel-head"><div><span className="ai-kicker">01 / SELECT YOUR CASE</span><h3>Case and investigation angle</h3></div><span className={'ai-provider '+(ready?.configured?'ready':'off')}><span/>{ready?.configured?ready.model:'Gemini not configured'}</span></div>
   <div className="ai-fields"><label>Authorized case<select value={selection?.id||''} onChange={e=>changeCase(e.target.value)} disabled={!cases.length||busy}>{!cases.length&&<option value="">No authorized cases</option>}{cases.map(c=><option key={c.id} value={c.id}>{domainInfo(c.domain).name} · {c.id.slice(0,8)} · {statusName(c.status)}</option>)}</select></label></div>
   {selection&&<div className="ai-case-summary"><span>{domainInfo(selection.domain).name}</span><span>{statusName(selection.status)}</span><span>{selection.severity} severity</span><button type="button" onClick={()=>onOpenCase(selection)}>Evidence Passport <ArrowRight size={14}/></button></div>}
   <div className="ai-focus-group" role="group" aria-label="Investigation focus">{modes.map(mode=><button type="button" key={mode.id} aria-pressed={focus===mode.id} className={focus===mode.id?'chosen':''} disabled={busy} onClick={()=>changeFocus(mode.id)}><strong>{mode.title}</strong><small>{mode.desc}</small></button>)}</div>
   {!ready?.configured&&<div className="ai-unconfigured"><CloudOff size={18}/><p>Gemini is off until you add a local key. Open <code>.env</code> in the project root and set <code>GEMINI_API_KEY=your-key</code>, then restart CivicSignal. The key is never displayed in this interface.</p></div>}
   {error&&<div className="ai-error" role="alert"><AlertCircle size={17}/>{error}</div>}
   <button type="button" className="ai-generate" disabled={busy||!selection||!ready?.configured} onClick={()=>void analyze()}>{busy?<RefreshCw className="spin" size={18}/>:<Sparkles size={18}/>} {busy?'Reviewing evidence…':'Generate investigation brief'}</button>
   <p className="ai-microcopy">Optional cloud AI · Read-only suggestions · No automatic case actions</p>
  </div>
  {report&&<div className="ai-results" aria-live="polite"><div className="ai-results-head"><span className="ai-kicker">02 / GEMINI REVIEW</span><h2>Investigation brief</h2><p>{report.result.overview}</p><span className="ai-source-note"><CheckCircle2 size={15}/>Case version {report.case_version} · {report.model} · Citations checked against submitted source IDs</span></div>
   <div className="ai-result-grid"><InsightList title="Possible explanations" icon={Lightbulb} items={report.result.hypotheses} sourceCatalog={report.source_catalog}/><InsightList title="Missing evidence" icon={BookOpen} items={report.result.missing_evidence} sourceCatalog={report.source_catalog}/><InsightList title="Recommended checks" icon={ClipboardCheck} items={report.result.next_checks} sourceCatalog={report.source_catalog}/></div>
   <p className="ai-disclaimer"><Target size={16}/>{report.disclaimer}</p>
  </div>}
  {!report&&<div className="ai-empty"><Sparkles size={22}/><strong>Evidence first. Answers second.</strong><p>Choose a case and generate an optional AI brief. Your existing deterministic Evidence Assistant remains available without a key.</p></div>}
 </div>;
}
