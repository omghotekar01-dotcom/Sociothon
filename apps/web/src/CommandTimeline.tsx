import {ChevronLeft, ChevronRight, Clock3, RotateCcw} from 'lucide-react';
import {date, getDisplayTimezoneLabel} from './api';
import {HOUR, type TimeWindow, type TimelineSelection} from './timeline';

export function CommandTimeline({bounds,window,selection,onChange,readingEnd,caseCount,readingCount,domainName='water',domainSpecific=false}: {
  bounds: TimeWindow | null; window: TimeWindow | null; selection: TimelineSelection | null;
  onChange: (selection: TimelineSelection | null) => void;
  readingEnd: number | null; caseCount: number; readingCount: number; domainName?:string; domainSpecific?:boolean;
}) {
  if (!bounds) return <section className="panel command-timeline"><p>No dated observations are available for this timeline.</p></section>;
  const end = selection?.end ?? window?.end ?? bounds.end;
  const hours = selection?.hours ?? (window ? (window.end-window.start)/HOUR : 24);
  const choices = [6,24,72,168,720];
  const span = choices.includes(hours) ? hours : 24;
  const move = (next: number) => onChange({end: Math.max(bounds.start + HOUR, Math.min(bounds.end, next)), hours: span});
  const format = (value: number) => date(new Date(value).toISOString());
  return <section className="panel command-timeline" aria-label="Observation timeline">
    <div className="timeline-heading"><div><span className="eyebrow"><Clock3 size={13}/> OBSERVATION TIMELINE</span><h2>{window ? 'Review a shared time window' : 'All recorded observations'}</h2></div><button className="button secondary" disabled={!window} onClick={()=>onChange(null)}><RotateCcw size={14}/>Reset timeline</button></div>
    <div className="timeline-controls"><button className="button secondary" aria-label="Move timeline back one hour" disabled={end<=bounds.start+HOUR} onClick={()=>move(end-HOUR)}><ChevronLeft size={16}/></button><label className="timeline-slider-label">Window end ({getDisplayTimezoneLabel()})<input type="range" aria-label="Observation window end" min={bounds.start+HOUR} max={bounds.end} step={HOUR} value={Math.max(bounds.start+HOUR,Math.min(bounds.end,end))} aria-valuetext={format(end)+' '+getDisplayTimezoneLabel()} onChange={e=>move(Number(e.target.value))}/></label><button className="button secondary" aria-label="Move timeline forward one hour" disabled={end>=bounds.end} onClick={()=>move(end+HOUR)}><ChevronRight size={16}/></button><label>Window length<select aria-label="Observation window length" value={span} onChange={e=>onChange({end,hours:Number(e.target.value)})}>{choices.map(n=><option key={n} value={n}>{n} hours</option>)}</select></label></div>
    <div className="timeline-summary"><p role="status" data-testid="timeline-summary">{window?`${format(window.start)} → ${format(window.end)} ${getDisplayTimezoneLabel()}`:`${format(bounds.start)} → ${format(bounds.end)} ${getDisplayTimezoneLabel()}`}<br/><strong>{caseCount} cases · {readingCount} {domainName} {domainSpecific?'observations':'intervals'} in view</strong></p><button className="text-button" disabled={readingEnd===null} onClick={()=>readingEnd!==null&&onChange({end:readingEnd,hours:24})}>Latest {domainName} readings</button></div>
    <p className="helper">{domainSpecific?'This domain chart and case list share the selected window and zone. Other domains do not inherit these readings.':'Map, list and water chart share this window and zone. Water telemetry is a reference series; other domains do not inherit its readings.'} Analytical events use observation times; reports use submission times. Case statuses are current. Interval ends are exclusive.</p>
  </section>;
}
