import {useEffect, useState} from 'react';
import {Link2, Network, RefreshCw} from 'lucide-react';
import {api, Bootstrap, CivicCase, fmt, send} from './api';
import {Badge, Empty, ErrorBox, Loading, SectionHead, statusName} from './components';

type LinkStatus = 'suggested'|'accepted'|'rejected'|'unlinked';
type Association = {
  id:string; source_id:string; target_id:string; status:LinkStatus;
  basis:{reason?:string; review_reason?:string; source?:string; provenance?:string; relationship?:string;
    distance_m?:number; time_offset_hours?:number; limitation?:string; same_asset?:boolean};
};

function AssociationReview({edge, cases, select, reviewed}:{edge:Association; cases:Map<string,CivicCase>; select:(c:CivicCase)=>void; reviewed:()=>void}) {
  const [reason,setReason] = useState('');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const update = async(status:LinkStatus) => {
    setBusy(true);setError('');
    try {
      await send('/associations/'+edge.id,{status,expected_status:edge.status,reason:reason.trim()},'PATCH');
      reviewed();
    } catch(error) {setError(error instanceof Error?error.message:'Association review failed.');}
    finally {setBusy(false);}
  };
  const basis=edge.basis||{};
  return <article data-association-id={edge.id}>
    <Badge type={edge.status==='accepted'?'teal':edge.status==='suggested'?'violet':'neutral'}>{statusName(edge.status)}</Badge>
    <h3>{[edge.source_id,edge.target_id].map((id,index)=><span key={id}>{index>0&&<> <Link2 size={14}/> </>}<button className="text-button" onClick={()=>{const item=cases.get(id);if(item)select(item)}}>{cases.get(id)?.title||id}</button></span>)}</h3>
    <p>{basis.reason||'Human-reviewed association'}</p>
    {basis.review_reason&&<p><strong>Latest review:</strong> {basis.review_reason}</p>}
    <p><Badge type="cyan">{statusName(basis.relationship||'operator_linked')}</Badge> · {basis.source||basis.provenance||'Recorded review'}</p>
    <small>{basis.distance_m==null?'Distance not recorded':`${fmt(basis.distance_m,2)} m separation`} · {basis.time_offset_hours==null?'Time offset not recorded':`${fmt(basis.time_offset_hours,2)} h observation offset`}</small>
    <p className="helper">{basis.limitation||'Correlation does not establish causation. Independent case histories are preserved.'}</p>
    <label>Reason for this review<textarea rows={2} value={reason} maxLength={2000} onChange={event=>setReason(event.target.value)} placeholder="Explain why these cases should be linked or separated."/></label>
    <div>{(['accepted','rejected','unlinked'] as const).filter(status=>status!==edge.status).map(status=><button className="button secondary" key={status} disabled={busy||reason.trim().length<5} onClick={()=>update(status)}>{status==='accepted'?'Accept':status==='rejected'?'Reject':'Unlink'}</button>)}</div>
    {busy&&<p role="status">Saving review…</p>}{error&&<ErrorBox error={error}/>}
  </article>;
}

function IncidentGraph({edges,cases,select}:{edges:Association[];cases:Map<string,CivicCase>;select:(c:CivicCase)=>void}) {
  const active=edges.filter(edge=>['suggested','accepted'].includes(edge.status));
  const ids=[...new Set(active.flatMap(edge=>[edge.source_id,edge.target_id]))].filter(id=>cases.has(id));
  const height=Math.max(340,Math.ceil(ids.length/2)*90+70);
  const positions=new Map(ids.map((id,index)=>[id,{x:index%2?580:190,y:60+Math.floor(index/2)*90}]));
  if(!ids.length)return <Empty title="No active links to plot" text="Suggestions and accepted relationships appear here. The register retains rejected and unlinked decisions."/>;
  return <><div className="network-map-viewport" tabIndex={0} role="region" aria-label="Cross-domain case graph. Scroll to explore; equivalent case links are in the register below.">
    <svg viewBox={`0 0 800 ${height}`} style={{width:'100%',minWidth:620,height}} role="group" aria-label="Recorded case relationships">
      {active.map(edge=>{const a=positions.get(edge.source_id),b=positions.get(edge.target_id);return a&&b?<line key={edge.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={edge.status==='accepted'?'#5edbb6':'#b9a3ff'} strokeWidth={2} strokeDasharray={edge.status==='suggested'?'6 5':undefined}><title>{statusName(edge.status)}: {cases.get(edge.source_id)?.title} → {cases.get(edge.target_id)?.title}</title></line>:null})}
      {ids.map(id=>{const c=cases.get(id)!,p=positions.get(id)!;return <g key={id} role="button" tabIndex={0} aria-label={`Open ${c.title}`} onClick={()=>select(c)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();select(c)}}}><rect x={p.x-170} y={p.y-30} width={340} height={60} rx={10} fill="#12232d" stroke="#718c9a"/><text x={p.x} y={p.y-7} textAnchor="middle" fill="#eff8fc" fontSize={13}>{c.title.length>43?c.title.slice(0,40)+'…':c.title}</text><text x={p.x} y={p.y+15} textAnchor="middle" fill="#adbdc6" fontSize={12}>{statusName(c.domain)} · {statusName(c.severity)} · {statusName(c.status)}</text><title>{c.title}</title></g>})}
    </svg>
  </div><p className="helper pad">Solid green: accepted · dashed violet: suggested. Nodes are authorized cases; lines represent reviewable relationships. This diagram is not a geographic map.</p></>;
}

