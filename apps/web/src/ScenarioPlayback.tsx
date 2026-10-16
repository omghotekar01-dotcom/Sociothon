import {useEffect, useMemo, useRef, useState} from 'react';
import {Pause, Play, RotateCcw, SkipBack, SkipForward} from 'lucide-react';
import {api, date, getDisplayTimezoneLabel, send, type CivicCase} from './api';
import {Badge, CaseRow, Empty, ErrorBox, SectionHead, SignalChart} from './components';
import {playbackFrames, reconcilePlayback, visiblePlaybackRows, PLAYBACK_SPEEDS} from './replayState';

type RecordedEvent = {id:string,title:string,asset_id:string,severity:string,start:string|null,end:string|null,available_at:string,availability_basis:string,source:string,interval_count:number|null,estimated_excess:number|null,unit:string|null,case_id:string|null};
type RecordedBranch = {observations:number,missing_observations:number,flagged_observations:number,asset_ids:string[],events:RecordedEvent[]};
type ServerPlayback = {job_id:string,updated_at:string,frame_timestamps:string[],cursor:number,status:'playing'|'paused',speed:number,version:number,analysis?:{as_of:string|null,completed:boolean,baseline:RecordedBranch,modified:RecordedBranch}};

export function ScenarioPlayback({job,cases,select}:{job:any,cases:CivicCase[],select:(c:CivicCase)=>void}) {
  const result = job.result;
  const [savedPlayback,setPlayback] = useState<ServerPlayback|null>(null);
  const playback = savedPlayback && savedPlayback.job_id===job.id ? savedPlayback : null;
  const [seekCursor,setSeekCursor] = useState(0);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const currentJob = useRef(job.id);
  currentJob.current=job.id;
  const accept = (state:ServerPlayback) => setPlayback(current=>reconcilePlayback(current,state,currentJob.current));
  const load = async () => {
    try {accept(await api(`/jobs/${job.id}/playback`));setError('')}
    catch (e:any) {setError(e.message||'Could not load the stored scenario clock.')}
  };
  useEffect(()=>{
    let active=true;
    api(`/jobs/${job.id}/playback`).then((state)=>{if(active){setPlayback(current=>reconcilePlayback(current,state,job.id));setError('')}}).catch((e:any)=>{if(active)setError(e.message||'Could not load the stored scenario clock.')});
    return()=>{active=false};
  },[job.id]);
  useEffect(()=>{
    if(playback?.status!=='playing')return;
    let active=true;
    let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{
      try{const state=await api(`/jobs/${job.id}/playback`);if(active)setPlayback(current=>reconcilePlayback(current,state,job.id))}
      catch(e:any){if(active)setError(e.message||'Playback status could not be refreshed.')}
      finally{if(active)timer=setTimeout(poll,250)}
    };
    timer=setTimeout(poll,250);
    return()=>{active=false;clearTimeout(timer)};
  },[job.id,playback?.status]);
  useEffect(()=>setSeekCursor(playback?.cursor??0),[playback?.cursor]);
  const control = async(action:string,value?:number)=>{
    if(!playback)return;
    setBusy(true);setError('');
    const body:any={action,version:playback.version};
    if(action==='seek')body.cursor=value;
    if(action==='speed')body.speed=value;
    try {accept(await send(`/jobs/${job.id}/playback`,body));}
    catch(e:any){setError(e.message||'Playback control failed.');if(e.status===409)await load()}
    finally{setBusy(false)}
  };
  const computedFrames=useMemo(()=>playbackFrames(result.baseline?.series||[],result.series||[],result.metadata?.clock),[result]);
  const frames=playback?.frame_timestamps||[];
  const scheduleMismatch=!!playback&&(frames.length!==computedFrames.length||frames.some((stamp,index)=>Date.parse(stamp)!==computedFrames[index]));
  const last=Math.max(0,frames.length-1);
  const cursor=Math.max(0,Math.min(last,playback?.cursor??0));
  const timestamp=frames[cursor]?Date.parse(frames[cursor]):undefined;
  const complete=frames.length>0&&cursor===last;
  const baseline=visiblePlaybackRows(result.baseline?.series||[],timestamp);
  const modified=visiblePlaybackRows(result.series||[],timestamp);
  const domain=result.metadata?.domain||job.parameters.domain;
  const runCases=cases.filter(c=>(result.case_ids||[]).includes(c.id));
  const analysis=playback?.analysis;
  return <div className="scenario-playback" data-testid="scenario-playback">
    <section className="panel playback-controls" aria-label="Scenario playback controls">
      <SectionHead eyebrow="RECORDED SIMULATION" title="Play the computed scenario"><Badge type="violet">{playback?.status==='playing'?'Playing':complete?'Playback complete':'Paused'}</Badge></SectionHead>
      {error&&<ErrorBox error={error} retry={load}/>}
      {scheduleMismatch&&<ErrorBox error="The saved playback clock does not match this scenario’s recorded timestamps. Playback controls are disabled until the result is reloaded." retry={load}/>}
      {!playback&&<p className="helper" role="status">Loading the persisted scenario clock…</p>}
      <div className="playback-clock" role="status" data-testid="playback-clock"><strong>{timestamp===undefined?'No recorded timestamps':date(new Date(timestamp).toISOString())+' '+getDisplayTimezoneLabel()}</strong><span>Frame {frames.length?cursor+1:0} of {frames.length} · {baseline.length} baseline / {modified.length} modified observations</span></div>
      <div className="playback-buttons"><button className="button secondary" disabled={!playback||busy||scheduleMismatch||cursor===0} aria-label="Previous simulation frame" onClick={()=>control('step_back')}><SkipBack size={15}/></button><button className="button primary" disabled={!playback||busy||scheduleMismatch||frames.length<2||complete&&playback.status!=='playing'} onClick={()=>control(playback?.status==='playing'?'pause':'play')}>{playback?.status==='playing'?<Pause size={15}/>:<Play size={15}/>} {playback?.status==='playing'?'Pause playback':'Play playback'}</button><button className="button secondary" disabled={!playback||busy||scheduleMismatch||cursor>=last} aria-label="Next simulation frame" onClick={()=>control('step_forward')}><SkipForward size={15}/></button><button className="button secondary" disabled={!playback||busy||scheduleMismatch||!frames.length} onClick={()=>control('restart')}><RotateCcw size={14}/>Restart playback</button><button className="text-button" disabled={!playback||busy||scheduleMismatch||complete} onClick={()=>control('seek',last)}>Show completed run</button><label>Playback speed<select aria-label="Playback speed" disabled={!playback||busy||scheduleMismatch} value={playback?.speed??1} onChange={e=>control('speed',Number(e.target.value))}>{PLAYBACK_SPEEDS.map(n=><option key={n} value={n}>{n}×</option>)}</select></label></div>
      <label className="playback-slider">Recorded simulation frame<input type="range" aria-label="Recorded simulation frame" min={0} max={last} step={1} value={seekCursor} disabled={!playback||busy||scheduleMismatch||frames.length<2} aria-valuetext={timestamp===undefined?'No data':`Frame ${cursor+1}: ${date(new Date(timestamp).toISOString())} ${getDisplayTimezoneLabel()}`} onChange={e=>setSeekCursor(Number(e.target.value))} onPointerUp={e=>control('seek',Number(e.currentTarget.value))} onKeyUp={e=>{if(['ArrowLeft','ArrowRight','Home','End','PageUp','PageDown'].includes(e.key))control('seek',Number(e.currentTarget.value))}}/></label>
      <p className="helper">The durable worker advances the saved clock through timestamps in the computed scenario data. Step, seek, pause and speed controls update the server-owned cursor; refresh restores its latest position. Missing samples remain missing, and no extra readings are generated.</p>
    </section>
    <div className="comparison-columns"><section className="panel" data-testid="playback-baseline"><SectionHead eyebrow="SAME RECORDED CLOCK" title="Baseline to this frame"/><div className="scenario-result"><SignalChart data={baseline} domain={domain} banded/></div></section><section className="panel" data-testid="playback-modified"><SectionHead eyebrow="SIMULATED CONDITIONS" title="Modified to this frame"/><div className="scenario-result"><SignalChart data={modified} domain={domain} banded/></div></section></div>
    {analysis&&<section className="panel spaced" data-testid="playback-analysis"><SectionHead eyebrow="STORED ANALYSIS" title="Evidence available at this frame"><Badge>{analysis.completed?'Complete recorded result':'Recorded windows'}</Badge></SectionHead><p className="helper pad">Counts describe the chart’s recorded observations. Analytical events appear after their complete evidence window; this is not their first detection time. Current human decisions remain in the case record.</p><div className="table-scroll"><table><thead><tr><th scope="col">Branch</th><th scope="col">Observations</th><th scope="col">Missing</th><th scope="col">Flagged observations</th><th scope="col">Complete event windows</th></tr></thead><tbody>{(['baseline','modified'] as const).map(branch=><tr key={branch}><th scope="row">{branch==='baseline'?'Baseline':'Modified'}</th><td>{analysis[branch].observations}</td><td>{analysis[branch].missing_observations}</td><td>{analysis[branch].flagged_observations}</td><td>{analysis[branch].events.length}</td></tr>)}</tbody></table></div>{analysis.as_of&&<p className="helper pad">Analysis through {date(analysis.as_of)} {getDisplayTimezoneLabel()}{analysis.completed?' · includes the saved end-of-run quality assessment.':'.'}</p>}<div className="comparison-columns">{(['baseline','modified'] as const).map(branch=><section key={branch} className="pad" aria-label={`${branch==='baseline'?'Baseline':'Modified'} recorded events`}><h3>{branch==='baseline'?'Baseline':'Modified'} events</h3>{analysis[branch].events.map(event=>{const linked=runCases.find(item=>item.id===event.case_id);return <article key={event.id} className="info-banner"><div><strong>{event.title}</strong><p>{event.asset_id} · {event.severity} · {event.source}</p><p className="helper">{event.availability_basis==='completed_snapshot'?'Recorded snapshot':'Evidence window ends'} {date(event.available_at)} {getDisplayTimezoneLabel()}{event.interval_count!=null?` · ${event.interval_count} observations`:''}</p>{linked&&<button className="text-button" onClick={()=>select(linked)}>Open current case</button>}</div></article>})}{!analysis[branch].events.length&&<p className="helper">No complete recorded event window at this frame.</p>}</section>)}</div></section>}
    {frames.length<=1&&<p className="info-banner">This run has only a recorded snapshot, so the app does not invent a multi-frame time series.</p>}
    <section className="panel spaced"><SectionHead title="Findings from the completed run"><Badge>{complete?'Full result':'Available at final frame'}</Badge></SectionHead>{complete?<><p className="helper pad">These findings use the full computed run. Their current case statuses are not historical playback states.</p><div className="scenario-cases">{runCases.map(c=><CaseRow key={c.id} item={c} onClick={()=>select(c)}/>)}{!runCases.length&&<Empty title="No linked cases in this run" text="A run may produce no findings. Only this run’s authorized cases appear here."/>}</div></>:<p className="helper pad">Finish playback or choose Show completed run to review findings and open this run’s cases. Full-run aggregates are not attributed to an earlier frame.</p>}</section>
  </div>;
}
