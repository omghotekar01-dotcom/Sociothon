import {parseWaterReviewRecovery, serializeWaterReviewRecovery, waterReviewRecoveryKey, type PendingWaterReview} from './waterReviewRecovery';
import {useEffect, useState} from 'react';
import {api, ApiError, date, download, fmt, send, type CivicCase} from './api';
import {useInterfaceLanguage} from './uiLanguage';

export type WaterReviewSnapshot = {
  schedule_mode?:'current'|'historical'; zone_id:string; snapshot_hash:string; configuration_version:number;
  review_inputs:Record<string,unknown>; window:{start:string;end_exclusive:string};
  balance:{unaccounted_l:number|null}; schedule_counts:Record<string,number>;
  source_observations:Array<unknown>;
};

export function AttachWaterReview({snapshot,zone,userId,onOpenCase}:{snapshot:WaterReviewSnapshot|null;zone:string;userId:string;onOpenCase:(item:CivicCase)=>void}) {
  const mr=useInterfaceLanguage()==='mr';
  const t=(en:string,marathi:string)=>mr?marathi:en;
  const [cases,setCases]=useState<CivicCase[]>([]);
  const [caseId,setCaseId]=useState('');
  const [reason,setReason]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [revision,setRevision]=useState(0);
  const [loading,setLoading]=useState(true);
  const [pending,setPending]=useState<PendingWaterReview|null>(null);
  const [retain,setRetain]=useState(false);
  const [storageError,setStorageError]=useState('');
  const [blocked,setBlocked]=useState(false);
  const storageKey=waterReviewRecoveryKey(userId,zone);
  useEffect(()=>{
    let raw:string|null=null;
    try{raw=localStorage.getItem(storageKey)}catch{setStorageError(t('Device recovery storage is unavailable. You can continue on this page without retaining the request.','उपकरणावरील पुनर्प्राप्ती साठवण उपलब्ध नाही. विनंती न जतन करता या पृष्ठावर पुढे जाऊ शकता.'));return}
    if(raw)try{setPending(parseWaterReviewRecovery(raw,userId,zone));setRetain(true)}catch{setBlocked(true);setStorageError(t('The saved recovery reference cannot be read. It has been retained; remove it explicitly before a new attachment.','जतन केलेला पुनर्प्राप्ती संदर्भ वाचता येत नाही. तो कायम ठेवला आहे; नवीन जोडणीपूर्वी स्पष्टपणे काढा.'))}
  },[storageKey,userId,zone]);
  useEffect(()=>{setSaved(null)},[snapshot?.snapshot_hash]);
  const forget=()=>{try{localStorage.removeItem(storageKey);setStorageError('');setBlocked(false);return true}catch{setStorageError(t('Device storage could not be cleared. Keep this page open.','उपकरणावरील साठवण काढता आली नाही. हे पृष्ठ उघडे ठेवा.'));return false}};
  const persist=(attempt:PendingWaterReview)=>{if(retain)try{localStorage.setItem(storageKey,serializeWaterReviewRecovery(attempt,userId,zone));setStorageError('')}catch{setStorageError(t('Could not retain the request on this device. Keep this page open and retry here.','या उपकरणावर विनंती जतन करता आली नाही. हे पृष्ठ उघडे ठेवून येथे पुन्हा पाठवा.'))}};
  const [saved,setSaved]=useState<{evidence_id:string;case_id:string}|null>(null);
  useEffect(()=>{
    let active=true;setLoading(true);
    api('/cases').then((items:CivicCase[])=>{if(active){setCases(items.filter(c=>c.domain==='water'&&c.zone_id===zone&&!['resolved','closed'].includes(c.status)));setCaseId('')}}).catch(e=>{if(active)setError(e.message)}).finally(()=>{if(active)setLoading(false)});
    return()=>{active=false};
  },[zone,revision]);
  const attach=async()=>{
    const selected=cases.find(c=>c.id===caseId);
    if(blocked||(!pending&&(!selected||!snapshot)))return;
    const attempt=pending||{caseId,body:{review:snapshot!.review_inputs,snapshot_hash:snapshot!.snapshot_hash,case_version:selected!.version,reason,idempotency_key:crypto.randomUUID()}};
    setPending(attempt);persist(attempt);setBusy(true);setError('');
    try{
      const response=await send(`/water/zones/${zone}/cases/${attempt.caseId}/reviews`,attempt.body);
      if(typeof response.evidence_id!=='string'||response.case_id!==attempt.caseId||response.snapshot_hash!==attempt.body.snapshot_hash)throw new Error('Unconfirmed attachment');
      setSaved(response);setPending(null);forget();
    }
    catch(e){
      if(e instanceof ApiError&&e.status>=400&&e.status<500){setError(e.message);if(!retain){setPending(null)}}
      else setError(t('Confirmation is unavailable. Retry this exact attachment before starting another. The retry cannot create a second record.','पुष्टी उपलब्ध नाही. दुसरी नोंद सुरू करण्यापूर्वी हीच जोडणी पुन्हा पाठवा. पुन्हा पाठवल्याने दुसरी प्रत तयार होणार नाही.'));
    }finally{setBusy(false)}
  };
  if(!snapshot&&!pending&&!storageError&&!saved)return null;
  return <section className="water-review-attachment" aria-label={t('Attach water review','पाण्याचा आढावा जोडा')}>
    <h3>{t('Save to an Evidence Passport','पुरावा नोंदीत जतन करा')}</h3>
    <p className="helper">{t('Attach the reviewed readings, configuration and accounting assumptions to an open water case in this zone. This records context without changing the case decision.','तपासलेली मोजमापे, संरचना व हिशेबाची गृहितके या क्षेत्रातील उघड्या पाणी प्रकरणाला जोडा. प्रकरणाचा निर्णय बदलणार नाही.')}</p>
    {error&&<p role="alert">{error}</p>}{storageError&&<p role="alert">{storageError}</p>}
    <label className="checkbox-label"><input type="checkbox" disabled={busy||blocked} checked={retain} onChange={e=>{const enabled=e.target.checked;if(!enabled&&!forget())return;setRetain(enabled);if(enabled&&pending)try{localStorage.setItem(storageKey,serializeWaterReviewRecovery(pending,userId,zone))}catch{setStorageError(t('Could not retain the request. Keep this page open.','विनंती जतन करता आली नाही. पृष्ठ उघडे ठेवा.'))}}}/>{t('Retain this pending attachment on this device, including my reason and accounting note, for recovery after reload.','पृष्ठ पुन्हा उघडल्यावर पुनर्प्राप्तीसाठी प्रलंबित जोडणी, माझे कारण व हिशेबाची टिप्पणी या उपकरणावर ठेवा.')}</label>
    {pending&&<p className="helper">{t('Original pending case / reviewed window','मूळ प्रलंबित प्रकरण / तपासलेला कालावधी')}: {pending.caseId} · {String(pending.body.review.start)} → {String(pending.body.review.end)}</p>}
    {(pending||blocked||storageError)&&<button className="text-button" disabled={busy} onClick={()=>{if(forget()){setPending(null);setRetain(false);setError('')}}}>{t('Remove local recovery reference','स्थानिक पुनर्प्राप्ती संदर्भ काढा')}</button>}
    {(pending||blocked)&&<p className="helper">{t('Removing the local reference does not delete evidence already saved on the server. Retry the original request first when confirmation is uncertain.','स्थानिक संदर्भ काढल्याने सर्व्हरवर जतन केलेला पुरावा हटत नाही. पुष्टी अनिश्चित असल्यास आधी मूळ विनंती पुन्हा पाठवा.')}</p>}
    {saved?<><p role="status">{t('Review attached. Evidence ID','आढावा जोडला. पुरावा क्रमांक')}: {saved.evidence_id}</p><button className="button secondary" disabled={busy} onClick={async()=>{setBusy(true);try{onOpenCase(await api('/cases/'+saved.case_id))}catch(e){setError(e instanceof Error?e.message:'Unable to open case')}finally{setBusy(false)}}}>{t('Open saved Evidence Passport','जतन केलेली पुरावा नोंद उघडा')}</button></>:<>
      <fieldset disabled={busy||!!pending||loading||blocked||!snapshot}>
        <label>{t('Water case for this review','या आढाव्यासाठी पाण्याचे प्रकरण')}<select value={caseId} onChange={e=>setCaseId(e.target.value)}><option value="">{t('Choose an open case','उघडे प्रकरण निवडा')}</option>{cases.map(c=><option key={c.id} value={c.id}>{c.title} · {c.id}</option>)}</select></label>
        <label>{t('Why this review is relevant','हा आढावा का संबंधित आहे')}<textarea value={reason} maxLength={2000} onChange={e=>setReason(e.target.value)}/></label>
      </fieldset>
      {!loading&&!cases.length&&<p role="status">{t('No authorized open water cases in this zone. Create or reopen a case through the normal review workflow.','या क्षेत्रात अधिकृत उघडी पाणी प्रकरणे नाहीत. नेहमीच्या पुनरावलोकन प्रक्रियेतून प्रकरण तयार करा किंवा पुन्हा उघडा.')}</p>}
      <div className="form-actions"><button className="button primary" disabled={busy||blocked||(!pending&&(!snapshot||!caseId||reason.trim().length<5))} onClick={attach}>{pending?t('Retry exact attachment','हीच जोडणी पुन्हा पाठवा'):t('Attach reviewed snapshot','तपासलेला आढावा जोडा')}</button><button className="button secondary" disabled={busy||!!pending} onClick={()=>{setError('');setRevision(v=>v+1)}}>{t('Refresh case list','प्रकरणांची यादी पुन्हा मिळवा')}</button></div>
      {pending&&<p role="status">{retain&&!storageError?t('The original request is retained for this account and zone. Retry is manual; changed source data or case versions still require review.','मूळ विनंती या खात्यासाठी व क्षेत्रासाठी जतन आहे. पुन्हा पाठवणे हस्तचलित आहे; बदललेली माहिती किंवा प्रकरणासाठी पुनरावलोकन आवश्यक आहे.'):t('The exact pending request is held in this page. Keep it open until confirmation.','पुष्टी न झालेली मूळ विनंती या पृष्ठावर ठेवली आहे. पुष्टी मिळेपर्यंत पृष्ठ उघडे ठेवा.')}</p>}
    </>}
  </section>;
}

