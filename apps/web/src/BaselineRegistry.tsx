import {useCallback,useEffect,useRef,useState} from 'react';
import {api,send,fmt,date,download} from './api';

import {ErrorBox} from './components';

function useApi(path:string){
  const [data,setData]=useState<any>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  const request=useRef<AbortController|null>(null);
  const reload=useCallback(async()=>{
    request.current?.abort();
    const controller=new AbortController();request.current=controller;setLoading(true);
    try{const result=await api(path,{signal:controller.signal});if(!controller.signal.aborted){setData(result);setError('')}}
    catch(e:any){if(!controller.signal.aborted)setError(e.message)}
    finally{if(!controller.signal.aborted)setLoading(false)}
  },[path]);
  useEffect(()=>{reload();return()=>request.current?.abort()},[reload]);
  return {data,error,loading,reload};
}

export function BaselineRegistry({domain,refresh}:{domain:string,refresh:()=>Promise<void>}) {
  const r=useApi('/baselines/'+domain);
  const [start,setStart]=useState(''),[end,setEnd]=useState(''),[reason,setReason]=useState('');
  const [selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  useEffect(()=>{setStart('');setEnd('');setSelected('');setReason('');setError('');setMessage('')},[domain]);
  useEffect(()=>{if(r.data){setStart(v=>v||r.data.suggested_start?.slice(0,16)||'');setEnd(v=>v||r.data.suggested_end?.slice(0,16)||'')}},[r.data]);
  const pending=r.data?.versions?.some((v:any)=>v.status==='pending'&&v.job_status!=='failed');
  useEffect(()=>{if(!pending)return;const timer=setInterval(()=>r.reload(),2000);return()=>clearInterval(timer)},[pending,r.reload]);
  const chosen=r.data?.versions?.find((v:any)=>v.id===selected);
  const active=r.data?.versions?.find((v:any)=>v.id===r.data.active_id);
  async function create(){
    setBusy(true);setError('');setMessage('');
    try{const result=await send('/baselines/'+domain+'/candidates',{train_start:start+':00Z',train_end:end+':00Z',reason,idempotency_key:crypto.randomUUID()});setSelected(result.baseline_id);await r.reload();setMessage('Candidate queued. The active baseline remains selected until an administrator promotes it.')}catch(e:any){setError(e.message)}finally{setBusy(false)}
  }
  async function activate(action:'promote'|'rollback'){
    setBusy(true);setError('');setMessage('');
    try{await send('/baselines/'+domain+'/'+action,{baseline_id:selected,version:r.data.version,reason});await r.reload();await refresh();setMessage(action==='promote'?'Candidate promoted. Future analyses use its frozen training snapshot.':'Previous baseline restored. Case decisions and evidence are preserved.');setReason('')}catch(e:any){setError(e.message);await r.reload()}finally{setBusy(false)}
  }
  return <div className="baseline-registry" data-testid="baseline-registry">{r.error&&<ErrorBox error={r.error} retry={r.reload}/>} {r.loading&&!r.data&&<p>Loading baseline versions…</p>}{r.data&&<>
    <div className="info-banner"><p>Baseline versions apply to stored {domain} readings. Training is frozen; unresolved incident intervals are excluded from candidates. Evaluation uses later observations and reports residual error, not anomaly accuracy. Forecasts and synthetic scenarios use their separate pipelines.</p></div>
    <p data-testid="active-baseline"><strong>Active baseline:</strong> {active?.id||'None — evaluate and promote a candidate'} · revision {r.data.version}</p>
    <p className="helper">Promotion selects its evaluated analytics snapshot. Run analysis in the domain workspace to process current readings and create findings. Existing case decisions remain unchanged.</p>
    {error&&<ErrorBox error={error}/>} {message&&<p role="status" className="info-banner">{message}</p>}
    <div className="baseline-grid"><section><h3>Prepare a candidate</h3><label>Training start (UTC)<input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)}/></label><label>Training end, exclusive (UTC)<input type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)}/></label><p className="helper">At least 14 valid days per asset, followed by at least 24 valid evaluation intervals. Training snapshots cannot be edited.</p><label>Baseline review reason<textarea value={reason} rows={3} onChange={e=>setReason(e.target.value)} placeholder="Explain the training period or activation decision."/></label><button className="button primary" onClick={create} disabled={busy||!start||!end||reason.trim().length<5}>Evaluate candidate</button></section>
    <section><h3>Review and activate</h3><label>Baseline version<select aria-label="Baseline version" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Choose a version</option>{r.data.versions.map((v:any)=><option key={v.id} value={v.id}>{v.id.slice(0,8)} · {v.id===r.data.active_id?'active':v.status} · {date(v.created_at)}</option>)}</select></label>{chosen&&<><p className="baseline-id">{chosen.id}</p><p>{chosen.status==='pending'?'Worker: '+chosen.job_status:chosen.status} · {fmt(chosen.training_rows)} frozen training rows</p><p className="helper">Training: {chosen.train_start} → {chosen.train_end} (exclusive)</p><p className="helper">Excluded {chosen.exclusions?.reading_count||0} unresolved intervals and {chosen.exclusions?.invalid_or_inactive_count||0} invalid/inactive intervals.</p>{chosen.job_error&&<ErrorBox error={chosen.job_error}/>} {chosen.evaluation?.reason&&<p role="alert">{chosen.evaluation.reason}</p>}
    {chosen.evaluation?.candidate&&<div className="table-scroll"><table><caption>Held-out baseline residual error · {chosen.evaluation.unit}</caption><thead><tr><th>Metric</th><th>Previous baseline</th><th>Candidate</th></tr></thead><tbody>{['mae','rmse'].map(key=><tr key={key}><th>{key.toUpperCase()}</th><td>{fmt(chosen.evaluation.previous?.[key],3)}</td><td>{fmt(chosen.evaluation.candidate[key],3)}</td></tr>)}</tbody></table><p className="helper">{chosen.evaluation.intervals} later intervals. {chosen.evaluation.limitation}</p></div>}
    <button className="button secondary" onClick={()=>download(chosen,'baseline-'+chosen.id+'.json')}>Export version summary</button>
    {r.data.can_activate?<div className="baseline-actions"><button className="button primary" disabled={busy||reason.trim().length<5||chosen.status!=='evaluated'||chosen.parent_id!==r.data.active_id||chosen.id===r.data.active_id} onClick={()=>activate('promote')}>Promote reviewed candidate</button><button className="button secondary" disabled={busy||reason.trim().length<5||!r.data.history.includes(chosen.id)||chosen.id===r.data.active_id} onClick={()=>activate('rollback')}>Roll back to this version</button></div>:<p className="helper">An administrator must review and activate versions.</p>}</>}</section></div>
    <h3>Version history</h3><div className="table-scroll"><table><thead><tr><th>Version</th><th>Status</th><th>Training rows</th><th>Created</th></tr></thead><tbody>{r.data.versions.map((v:any)=><tr key={v.id}><td><button className="text-button" onClick={()=>setSelected(v.id)} aria-label={'Review baseline '+v.id}>{v.id.slice(0,8)}</button></td><td>{v.id===r.data.active_id?'Active':v.status==='pending'?v.job_status:v.status}</td><td>{fmt(v.training_rows)}</td><td>{date(v.created_at)}</td></tr>)}</tbody></table></div>
    <h3>Activation and training decisions</h3><ul className="baseline-decisions">{r.data.decisions.map((a:any)=><li key={a.id}><strong>{a.action.replaceAll('_',' ')}</strong> · {date(a.created_at)}<p>{a.reason}</p><small>{a.actor_id} · {a.after.active_id||a.after.baseline_id}</small></li>)}</ul>
  </>}</div>;
}
