import {useCallback,useEffect,useRef,useState} from 'react';
import {ArrowRight,Camera,RefreshCw,Search,ShieldCheck} from 'lucide-react';
import {api,type CivicCase} from './api';
import {Badge,domainInfo,Empty,ErrorBox,statusName} from './components';

type Report={id:string;case_id:string;title:string;description:string;location:string;domain:string;zone_id:string;receipt:string;created_at:string;status:string};
type Detail={id:string;citizen_reports:Report[];evidence_records:{id:string;kind:string;notes:string;url?:string;created_at:string}[];assignment_team?:{lead?:{name:string}|null};status:string;version:number};
export function StaffCaseInbox({onOpenCase}:{onOpenCase:(item:CivicCase)=>void}){
 const [items,setItems]=useState<Report[]>([]);const [selected,setSelected]=useState<Report|null>(null);
 const [detail,setDetail]=useState<Detail|null>(null);const [search,setSearch]=useState('');
 const [loading,setLoading]=useState(true);const [error,setError]=useState('');const requestId=useRef(0);
 const load=useCallback(async(silent=false)=>{
  if(!silent)setLoading(true);
  try{const reports=await api('/reports');if(!Array.isArray(reports))throw new Error('Unexpected report list');setItems(reports);setError('')}
  catch(e){setError(e instanceof Error?e.message:'Could not load submissions.')}
  finally{if(!silent)setLoading(false)}
 },[]);
 useEffect(()=>{void load();const id=setInterval(()=>void load(true),45000);return()=>clearInterval(id)},[load]);
 useEffect(()=>{if(!selected?.case_id)return;let active=true;const caseId=selected.case_id;const refreshDetail=async()=>{try{const value=await api('/cases/'+encodeURIComponent(caseId));if(active){setDetail(value);setError('')}}catch(e){if(active)setError(e instanceof Error?e.message:'Could not refresh case evidence.')}};const id=setInterval(()=>void refreshDetail(),15000);return()=>{active=false;clearInterval(id)}},[selected?.case_id]);
 const open=async(report:Report)=>{
  const requested=++requestId.current;setSelected(report);setDetail(null);setError('');
  try{const value=await api('/cases/'+encodeURIComponent(report.case_id));if(requested===requestId.current)setDetail(value)}
  catch(e){if(requested===requestId.current)setError(e instanceof Error?e.message:'Could not read case evidence.')}
 };
 const visible=items.filter(r=>[r.title,r.description,r.receipt,r.domain,r.zone_id].some(v=>v?.toLowerCase().includes(search.toLowerCase())));
 const pics=detail?.evidence_records?.filter(e=>e.kind==='photograph'&&e.url)||[];
 return <div className="staff-inbox">
   <section className="panel staff-inbox-list"><div className="staff-inbox-head"><div><span className="eyebrow">CITIZEN → OPERATOR</span><h2>Submitted reports</h2><p>These are real saved reports from your authorized zones, not placeholder cards.</p></div><button className="button secondary" disabled={loading} onClick={()=>void load()}><RefreshCw size={15}/>Refresh</button></div>
   <label className="staff-search"><Search size={15}/><input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search title, zone, reference…" aria-label="Search citizen submissions"/></label>
   {loading&&<p role="status">Refreshing saved reports…</p>}{error&&<ErrorBox error={error} retry={load}/>}
   <div className="staff-report-list">{visible.map(report=><button type="button" key={report.id} className={selected?.id===report.id?'active':''} onClick={()=>void open(report)}>
    <div><strong>{report.title}</strong><small>{domainInfo(report.domain).name} · {report.zone_id} · {report.receipt}</small><p>{report.description}</p></div><Badge type="cyan">{statusName(report.status)}</Badge><ArrowRight size={15}/>
   </button>)}</div>
   {!loading&&!visible.length&&<Empty title="No matching reports" text="Citizen submissions appear automatically when saved in an authorized service zone."/>}
   </section>
   <section className="panel staff-inbox-detail" aria-live="polite">
    {!selected?<div className="staff-inbox-empty"><ShieldCheck size={24}/><h3>Select a report</h3><p>Review its full description, location, photos and case progress before assigning work.</p></div>:<><span className="eyebrow">REPORT {selected.receipt}</span><h2>{selected.title}</h2><p>{selected.description}</p><dl><div><dt>Submitted location</dt><dd>{selected.location}</dd></div><div><dt>Category & zone</dt><dd>{domainInfo(selected.domain).name} · {selected.zone_id}</dd></div><div><dt>Current status</dt><dd>{statusName(detail?.status||selected.status)}</dd></div><div><dt>Assigned inspector</dt><dd>{detail?.assignment_team?.lead?.name||'Not yet assigned'}</dd></div></dl>
    <h3><Camera size={17}/> Citizen photographs</h3>
    {detail?pics.length?<div className="staff-photo-grid">{pics.map(photo=><a key={photo.id} href={photo.url} target="_blank" rel="noreferrer" title="View authorized original photograph"><img loading="lazy" src={photo.url} alt={'Photo evidence for '+selected.title}/><small>{photo.notes}</small></a>)}</div>:<p className="helper">No photographs uploaded for this case.</p>:<p className="helper">Loading authorized case records…</p>}
    {detail&&<button type="button" className="button primary" onClick={()=>onOpenCase(detail as unknown as CivicCase)}>Open Evidence Passport and assign <ArrowRight size={15}/></button>}
    </>}
   </section>
 </div>;
}
