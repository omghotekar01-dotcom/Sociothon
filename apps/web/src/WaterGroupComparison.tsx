import {useState} from 'react';
import {dateTimeLocalToIso, dateTimeLocalValue, download, fmt, getDisplayTimezoneLabel, send} from './api';
import {useInterfaceLanguage} from './uiLanguage';
import {classifyWaterFollowup} from './waterFollowup';

type Config={version:number;inlet_ids:string[];outlet_ids:string[];consumption_ids:string[];boundary_confirmed:boolean};
type Total={total_l:number|null;issues:string[]};
type Comparison={status:string;before_total_l:number|null;after_total_l:number|null;observed_reduction_l:number|null;issues:string[];meters:Record<string,{before:Total;after:Total}>;snapshot_hash:string};
export function WaterGroupComparison({zone,configuration,assets,latestEnd,dirty}:{zone:string;configuration:Config;assets:Array<{id:string;name:string}>;latestEnd:string|null;dirty:boolean}){
  const mr=useInterfaceLanguage()==='mr';const t=(en:string,marathi:string)=>mr?marathi:en;
  const [open,setOpen]=useState(false);const [role,setRole]=useState<'inlet_ids'|'outlet_ids'|'consumption_ids'>('consumption_ids');
  const [selected,setSelected]=useState<string[]>([]);const [confirmed,setConfirmed]=useState(false);const [note,setNote]=useState('');
  const [windows,setWindows]=useState(()=>{const end=latestEnd?Date.parse(latestEnd):Date.now();return {before_start:dateTimeLocalValue(end-8*86400000),before_end:dateTimeLocalValue(end-7*86400000),after_start:dateTimeLocalValue(end-86400000),after_end:dateTimeLocalValue(end)}});
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [result,setResult]=useState<Comparison|null>(null);
  const labels={before_start:t('Before start','पूर्वीची सुरुवात'),before_end:t('Before end (exclusive)','पूर्वीचा शेवट (वगळून)'),after_start:t('After start','नंतरची सुरुवात'),after_end:t('After end (exclusive)','नंतरचा शेवट (वगळून)')};
  const compare=async()=>{
    setBusy(true);setError('');setResult(null);
    try{setResult(await send(`/water/zones/${zone}/impact-comparison`,{configuration_version:configuration.version,meter_ids:selected,...Object.fromEntries(Object.entries(windows).map(([k,v])=>[k,dateTimeLocalToIso(v)])),independent_meters_confirmed:confirmed,context_note:note}))}catch(e){setError(e instanceof Error?e.message:'Unable to compare meters')}finally{setBusy(false)}
  };
  const volume=(v:number|null)=>v===null?t('Unavailable','उपलब्ध नाही'):fmt(v,2)+' L';
  return <section className="water-extension" aria-label={t('Multi-meter impact comparison','अनेक मीटरची परिणाम तुलना')}>
    <button className="button secondary" aria-expanded={open} onClick={()=>setOpen(!open)}>{t('Compare multiple meters','अनेक मीटरची तुलना करा')}</button>
    {open&&<>
      <p>{t('Compare the same non-overlapping meters in equal windows, at least 24 hours long and whole weeks apart. Every meter needs complete readings. This compares recorded volume, not proven savings.','समान, एकमेकांत न मोजल्या जाणाऱ्या मीटरची किमान २४ तासांच्या समतुल्य कालावधीत, पूर्ण आठवड्यांच्या अंतराने तुलना करा. प्रत्येक मीटरची पूर्ण मोजमापे आवश्यक आहेत. ही नोंदवलेल्या प्रमाणाची तुलना आहे; सिद्ध बचत नाही.')}</p>
      {!configuration.boundary_confirmed&&<p role="status">{t('Ask an administrator to configure and confirm the meter boundary above.','वरची मीटर सीमा प्रशासकाकडून निश्चित करून घ्या.')}</p>}
      {error&&<p role="alert">{error}</p>}
      <fieldset className="form-fields" disabled={busy||dirty||!configuration.boundary_confirmed} onChange={()=>setResult(null)}>
        <legend>{t('Comparison inputs','तुलनेची माहिती')} · {getDisplayTimezoneLabel()}</legend>
        <label>{t('Meter accounting role','मीटरची हिशेबातील भूमिका')}<select aria-label={t('Meter accounting role','मीटरची हिशेबातील भूमिका')} value={role} onChange={e=>{setRole(e.target.value as typeof role);setSelected([]);setConfirmed(false)}}><option value="inlet_ids">{t('Inlets','आवक')}</option><option value="outlet_ids">{t('Outlets','जावक')}</option><option value="consumption_ids">{t('Consumption','वापर')}</option></select></label>
        <div role="group" aria-label={t('Meters to compare','तुलनेसाठी मीटर')}>{configuration[role].map(id=><label className="checkbox-label" key={id}><input type="checkbox" checked={selected.includes(id)} onChange={()=>{setSelected(selected.includes(id)?selected.filter(v=>v!==id):[...selected,id]);setConfirmed(false)}}/>{assets.find(a=>a.id===id)?.name||id}</label>)}</div>
        {Object.entries(windows).map(([key,value])=><label key={key}>{labels[key as keyof typeof labels]}<input type="datetime-local" value={value} onChange={e=>setWindows({...windows,[key]:e.target.value})}/></label>)}
        <label>{t('Comparison assumptions and supply context','तुलनेची गृहितके व पुरवठ्याचा संदर्भ')}<textarea maxLength={2000} value={note} onChange={e=>setNote(e.target.value)}/></label>
        <label className="checkbox-label"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>{t('I checked that selected meters measure separate volumes and reviewed supply, demand and storage changes.','निवडलेले मीटर वेगवेगळे प्रमाण मोजतात याची तपासणी केली व पुरवठा, मागणी आणि साठ्यातील बदल तपासले.')}</label>
        <button className="button primary" disabled={!selected.length||!confirmed||note.trim().length<5||Object.values(windows).some(v=>!v)} onClick={compare}>{t('Compare selected meters','निवडलेल्या मीटरची तुलना करा')}</button>
      </fieldset>
      {result&&<div aria-live="polite" data-testid="water-group-comparison-result">
        <h3>{t('Recorded volume comparison','नोंदवलेल्या प्रमाणाची तुलना')}</h3>
        {(()=>{const assessment=classifyWaterFollowup(result);return <div className={'water-followup-status '+assessment.category} role="status">
          <strong>{assessment.category==='insufficient'?t('Insufficient evidence','अपुरी माहिती'):assessment.category==='observed_reduction'?t('Observed improvement in recorded volume','नोंदवलेल्या प्रमाणात घट'):assessment.category==='increased'?t('No observed improvement','नोंदवलेली सुधारणा नाही'):t('No clear change','स्पष्ट बदल नाही')}</strong>
          <p>{assessment.reason}</p>
        </div>})()}

        <p>{t('Before','पूर्वी')}: {volume(result.before_total_l)} · {t('After','नंतर')}: {volume(result.after_total_l)}</p>
        <p>{t('Observed reduction (negative means increase)','नोंदवलेली घट (ऋण म्हणजे वाढ)')}: <strong>{volume(result.observed_reduction_l)}</strong></p>
        <ul>{result.issues.map(issue=><li key={issue}>{issue}</li>)}</ul>
        <div className="table-scroll"><table><thead><tr><th>{t('Meter','मीटर')}</th><th>{t('Before','पूर्वी')}</th><th>{t('After','नंतर')}</th><th>{t('Coverage issues','माहितीतील त्रुटी')}</th></tr></thead><tbody>{Object.entries(result.meters).map(([id,m])=><tr key={id}><td>{assets.find(a=>a.id===id)?.name||id}</td><td>{volume(m.before.total_l)}</td><td>{volume(m.after.total_l)}</td><td>{[...m.before.issues,...m.after.issues].join(' ')||t('Complete windows','पूर्ण कालावधी')}</td></tr>)}</tbody></table></div>
        <p className="helper">{t('Human review required. This result cannot close a case and does not establish leakage or causal savings. Export includes the exact inputs, source readings, current meter boundary and recorded schedule history.','मानवी पुनरावलोकन आवश्यक. या निकालाने प्रकरण बंद होत नाही किंवा गळती अथवा कारणात्मक बचत सिद्ध होत नाही. निर्यातीत अचूक इनपुट, मोजमापे, सध्याची मीटर सीमा व वेळापत्रकाचा इतिहास आहे.')}</p>
        <button className="button secondary" onClick={()=>download(result,`water-group-comparison-${zone}.json`)}>{t('Export meter comparison','मीटर तुलना निर्यात करा')}</button>
      </div>}
    </>}
  </section>;
}
