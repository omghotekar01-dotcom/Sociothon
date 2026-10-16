import {WaterHistory, type ScheduleHistory} from './WaterHistory';
import {WaterGroupComparison} from './WaterGroupComparison';
import {useEffect, useRef, useState} from 'react';
import {AttachWaterReview, type WaterReviewSnapshot} from './WaterReviewEvidence';
import {type CivicCase} from './api';
import {api, dateTimeLocalToIso, dateTimeLocalValue, download, fmt, getDisplayTimezoneLabel, send} from './api';
import {ErrorBox, Loading, SectionHead} from './components';
import {useInterfaceLanguage} from './uiLanguage';

type SupplyWindow = {days:number[]; start_minute:number; end_minute:number; label:string};
type WaterConfig = {version:number; timezone:'Asia/Kolkata'|'UTC'; supply_windows:SupplyWindow[]; exceptions:SupplyWindow[]; outside_rate_lph:number; inlet_ids:string[]; outlet_ids:string[]; consumption_ids:string[]; meter_parents:Record<string,string>; boundary_confirmed:boolean};
type WaterAsset = {id:string;name:string;kind:string;provenance:string};
type Operations = {zone_id:string;schedule_history:ScheduleHistory;configuration:WaterConfig;assets:WaterAsset[];latest_end:string|null};
type ScheduleRow = {reading_id:string;asset_id:string;timestamp:string;status:string;explanation:string;volume_l:number|null};
type MeterTotal = {role:string;status:string;total_l:number|null;issues:string[];sources:string[]};
type Review = WaterReviewSnapshot & {configuration_version:number;window:{start:string;end_exclusive:string};schedule:ScheduleRow[];schedule_counts:Record<string,number>;balance:{status:string;unaccounted_l:number|null;inlet_l:number|null;outlet_l:number|null;consumption_l:number|null;meters:Record<string,MeterTotal>;issues:string[];interpretation:string}};
const message = (error:unknown) => error instanceof Error ? error.message : 'Unable to complete the request.';
const clock = (minutes:number) => `${String(Math.floor(minutes/60)%24).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;
const minutes = (value:string) => value.split(':').map(Number).reduce((h,m)=>h*60+m);

export function WaterOperations({onOpenCase}:{onOpenCase:(item:CivicCase)=>void}) {
  const mr = useInterfaceLanguage()==='mr';
  const t = (en:string, marathi:string) => mr ? marathi : en;
  const [zones,setZones] = useState<Array<{id:string;name:string}>>([]);
  const [zone,setZone] = useState('');
  const [admin,setAdmin] = useState(false);
  const [userId,setUserId]=useState('');
  const [value,setValue] = useState<Operations|null>(null);
  const [config,setConfig] = useState<WaterConfig|null>(null);
  const [reason,setReason] = useState('');
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [busy,setBusy] = useState(false);
  const [start,setStart] = useState('');
  const [end,setEnd] = useState('');
  const [storage,setStorage] = useState('');
  const [unmetered,setUnmetered] = useState('');
  const [note,setNote] = useState('');
  const [scheduleMode,setScheduleMode]=useState<'current'|'historical'>('current');
  const [result,setResult] = useState<Review|null>(null);
  const [revision,setRevision] = useState(0);
  const generation=useRef(0);
  useEffect(()=>{let active=true;api('/bootstrap').then(data=>{if(!active)return;setZones(data.zones);setAdmin(data.user.role==='admin');setUserId(data.user.id);setZone(data.zones[0]?.id||'')}).catch(e=>{if(active)setError(message(e))});return()=>{active=false}},[]);
  useEffect(()=>{
    const id=++generation.current;setValue(null);setConfig(null);setResult(null);setError('');setNotice('');setReason('');setStorage('');setUnmetered('');setNote('');setBusy(false);
    if(!zone)return;
    api('/water/zones/'+zone+'/operations').then((data:Operations)=>{if(id!==generation.current)return;setValue(data);setConfig(data.configuration);setEnd(data.latest_end?dateTimeLocalValue(data.latest_end):'');setStart(data.latest_end?dateTimeLocalValue(Date.parse(data.latest_end)-86400000):'')}).catch(e=>{if(id===generation.current)setError(message(e))});
    return()=>{generation.current++};
  },[zone,revision]);
  const update=(patch:Partial<WaterConfig>)=>{setConfig(c=>c?{...c,...patch}:c);setResult(null);setNotice('')};
  const dirty=!!value&&JSON.stringify(config)!==JSON.stringify(value.configuration);
  const save=async()=>{
    if(!config)return;const id=generation.current;setBusy(true);setError('');
    try{const saved=await send('/water/zones/'+zone+'/operations',{...config,reason},'PUT');if(id!==generation.current)return;setConfig(saved);setValue(v=>v?{...v,configuration:saved}:v);setReason('');setResult(null);setNotice(t('Configuration saved with an audit record.','बदल लेखापरीक्षण नोंदीसह जतन केले.'))}catch(e){if(id===generation.current)setError(message(e))}finally{if(id===generation.current)setBusy(false)}
  };
  const review=async()=>{
    if(!config)return;const id=generation.current;setBusy(true);setError('');setResult(null);
    try{const output=await send('/water/zones/'+zone+'/review',{start:dateTimeLocalToIso(start),end:dateTimeLocalToIso(end),configuration_version:config.version,storage_change_l:storage===''?null:Number(storage),authorized_unmetered_l:unmetered===''?null:Number(unmetered),accounting_note:note,schedule_mode:scheduleMode,history_version:scheduleMode==='historical'?value?.schedule_history.version:null});if(id===generation.current)setResult(output)}catch(e){if(id===generation.current)setError(message(e))}finally{if(id===generation.current)setBusy(false)}
  };
  const windowEditor=(key:'supply_windows'|'exceptions',title:string)=>{
    if(!config)return null;
    return <fieldset><legend>{title}</legend>{config[key].map((window,i)=>{
      const change=(patch:Partial<SupplyWindow>)=>update({[key]:config[key].map((w,j)=>i===j?{...w,...patch}:w)});
      return <div className="water-window" key={i}>
        <label>{t('Description','वर्णन')}<input value={window.label} maxLength={120} onChange={e=>change({label:e.target.value})}/></label>
        <label>{t('Start','सुरुवात')}<input type="time" value={clock(window.start_minute)} onChange={e=>change({start_minute:minutes(e.target.value)})}/></label>
        <label>{t('End (midnight is next day)','शेवट (मध्यरात्र म्हणजे पुढील दिवस)')}<input type="time" value={clock(window.end_minute)} onChange={e=>change({end_minute:e.target.value==='00:00'?1440:minutes(e.target.value)})}/></label>
        <div className="water-weekdays" role="group" aria-label={t('Days the window begins','वेळापत्रक सुरू होण्याचे दिवस')}>{(mr?['सोम','मंगळ','बुध','गुरु','शुक्र','शनि','रवि']:['Mon','Tue','Wed','Thu','Fri','Sat','Sun']).map((day,d)=><label className="checkbox-label" key={day}><input type="checkbox" checked={window.days.includes(d)} onChange={()=>change({days:window.days.includes(d)?window.days.filter(x=>x!==d):[...window.days,d].sort()})}/>{day}</label>)}</div>
        <button type="button" className="text-button" onClick={()=>update({[key]:config[key].filter((_,j)=>j!==i)})}>{t('Remove window','वेळ काढा')}</button>
      </div>;
    })}<button className="button secondary" type="button" disabled={config[key].length>=21} onClick={()=>update({[key]:[...config[key],{days:[0,1,2,3,4,5,6],start_minute:360,end_minute:480,label:key==='exceptions'?'Legitimate use':'Scheduled supply'}]})}>{t('Add window','वेळ जोडा')}</button></fieldset>;
  };
  const statuses:Record<string,string> = mr?{within_window:'नियोजित वेळेत',straddles_window:'वेळेची सीमा ओलांडते',review_outside_window:'नियोजित वेळेबाहेरील प्रवाह तपासा',below_review_threshold:'तपासणी मर्यादेपेक्षा कमी',history_missing:'ऐतिहासिक वेळापत्रक नाही',history_boundary:'ऐतिहासिक कालावधीची सीमा',data_quality:'माहितीची गुणवत्ता',not_configured:'वेळापत्रक नाही'}:{};
  const meters=value?.assets.filter(a=>a.kind.toLowerCase().includes('meter'))||[];
  return <section className="panel spaced water-operations" aria-labelledby="water-operations-title">
    <h2 id="water-operations-title">{t('Water operations review','पाणीपुरवठा आढावा')}</h2>
    <p>{t('Review supply context and account for water across a declared boundary. These checks do not confirm a leak or close a case.','नोंदवलेल्या क्षेत्रातील पाणीपुरवठ्याच्या वेळा व पाण्याचा हिशेब तपासा. या तपासण्या गळती सिद्ध करत नाहीत किंवा प्रकरण बंद करत नाहीत.')}</p>
    <label>{t('Service zone','सेवा क्षेत्र')}<select value={zone} onChange={e=>setZone(e.target.value)}>{zones.map(z=><option key={z.id} value={z.id}>{z.name}</option>)}</select></label>
    {error&&<ErrorBox error={error} retry={()=>setRevision(r=>r+1)}/>}<p role="status">{notice}</p>
    {!value&&!error&&<Loading/>}
    {value&&config&&<>
      <details><summary>{t('Supply schedule and accounting boundary','पुरवठा वेळापत्रक व हिशेबाची सीमा')} · {t('Version','आवृत्ती')} {config.version}</summary>
        <fieldset disabled={!admin||busy} className="form-fields">
          <label>{t('Schedule timezone','वेळापत्रकाचा प्रमाणवेळ')}<select value={config.timezone} onChange={e=>update({timezone:e.target.value as WaterConfig['timezone']})}><option>Asia/Kolkata</option><option>UTC</option></select></label>
          {windowEditor('supply_windows',t('Supply windows','पुरवठ्याच्या वेळा'))}
          {windowEditor('exceptions',t('Declared recurring legitimate-use exceptions','नोंदवलेले नियमित वैध वापराचे अपवाद'))}
          <label>{t('Outside-window review threshold · litres/hour','पुरवठ्याच्या वेळेबाहेरील तपासणी मर्यादा · लिटर/तास')}<input type="number" min="0" max="1000000000" value={config.outside_rate_lph} onChange={e=>update({outside_rate_lph:Number(e.target.value)})}/></label>
          <div className="table-scroll"><table><caption>{t('Choose each boundary meter role. Parent relationships describe metering containment, not hydraulic flow.','प्रत्येक मीटरची भूमिका निवडा. मूळ मीटरचे नाते मोजमापाची व्याप्ती दर्शवते; दाब किंवा प्रवाहाचे मॉडेल नाही.')}</caption><thead><tr><th>{t('Meter','मीटर')}</th><th>{t('Role','भूमिका')}</th><th>{t('Parent meter','मूळ मीटर')}</th></tr></thead><tbody>{meters.map(a=>{
            const role=(['inlet_ids','outlet_ids','consumption_ids'] as const).find(k=>config[k].includes(a.id))||'';
            return <tr key={a.id}><td>{a.name}<small> · {a.provenance}</small></td><td><select aria-label={'Accounting role '+a.name} value={role} onChange={e=>{const patch={inlet_ids:config.inlet_ids.filter(id=>id!==a.id),outlet_ids:config.outlet_ids.filter(id=>id!==a.id),consumption_ids:config.consumption_ids.filter(id=>id!==a.id)};if(e.target.value)patch[e.target.value as keyof typeof patch].push(a.id);update(patch)}}><option value="">{t('Not included','समाविष्ट नाही')}</option><option value="inlet_ids">{t('Inlet','आवक')}</option><option value="outlet_ids">{t('Export / outlet','बाहेर जाणारे')}</option><option value="consumption_ids">{t('Consumption','वापर')}</option></select></td><td><select aria-label={'Parent meter '+a.name} value={config.meter_parents[a.id]||''} onChange={e=>{const parents={...config.meter_parents};if(e.target.value)parents[a.id]=e.target.value;else delete parents[a.id];update({meter_parents:parents})}}><option value="">{t('None recorded','नोंद नाही')}</option>{meters.filter(m=>m.id!==a.id).map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></td></tr>;
          })}</tbody></table></div>
          <label className="checkbox-label"><input type="checkbox" checked={config.boundary_confirmed} onChange={e=>update({boundary_confirmed:e.target.checked})}/>{t('I reviewed boundary completeness and recorded the known meter hierarchy. Empty outlet or consumption groups mean none at this boundary.','क्षेत्राची पूर्णता आणि ज्ञात मीटरची रचना तपासली आहे. रिकामा गट म्हणजे या सीमेवर तसा प्रवाह नाही.')}</label>
          <label>{t('Reason and boundary assumptions','कारण व क्षेत्राविषयी गृहितके')}<textarea value={reason} maxLength={2000} onChange={e=>setReason(e.target.value)}/></label>
          <button className="button primary" disabled={!dirty||reason.trim().length<5} onClick={save}>{t('Save configuration','संरचना जतन करा')}</button>
        </fieldset>
        {!admin&&<p className="helper">{t('An administrator can update this configuration.','प्रशासक ही संरचना बदलू शकतो.')}</p>}
      </details>
      <div className="form-fields"><div className="water-form-grid">
        <label>{t('Window start','कालावधीची सुरुवात')} · {getDisplayTimezoneLabel()}<input type="datetime-local" value={start} onChange={e=>{setStart(e.target.value);setResult(null)}}/></label>
        <label>{t('Window end, exclusive','कालावधीचा शेवट, वगळून')} · {getDisplayTimezoneLabel()}<input type="datetime-local" value={end} onChange={e=>{setEnd(e.target.value);setResult(null)}}/></label>
        <label>{t('Storage increase · litres (negative means decrease)','साठ्यातील वाढ · लिटर (घट असल्यास ऋण संख्या)')}<input type="number" value={storage} placeholder={t('Unknown','अज्ञात')} onChange={e=>{setStorage(e.target.value);setResult(null)}}/></label>
        <label>{t('Authorized unmetered use · litres','मीटरबाहेरील अधिकृत वापर · लिटर')}<input type="number" min="0" value={unmetered} placeholder={t('Unknown','अज्ञात')} onChange={e=>{setUnmetered(e.target.value);setResult(null)}}/></label>
      </div><label>{t('Source and assumptions for supplied accounting values','दिलेल्या हिशेबाच्या आकड्यांचा स्रोत व गृहितके')}<textarea value={note} maxLength={2000} onChange={e=>{setNote(e.target.value);setResult(null)}}/></label>
      <p className="helper">{t('Leave unknown quantities blank. Enter zero only when supported. A maximum of 31 days can be reviewed; no missing interval volume is estimated.','अज्ञात प्रमाण रिकामे ठेवा. पुरावा असल्यासच शून्य लिहा. जास्तीत जास्त ३१ दिवस तपासता येतात; गहाळ मोजमापाचा अंदाज भरला जात नाही.')}</p>
      {dirty&&<p role="status">{t('Save configuration changes before reviewing readings.','मोजमाप तपासण्यापूर्वी संरचनेतील बदल जतन करा.')}</p>}
      <label>{t('Schedule context to review','तपासण्यासाठी वेळापत्रकाचा संदर्भ')}<select aria-label={t('Schedule context to review','तपासण्यासाठी वेळापत्रकाचा संदर्भ')} disabled={busy} value={scheduleMode} onChange={e=>{setScheduleMode(e.target.value as typeof scheduleMode);setResult(null)}}><option value="current">{t('Current configuration (not historical proof)','सध्याची संरचना (ऐतिहासिक पुरावा नाही)')}</option><option value="historical">{t('Recorded effective schedules','नोंदवलेली लागू वेळापत्रके')}</option></select></label>
      <button className="button primary" disabled={busy||dirty||!start||!end} onClick={review}>{busy?t('Working…','प्रक्रिया सुरू…'):t('Review water observations','पाण्याची मोजमापे तपासा')}</button></div>
      {result&&<div aria-live="polite">
        <SectionHead title={t('Accounting result','हिशेबाचा निकाल')}/>
        <p>{t('Unaccounted volume','हिशेबात न आलेले प्रमाण')}: <strong>{result.balance.unaccounted_l===null?t('Unavailable','उपलब्ध नाही'):fmt(result.balance.unaccounted_l,2)+' L'}</strong></p>
        <p className="helper">{t('Signed accounting residual; not confirmed leakage or savings. Storage and unmetered-use values are supplied by the reviewer, not independently verified.','हा हिशेबातील फरक आहे; सिद्ध झालेली गळती किंवा बचत नाही. साठा व मीटरबाहेरील वापराची माहिती तपासणाऱ्याने दिली आहे; स्वतंत्र पडताळणी झालेली नाही.')}</p>
        <ul>{result.balance.issues.map(issue=><li key={issue}>{issue}</li>)}</ul>
        <div className="table-scroll"><table><thead><tr><th>{t('Meter','मीटर')}</th><th>{t('Volume · L','प्रमाण · लिटर')}</th><th>{t('Coverage / issues','माहितीची व्याप्ती / अडचणी')}</th></tr></thead><tbody>{Object.entries(result.balance.meters).map(([id,m])=><tr key={id}><td>{value.assets.find(a=>a.id===id)?.name||id}</td><td>{m.total_l===null?'—':fmt(m.total_l,2)}</td><td>{m.issues.length?m.issues.join(' '):t('Complete selected window','निवडलेल्या कालावधीची पूर्ण माहिती')}</td></tr>)}</tbody></table></div>
        <SectionHead title={t('Schedule context','वेळापत्रकाचा संदर्भ')}/>
        <p className="helper">{result.schedule_mode==='historical'?t('Using recorded effective schedules. Missing history remains unknown; accounting still uses the reviewed current meter boundary.','नोंदवलेली लागू वेळापत्रके वापरली आहेत. इतिहासातील रिकामा कालावधी अज्ञात राहतो; हिशेबासाठी तपासलेली सध्याची मीटर सीमा वापरली जाते.'):t('Using the current configuration; this does not establish historical supply.','सध्याची संरचना वापरली आहे; त्यामुळे ऐतिहासिक पुरवठा सिद्ध होत नाही.')}</p>
        <p>{Object.entries(result.schedule_counts).map(([state,n])=>`${statuses[state]||state.replaceAll('_',' ')}: ${n}`).join(' · ')||t('No observations in this window.','या कालावधीत मोजमापे नाहीत.')}</p>
        <div className="table-scroll"><table><caption>{t('First 100 observations. Export includes the complete review. Intervals crossing a schedule boundary are not split into invented volumes.','पहिली १०० मोजमापे. निर्यातीमध्ये पूर्ण आढावा आहे. वेळेची सीमा ओलांडणाऱ्या मोजमापांचे काल्पनिक विभाजन केले जात नाही.')}</caption><thead><tr><th>{t('Observation (UTC)','मोजमाप (UTC)')}</th><th>{t('Meter','मीटर')}</th><th>{t('Volume · L','प्रमाण · लिटर')}</th><th>{t('Review state','तपासणी स्थिती')}</th></tr></thead><tbody>{result.schedule.slice(0,100).map(r=><tr key={r.reading_id}><td>{r.timestamp}</td><td>{r.asset_id}</td><td>{r.volume_l===null?'—':fmt(r.volume_l,2)}</td><td title={r.explanation}>{statuses[r.status]||r.status.replaceAll('_',' ')}</td></tr>)}</tbody></table></div>
        <button className="button secondary" onClick={()=>download(result,'water-review-'+zone+'.json')}>{t('Export review JSON','आढावा JSON निर्यात करा')}</button>
      </div>}
      <AttachWaterReview key={userId+':'+zone} snapshot={result} userId={userId} zone={zone} onOpenCase={onOpenCase}/>
      <WaterHistory key={zone} zone={zone} history={value.schedule_history} configurationVersion={config.version} admin={admin} dirty={dirty} latestEnd={value.latest_end} onChange={history=>{setValue(v=>v?.zone_id===zone?{...v,schedule_history:history}:v);setResult(null)}}/>
      <WaterGroupComparison key={zone+'-'+config.version} zone={zone} configuration={config} assets={meters} latestEnd={value.latest_end} dirty={dirty}/>
    </>}
  </section>;
}
