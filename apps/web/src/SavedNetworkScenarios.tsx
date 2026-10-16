import {useEffect,useState} from 'react';
import {api,send} from './api';
import {useInterfaceLanguage} from './uiLanguage';

export type NetworkScenarioInputs={source:string;target:string;closed_edges:string[];zone_id:string|null};
type Saved={id:string;version:number;name:string;reason:string;archived:boolean;topology_changed:boolean;inputs:NetworkScenarioInputs};
type Submission={name:string;reason:string;inputs:NetworkScenarioInputs;configuration_hash:string;idempotency_key:string};
export function SavedNetworkScenarios({inputs,configurationHash,onLoad}:{inputs:NetworkScenarioInputs;configurationHash:string;onLoad:(inputs:NetworkScenarioInputs)=>void}){
  const mr=useInterfaceLanguage()==='mr';const t=(en:string,marathi:string)=>mr?marathi:en;
  const [items,setItems]=useState<Saved[]>([]);const [selected,setSelected]=useState('');const [name,setName]=useState('');const [reason,setReason]=useState('');const [actionReason,setActionReason]=useState('');
  const [error,setError]=useState('');const [notice,setNotice]=useState('');const [busy,setBusy]=useState(false);const [revision,setRevision]=useState(0);const [includeArchived,setIncludeArchived]=useState(false);const [pending,setPending]=useState<Submission|null>(null);
  useEffect(()=>{let active=true;api('/network/scenarios').then((rows:Saved[])=>{if(active)setItems(rows)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[revision]);
  const item=items.find(row=>row.id===selected);
  const save=async()=>{
    const body=pending||{name,reason,inputs:{...inputs,closed_edges:[...inputs.closed_edges]},configuration_hash:configurationHash,idempotency_key:crypto.randomUUID()};
    setPending(body);setBusy(true);setError('');setNotice('');
    try{const result=await send('/network/scenarios',body);if(typeof result.id!=='string')throw new Error('Confirmation unavailable');setPending(null);setSelected(result.id);setName('');setReason('');setRevision(v=>v+1);setNotice(t('Named scenario saved.','नाव दिलेला प्रयोग जतन केला.'))}catch(e){setError(e instanceof Error?e.message:'Unable to save scenario')}finally{setBusy(false)}
  };
  const load=async()=>{if(!item)return;setBusy(true);setError('');setNotice('');try{const result=await api('/network/scenarios/'+item.id);onLoad(result.inputs);setNotice(t('Saved scenario loaded into this sandbox.','जतन केलेला प्रयोग या नमुन्यात उघडला.'))}catch(e){setError(e instanceof Error?e.message:'Unable to load scenario')}finally{setBusy(false)}};
  const archive=async()=>{if(!item)return;setBusy(true);setError('');setNotice('');try{await send('/network/scenarios/'+item.id+'/archive',{version:item.version,archived:!item.archived,reason:actionReason});setRevision(v=>v+1);setSelected('');setActionReason('');setNotice(t('Scenario archive state updated.','प्रयोगाची संग्रहित स्थिती बदलली.'))}catch(e){setError(e instanceof Error?e.message:'Unable to update scenario')}finally{setBusy(false)}};
  return <section className="panel spaced saved-network-scenarios" aria-label={t('Saved network scenarios','जतन केलेले जाळ्याचे प्रयोग')}>
    <h2>{t('Saved network scenarios','जतन केलेले जाळ्याचे प्रयोग')}</h2>
    <p className="helper">{t('Save source, destination, zone and simulated pipe closures to your account. Loading rechecks permissions and the network fingerprint. It never changes the configured network or case decisions.','स्रोत, गंतव्य, क्षेत्र आणि नमुना पाइप बंद करण्याची स्थिती आपल्या खात्यात जतन करा. उघडताना परवानगी व जाळ्याची ओळख पुन्हा तपासली जाते. मूळ जाळे किंवा प्रकरणांचे निर्णय बदलत नाहीत.')}</p>
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <fieldset className="form-fields" disabled={busy||!!pending}>
      <legend>{t('Save the current experiment','सध्याचा प्रयोग जतन करा')}</legend>
      <label>{t('Scenario name','प्रयोगाचे नाव')}<input maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label>
      <label>{t('Scenario purpose','प्रयोगाचा उद्देश')}<textarea maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)}/></label>
    </fieldset>
    <button className="button primary" disabled={busy||(!pending&&(name.trim().length<3||reason.trim().length<5))} onClick={save}>{pending?t('Retry exact scenario save','हाच प्रयोग पुन्हा जतन करा'):t('Save named scenario','नाव दिलेला प्रयोग जतन करा')}</button>
    {pending&&<><p>{t('Keep this page open until confirmation. Retrying keeps the original selections and cannot create a second record.','पुष्टी मिळेपर्यंत पृष्ठ उघडे ठेवा. पुन्हा पाठवताना मूळ निवड कायम राहते व दुसरी प्रत तयार होत नाही.')}</p><button className="text-button" disabled={busy} onClick={()=>setPending(null)}>{t('Discard pending save reference','प्रलंबित जतन संदर्भ काढा')}</button></>}
    <label className="checkbox-label"><input type="checkbox" checked={includeArchived} onChange={e=>{setIncludeArchived(e.target.checked);setSelected('')}}/>{t('Include archived scenarios','संग्रहित प्रयोग दाखवा')}</label>
    <label>{t('Saved experiment','जतन केलेला प्रयोग')}<select aria-label={t('Saved experiment','जतन केलेला प्रयोग')} value={selected} disabled={busy} onChange={e=>setSelected(e.target.value)}><option value="">{t('Choose a saved scenario','जतन केलेला प्रयोग निवडा')}</option>{items.filter(row=>includeArchived||!row.archived).map(row=><option key={row.id} value={row.id}>{row.name}{row.archived?' · '+t('Archived','संग्रहित'):''}{row.topology_changed?' · '+t('Network changed','जाळे बदलले'):''}</option>)}</select></label>
    <div className="form-actions"><button className="button secondary" disabled={busy||!item||item.archived||item.topology_changed} onClick={load}>{t('Load selected scenario','निवडलेला प्रयोग उघडा')}</button><button className="button secondary" disabled={busy} onClick={()=>{setError('');setRevision(v=>v+1)}}>{t('Refresh saved scenarios','जतन केलेले प्रयोग पुन्हा मिळवा')}</button></div>
    {item&&<>
      <p>{item.reason}</p>
      {item.topology_changed&&<p role="status">{t('The network or your scope changed. Review the current topology and save a new experiment.','जाळे किंवा आपली व्याप्ती बदलली. सध्याचे जाळे तपासा व नवीन प्रयोग जतन करा.')}</p>}
      <label>{t('Archive or restore reason','संग्रहित किंवा पुनर्संचयित करण्याचे कारण')}<textarea disabled={busy} maxLength={2000} value={actionReason} onChange={e=>setActionReason(e.target.value)}/></label>
      <button className="button secondary" disabled={busy||actionReason.trim().length<5} onClick={archive}>{item.archived?t('Restore selected scenario','निवडलेला प्रयोग पुनर्संचयित करा'):t('Archive selected scenario','निवडलेला प्रयोग संग्रहित करा')}</button>
    </>}
  </section>;
}
