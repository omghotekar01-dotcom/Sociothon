import {useEffect, useState} from 'react';
import {api, ApiError, CivicCase, send} from './api';
import {emptyFieldDraft, parseFieldDraft, prepareFieldSubmission, type FieldDraft, type FieldKind} from './fieldDraft';
import {useInterfaceLanguage} from './uiLanguage';

export function FieldNotes({item,userId,role,busy:parentBusy,onCase,onSaved}:{item:CivicCase;userId:string;role:string;busy:boolean;onCase:(item:CivicCase)=>void;onSaved:()=>Promise<void>}) {
  const mr=useInterfaceLanguage()==='mr';
  const [fields,setFields]=useState<Array<{key:string;label:string;mr:string;type:string;unit?:string;minimum?:number;maximum?:number;max_length?:number}>>([]);
  const [schemaError,setSchemaError]=useState('');
  useEffect(()=>{let active=true;api('/cases/'+item.id+'/field-schema').then(schema=>{if(active){setFields(schema.fields);setSchemaError('')}}).catch(()=>{if(active)setSchemaError(mr?'क्षेत्रीय फॉर्म उपलब्ध नाही. नोंदी जतन ठेवा व पृष्ठ पुन्हा उघडा.':'Domain form unavailable. Keep your notes and reopen the case to retry.')});return()=>{active=false}},[item.id,mr]);
  const storageKey='civic-notes-'+userId+'-'+item.id;
  const [initial]=useState(()=>{try{const raw=localStorage.getItem(storageKey);return {draft:parseFieldDraft(raw,item.version),saved:!!raw,error:''};}catch(error){return {draft:emptyFieldDraft(item.version),saved:false,error:error instanceof Error?error.message:'Device storage is unavailable.'};}});
  const [draft,setDraft]=useState<FieldDraft>(initial.draft);
  // A successful status transition can advance the case while this form is empty.
  // Adopt that version only for an untouched form; preserve unsent/pending evidence.
  useEffect(()=>{setDraft(current=>!current.pending&&!current.notes&&!Object.keys(current.observations||{}).length?{...current,baseVersion:item.version}:current)},[item.version]);
  const [consent,setConsent]=useState(initial.saved);
  const [storageError,setStorageError]=useState(initial.error);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [online,setOnline]=useState(navigator.onLine);
  const [confirmed,setConfirmed]=useState(false);
  const [conflict,setConflict]=useState(false);
  const [reviewed,setReviewed]=useState<CivicCase|null>(null);
  useEffect(()=>{const update=()=>setOnline(navigator.onLine);window.addEventListener('online',update);window.addEventListener('offline',update);return()=>{window.removeEventListener('online',update);window.removeEventListener('offline',update);};},[]);
  const persist=(value:FieldDraft)=>{try{localStorage.setItem(storageKey,JSON.stringify(value));setStorageError('');return true;}catch{setStorageError('Device storage failed. Keep this page open; your draft is currently in memory only.');return false;}};
  const update=(value:FieldDraft)=>{setDraft(value);setConfirmed(false);if(consent)persist(value);};
  const submit=async(kind:FieldKind)=>{
    const next=prepareFieldSubmission(draft,kind,crypto.randomUUID());
    update(next);setBusy(true);setError('');setConflict(false);setReviewed(null);
    try{
      const {kind:submissionKind,...body}=next.pending!;
      const updated=await send('/cases/'+item.id+'/'+(submissionKind==='intervention'?'intervention':'inspection'),submissionKind==='intervention'?body:{...body,kind:submissionKind});
      setDraft(emptyFieldDraft(updated.version));setConfirmed(true);onCase(updated);
      try{localStorage.removeItem(storageKey);setStorageError('');}catch{setStorageError('Saved on the server, but the device copy could not be removed. Retrying that saved copy will not duplicate the evidence.');}
      try{await onSaved();}catch{setError('Evidence saved. The workspace could not refresh; refresh it when the connection returns.');}
    }catch(error){
      setConflict(error instanceof ApiError && error.status===409);
      setError(error instanceof ApiError?error.message:'Submission not confirmed. Your notes are retained. Retry the pending submission when the connection returns.');
    }finally{setBusy(false);}
  };
  const locked=busy||parentBusy||!!draft.pending;
  const electricalCase=item.domain==='electricity';
  const canSubmit=online&&!busy&&!parentBusy&&draft.notes.trim().length>=10&&['inspector','admin'].includes(role)&&(!electricalCase||(role==='inspector'&&draft.electricalQualified));
  const review=async()=>{setBusy(true);try{const latest=await api('/cases/'+item.id);onCase(latest);setReviewed(latest);setError('');}catch(error){setError(error instanceof Error?error.message:'Unable to refresh the case.');}finally{setBusy(false);}};
  return <section className="field-notes" data-testid="field-notes">
    <h3>Field findings & intervention</h3>
    <fieldset disabled={locked}><legend>{mr?'या क्षेत्रातील प्रत्यक्ष निरीक्षणे':'Domain-specific field observations'}</legend><p className="helper">{mr?'अज्ञात मोजमाप रिकामे ठेवा. छायाचित्रावरून मोजमाप गृहीत धरू नका.':'Leave unknown measurements blank. Values are manually recorded, never inferred from photographs.'}</p>{schemaError&&<p role="alert">{schemaError}</p>}{fields.map(field=><label key={field.key}>{mr?field.mr:field.label}{field.unit?' · '+field.unit:''}<input type={field.type==='number'?'number':'text'} step={field.type==='number'?'any':undefined} min={field.minimum} max={field.maximum} maxLength={field.max_length} value={draft.observations?.[field.key]??''} onChange={e=>{const observations={...draft.observations};if(e.target.value==='')delete observations[field.key];else observations[field.key]=field.type==='number'?Number(e.target.value):e.target.value;update({...draft,observations})}}/></label>)}</fieldset>
    <p className="helper" role="status">{online?'Network available. Submission is always manual.':'Offline. Keep editing your draft; reconnect before submitting.'}</p>
    {['Record what you safely observed','Document the action and responsible crew','Specify a follow-up observation'].map((text,i)=><label className="checkbox-label" key={text}><input type="checkbox" disabled={locked} checked={draft.checklist[i]} onChange={e=>update({...draft,checklist:draft.checklist.map((v,j)=>i===j?e.target.checked:v)})}/>{text}</label>)}
    {electricalCase&&<><div className="info-banner"><strong>Electrical safety: keep away from suspected hazards. Use verified local emergency or utility channels. Never touch, test or repair energized equipment.</strong></div><label className="checkbox-label"><input type="checkbox" disabled={locked} checked={draft.electricalQualified} onChange={e=>update({...draft,electricalQualified:e.target.checked})}/>I confirm I am an administrator-qualified electricity inspector and this record reflects a safe, authorized assessment.</label><p className="helper">Electrical inspection and intervention submissions require an administrator-recorded qualification and this case-specific confirmation.</p></>}
    <label>Findings and intervention notes<textarea aria-label="Findings and intervention notes" rows={5} maxLength={10000} disabled={locked} value={draft.notes} onChange={e=>update({...draft,notes:e.target.value})} placeholder="Describe the observed finding, intervention and follow-up. Never claim a verified repair from a model score."/></label>
    <p className="draft-state" aria-live="polite">{confirmed?'Synchronized with server':draft.pending?'Submission unconfirmed · exact payload retained for safe retry':consent&&!storageError?'Draft saved on this device · not synchronized':'Unsent notes · kept in memory until saved'}</p>
    <p className="helper">Draft case version {draft.baseVersion}. Current displayed version {item.version}.</p>
    {storageError&&<p role="alert" className="field-note-error">{storageError}</p>}
    {error&&<p role="alert" className="field-note-error">{error}</p>}
    <label className="checkbox-label"><input type="checkbox" disabled={locked} checked={consent} onChange={e=>{setConsent(e.target.checked);if(e.target.checked)persist(draft);else try{localStorage.removeItem(storageKey);setStorageError('');}catch{setStorageError('The saved device copy could not be removed.');}}}/>Keep these notes on this device until I submit or clear them</label>
    <p className="helper">With this enabled, notes, checklist and pending submission are saved on each change for this account and case. Turning it off removes the device copy. Nothing is sent automatically.</p>
    <div className="form-actions"><button className="button secondary" disabled={locked||!consent||!draft.notes} onClick={()=>persist(draft)}>Save draft</button><button className="text-button" disabled={locked} onClick={()=>{try{localStorage.removeItem(storageKey);setStorageError('');setDraft(emptyFieldDraft(item.version));setConfirmed(false);setError('');}catch{setStorageError('The device draft could not be cleared.');}}}>Clear draft</button></div>
    {draft.pending?<><button className="button primary" disabled={!canSubmit} onClick={()=>submit(draft.pending!.kind)}>{busy?'Submitting…':'Retry pending submission'}</button><p className="helper">Retry confirms the original submission. Editing stays locked until confirmation or review of a rejected case version.</p></>:<div className="form-actions"><button className="button secondary" disabled={!canSubmit} onClick={()=>submit('inspection')}>Submit inspection</button><button className="button secondary" disabled={!canSubmit||item.status!=='monitoring'} onClick={()=>submit('follow_up')}>Submit follow-up</button><button className="button primary" disabled={!canSubmit||item.status!=='assigned'||!draft.checklist.every(Boolean)} onClick={()=>submit('intervention')}>Submit intervention</button></div>}
    {conflict&&<div className="field-conflict"><p>The server rejected this submission. Review the latest evidence and case state before preparing another attempt.</p><button className="button secondary" disabled={!online||busy} onClick={review}>Refresh case for review</button>{reviewed&&<><p>Latest case: {reviewed.status.replaceAll('_',' ')} · version {reviewed.version}. The Evidence Passport now shows this version.</p><button className="button secondary" disabled={busy} onClick={()=>{update({...draft,baseVersion:reviewed.version,pending:null});setConflict(false);setReviewed(null);setError('');}}>Use reviewed case version</button></>}</div>}
  </section>;
}