export function CrossDomainPage({data,select,notify}:{data:Bootstrap;select:(c:CivicCase)=>void;notify:(message:string)=>void}) {
  const [edges,setEdges]=useState<Association[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [revision,setRevision]=useState(0);
  const [source,setSource]=useState('');
  const [target,setTarget]=useState('');
  const [reason,setReason]=useState('');
  const [saving,setSaving]=useState(false);
  const [saveError,setSaveError]=useState('');
  const cases=new Map(data.cases.map(c=>[c.id,c]));
  const reload=()=>setRevision(value=>value+1);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');
    api('/associations',{signal:controller.signal}).then(rows=>{if(!controller.signal.aborted)setEdges(rows)}).catch(error=>{if(!controller.signal.aborted)setError(error.message)}).finally(()=>{if(!controller.signal.aborted)setLoading(false)});
    return()=>controller.abort();
  },[revision]);
  const record=async(event:React.FormEvent)=>{
    event.preventDefault();setSaving(true);setSaveError('');
    try{const result=await send('/cases/'+source+'/link',{target_id:target,reason:reason.trim()});reload();setReason('');notify(result.status==='accepted'?'Association recorded.':'This pair already has a review. Use its register entry to change the decision.');}
    catch(error){setSaveError(error instanceof Error?error.message:'Unable to record association.');}
    finally{setSaving(false);}
  };
  return <>
    <div className="info-banner"><Network size={21}/><div><strong>Shared context is an investigative lead.</strong><p>Suggestions use registered geographic coordinates, compatible domains, and configured distance/time windows. Every connection requires human review.</p></div></div>
    <div className="cross-layout"><section className="panel"><SectionHead eyebrow="REVIEWABLE CASE CONNECTIONS" title="The cross-domain picture"><button className="text-button" onClick={reload} disabled={loading}><RefreshCw size={14}/>Refresh</button></SectionHead>{loading?<Loading/>:error?<ErrorBox error={error} retry={reload}/>:<IncidentGraph edges={edges} cases={cases} select={select}/>}</section>
    <section className="panel link-form"><SectionHead title="Connect two investigations"/><form className="form-fields" onSubmit={record}>
      <label>Source case<select value={source} required onChange={event=>{setSource(event.target.value);if(event.target.value===target)setTarget('')}}><option value="">Select a case</option>{data.cases.map(c=><option value={c.id} key={c.id}>{c.title}</option>)}</select></label>
      <label>Related case<select value={target} required onChange={event=>setTarget(event.target.value)}><option value="">Select a related case</option>{data.cases.filter(c=>c.id!==source).map(c=><option value={c.id} key={c.id}>{c.title}</option>)}</select></label>
      <label>Evidence for this association<textarea rows={4} value={reason} maxLength={2000} onChange={event=>setReason(event.target.value)} placeholder="Explain the shared location, time window or asset connection."/></label>
      <button className="button primary" disabled={saving||!source||!target||source===target||reason.trim().length<5}><Link2 size={15}/>{saving?'Recording…':'Record association'}</button>
      {saveError&&<ErrorBox error={saveError}/>}
    </form></section></div>
    <div className="panel spaced"><SectionHead title="Association register"/>{loading?<Loading/>:error?<ErrorBox error={error} retry={reload}/>:edges.length?<div className="association-list">{edges.map(edge=><AssociationReview key={edge.id+'-'+edge.status} edge={edge} cases={cases} select={select} reviewed={()=>{reload();notify('Association review recorded.')}}/>)}</div>:<Empty title="No cross-domain suggestions" text="No authorized case pair meets the current coordinate and time windows. Record a reasoned association when other reviewable evidence supports coordination."/>}</div>
  </>;
}
