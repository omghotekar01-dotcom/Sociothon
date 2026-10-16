import {useState} from 'react';
import {dateTimeLocalToIso, dateTimeLocalValue, download, getDisplayTimezoneLabel, send} from './api';
import {useInterfaceLanguage} from './uiLanguage';

export type ScheduleHistory = {version:number;entries:Array<{id:string;effective_from:string;effective_until:string;source_reference:string;reason:string;configuration_version:number;recorded_at:string;revoked_at?:string;revocation_reason?:string}>};

export function WaterHistory({zone,history,configurationVersion,admin,dirty,latestEnd,onChange}:{zone:string;history:ScheduleHistory;configurationVersion:number;admin:boolean;dirty:boolean;latestEnd:string|null;onChange:(history:ScheduleHistory)=>void}) {
  const mr=useInterfaceLanguage()==='mr';const t=(en:string,marathi:string)=>mr?marathi:en;
  const [open,setOpen]=useState(false);
  const [start,setStart]=useState(latestEnd?dateTimeLocalValue(Date.parse(latestEnd)-86400000):'');
  const [end,setEnd]=useState(latestEnd?dateTimeLocalValue(latestEnd):'');
  const [source,setSource]=useState('');const [reason,setReason]=useState('');
  const [revokeId,setRevokeId]=useState('');const [correction,setCorrection]=useState('');
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [pending,setPending]=useState<Record<string,unknown>|null>(null);
  const [notice,setNotice]=useState('');
  const save=async()=>{
    setError('');setNotice('');setBusy(true);
    try{
      const body=pending||{version:history.version,configuration_version:configurationVersion,effective_from:dateTimeLocalToIso(start),effective_until:dateTimeLocalToIso(end),source_reference:source,reason,idempotency_key:crypto.randomUUID()};
      setPending(body);const result=await send(`/water/zones/${zone}/schedule-history`,body);onChange(result);setPending(null);setReason('');setSource('');setNotice(t('Effective schedule recorded.','लागू वेळापत्रकाची नोंद झाली.'));
    }catch(e){setError(e instanceof Error?e.message:'Unable to save schedule');if(e&&typeof e==='object'&&'status' in e&&Number(e.status)>=400&&Number(e.status)<500)setPending(null)}finally{setBusy(false)}
  };
  const revoke=async()=>{
    setBusy(true);setError('');setNotice('');
    try{onChange(await send(`/water/zones/${zone}/schedule-history/${revokeId}/revoke`,{version:history.version,reason:correction}));setRevokeId('');setCorrection('');setNotice(t('Record revoked; its audit history is retained.','नोंद रद्द केली; लेखापरीक्षण इतिहास कायम आहे.'))}catch(e){setError(e instanceof Error?e.message:'Unable to revoke schedule')}finally{setBusy(false)}
  };
  return <section className="water-extension" aria-label={t('Historical supply schedules','ऐतिहासिक पुरवठा वेळापत्रके')}>
    <button className="button secondary" aria-expanded={open} onClick={()=>setOpen(!open)}>{t('Historical supply schedules','ऐतिहासिक पुरवठा वेळापत्रके')} · {history.entries.filter(e=>!e.revoked_at).length}</button>
    {open&&<>
      <p>{t('Record when a saved schedule applied, with its source. Gaps remain unknown. Recorded history does not independently prove that supply occurred. Corrections retain the original record.','जतन केलेले वेळापत्रक कधी लागू होते व त्याचा स्रोत नोंदवा. नोंद नसलेला कालावधी अज्ञात राहतो. इतिहासाची नोंद म्हणजे प्रत्यक्ष पुरवठ्याचा स्वतंत्र पुरावा नाही. दुरुस्तीत मूळ नोंद कायम राहते.')}</p>
      <p className="helper">{t('History version','इतिहास आवृत्ती')}: {history.version} · {t('Inputs use','इनपुट प्रमाणवेळ')}: {getDisplayTimezoneLabel()}</p>
      {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
      {admin&&<fieldset className="form-fields" disabled={busy||dirty||!!pending}>
        <legend>{t('Record the saved configuration’s schedule','जतन केलेल्या संरचनेचे वेळापत्रक नोंदवा')} · {configurationVersion}</legend>
        <label>{t('Effective from','लागू होण्याची सुरुवात')}<input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)}/></label>
        <label>{t('Effective until (exclusive)','लागू होण्याचा शेवट (वगळून)')}<input type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)}/></label>
        <label>{t('Schedule source reference','वेळापत्रकाचा स्रोत संदर्भ')}<input maxLength={500} value={source} onChange={e=>setSource(e.target.value)}/></label>
        <label>{t('Reason for this historical record','या ऐतिहासिक नोंदीचे कारण')}<textarea maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label>
      </fieldset>}
      {admin&&<button className="button primary" disabled={busy||dirty||(!pending&&(!start||!end||reason.trim().length<5||source.trim().length<5||configurationVersion<1))} onClick={save}>{pending?t('Retry exact schedule record','हीच वेळापत्रक नोंद पुन्हा पाठवा'):t('Record effective schedule','लागू वेळापत्रक नोंदवा')}</button>}
      {pending&&<p role="status">{t('Keep this page open and retry the same record until confirmed.','पुष्टी मिळेपर्यंत हे पृष्ठ उघडे ठेवा आणि हीच नोंद पुन्हा पाठवा.')}</p>}
      {dirty&&<p>{t('Save or reload your configuration edits first.','आधी संरचनेतील बदल जतन करा किंवा पुन्हा मिळवा.')}</p>}
      <div className="table-scroll"><table><caption>{t('Recorded periods (UTC); start inclusive, end exclusive','नोंदवलेले कालावधी (UTC); सुरुवात समाविष्ट, शेवट वगळून')}</caption><thead><tr><th>{t('Period','कालावधी')}</th><th>{t('Source / version','स्रोत / आवृत्ती')}</th><th>{t('State','स्थिती')}</th></tr></thead><tbody>{history.entries.map(e=><tr key={e.id}><td>{e.effective_from}<br/>{e.effective_until}</td><td>{e.source_reference}<br/>v{e.configuration_version}<br/>{e.reason}</td><td>{e.revoked_at?t('Revoked','रद्द'):t('Recorded','नोंदवलेले')}{e.revocation_reason&&<p>{e.revocation_reason}</p>}</td></tr>)}</tbody></table></div>
      <button className="button secondary" onClick={()=>download(history,`water-schedule-history-${zone}.json`)}>{t('Export schedule history','वेळापत्रकाचा इतिहास निर्यात करा')}</button>
      {admin&&history.entries.some(e=>!e.revoked_at)&&<fieldset className="form-fields" disabled={busy||!!pending}>
        <legend>{t('Correct a recorded period','नोंदवलेला कालावधी दुरुस्त करा')}</legend>
        <label>{t('Record to revoke','रद्द करायची नोंद')}<select aria-label={t('Record to revoke','रद्द करायची नोंद')} value={revokeId} onChange={e=>setRevokeId(e.target.value)}><option value="">{t('Choose a record','नोंद निवडा')}</option>{history.entries.filter(e=>!e.revoked_at).map(e=><option key={e.id} value={e.id}>{e.source_reference} · {e.effective_from}</option>)}</select></label>
        <label>{t('Correction reason','दुरुस्तीचे कारण')}<textarea maxLength={2000} value={correction} onChange={e=>setCorrection(e.target.value)}/></label>
        <button className="button secondary" disabled={!revokeId||correction.trim().length<5} onClick={revoke}>{t('Revoke selected record','निवडलेली नोंद रद्द करा')}</button>
      </fieldset>}
    </>}
  </section>;
}
