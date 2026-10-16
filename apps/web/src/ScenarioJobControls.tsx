import {useState} from 'react';
import {send} from './api';
import {ErrorBox} from './components';

export function ScenarioJobControls({job,changed}:{job:any,changed:(job:any)=>void}){
  const [reason,setReason]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const actionable=['queued','running','paused'].includes(job.status);
  async function control(){
    setBusy(true);setError('');
    try{changed(await send('/jobs/'+job.id+'/'+(job.status==='paused'?'resume':'pause'),{version:job.control_version,reason}));setReason('')}
    catch(e:any){setError(e.message)}finally{setBusy(false)}
  }
  return <section className="panel scenario-job-controls" data-testid="scenario-job-controls" aria-label="Worker controls">
    <h3>Worker controls</h3><p role="status" data-testid="worker-status">{job.status==='pausing'?'Pause requested — waiting for the current calculation to reach its checkpoint.':job.status==='paused'?(job.checkpoint_ready?'Paused — calculation saved; cases have not been published.':'Paused — waiting to calculate.'):job.status==='queued'?'Queued — waiting for a worker.':job.status==='running'?'Running — calculating or publishing the saved checkpoint.':job.status==='succeeded'?'Finished — result and case links saved.':job.status==='reset'?'Cleared by demo-session reset; the run cannot be resumed.':'Failed — inspect the recorded error.'}</p>
    <p className="helper">Queued runs pause immediately. Running calculations finish their current computation and pause before publishing cases. Resume uses the saved checkpoint when available. These controls are separate from recorded playback.</p>
    <p className="helper">Control revision {job.control_version} · {job.checkpoint_stage} · attempts {job.attempts}/{job.max_attempts}</p>
    {error&&<ErrorBox error={error}/>} {actionable&&<><label>Worker control reason<textarea rows={2} maxLength={2000} value={reason} onChange={e=>setReason(e.target.value)} placeholder="Explain why this run should pause or resume."/></label><button className="button secondary" disabled={busy||reason.trim().length<5} onClick={control}>{job.status==='paused'?'Resume worker run':'Pause worker run'}</button></>}
  </section>;
}
