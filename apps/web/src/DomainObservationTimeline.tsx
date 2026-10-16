import {CommandTimeline} from './CommandTimeline';
import {domainInfo, SignalChart} from './components';
import {download, type CivicCase} from './api';
import {caseInterval,domainReadings,overlaps,readingInterval,timelineBounds,type TimedReading,type TimeWindow,type TimelineSelection} from './timeline';
import {useInterfaceLanguage} from './uiLanguage';

export function DomainObservationTimeline({domain,rows,cases,assets,zone,window,selection,onChange}:{domain:string;rows:TimedReading[];cases:CivicCase[];assets:Array<{id:string;domain:string;zone_id:string}>;zone:string;window:TimeWindow|null;selection:TimelineSelection|null;onChange:(selection:TimelineSelection|null)=>void}){
  const mr=useInterfaceLanguage()==='mr';
  const source=domainReadings(rows,domain,assets,zone,null);
  const visible=domainReadings(rows,domain,assets,zone,window);
  const scoped=cases.filter(c=>c.domain===domain&&(zone==='all'||c.zone_id===zone));
  const bounds=timelineBounds(scoped,source);
  const ends=source.map(readingInterval).filter((v):v is TimeWindow=>v!==null).map(v=>v.end);
  return <section data-testid="domain-observation-timeline" aria-label={mr?'विभागाच्या मोजमापांचा कालावधी':'Domain observation timeline'}>
    <CommandTimeline bounds={bounds} window={window} selection={selection} onChange={onChange} readingEnd={ends.length?Math.max(...ends):null} caseCount={scoped.filter(c=>overlaps(caseInterval(c),window)).length} readingCount={visible.length} domainName={domainInfo(domain).name.toLowerCase()} domainSpecific/>
    <SignalChart data={visible} domain={domain} height={260} banded/>
    <button className="text-button" onClick={()=>download({domain,zone,window_utc:window?{start:new Date(window.start).toISOString(),end_exclusive:new Date(window.end).toISOString()}:null,observations:visible},`civicsignal-${domain}-visible-observations.json`)}>{mr?'दिसणारी मोजमापे निर्यात करा':'Export visible observations'}</button>
    <p className="helper">{mr?'आलेख व खालील प्रकरणांची यादी सामायिक क्षेत्र आणि कालावधी वापरतात. नियोजन, गुणवत्ता, अंदाज व इतर विश्लेषणे त्यांच्या प्रकाशित पूर्ण कालावधीतील निकालांप्रमाणे राहतात.':'This chart and the case list below use the shared zone and time window. Planning, quality, forecasts and other analytical summaries retain their published full-analysis scope.'}</p>
  </section>;
}