export function WaterReviewEvidence({record}:{record:{id:string;notes:string;created_at:string;observations:{water_review:WaterReviewSnapshot}}}) {
  const mr=useInterfaceLanguage()==='mr';
  const snapshot=record.observations.water_review;
  return <div className="saved-water-review" data-testid="saved-water-review">
    <strong>{mr?'जतन केलेला पाणीपुरवठा आढावा':'Saved water operations review'}</strong>
    <p>{record.notes}</p><small>{date(record.created_at)} · {record.id}</small>
    <p>{mr?'निवडलेला कालावधी (UTC)':'Selected window (UTC)'}: {snapshot.window.start} → {snapshot.window.end_exclusive}</p>
    <p>{mr?'संरचनेची आवृत्ती':'Configuration version'}: {snapshot.configuration_version} · {mr?'मूळ मोजमापे':'Source observations'}: {snapshot.source_observations.length}</p>
    <p>{mr?'हिशेबातील फरक':'Accounting residual'}: {snapshot.balance.unaccounted_l===null?(mr?'उपलब्ध नाही':'Unavailable'):fmt(snapshot.balance.unaccounted_l,2)+' L'}</p>
    <p>{mr?'वेळापत्रकाचा संदर्भ':'Schedule context'}: {snapshot.schedule_mode==='historical'?(mr?'नोंदवलेले लागू कालावधी':'Recorded effective periods'):(mr?'सध्याची संरचना':'Current configuration')}</p>
    <p className="helper">{mr?'नोंदवलेला संदर्भ; सिद्ध गळती किंवा प्रत्यक्ष स्थळ तपासणी नाही. सध्याची संरचना ऐतिहासिक वेळापत्रक सिद्ध करत नाही.':'Recorded context, not a confirmed leak or field inspection. Current configuration does not prove the historical supply schedule.'}</p>
    <details><summary>{mr?'आढाव्याची ओळख':'Snapshot identity'}</summary><code>{snapshot.snapshot_hash}</code></details>
    <button className="button secondary" onClick={()=>download(snapshot,'water-review-evidence-'+record.id+'.json')}>{mr?'जतन केलेला आढावा निर्यात करा':'Export saved water review'}</button>
  </div>;
}
