import {useState} from 'react';
import {RotateCcw} from 'lucide-react';
import {send} from './api';
import {ErrorBox,SectionHead} from './components';

export function DemoSessionReset({onReset,refresh}:{onReset:()=>void,refresh:()=>Promise<void>}) {
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const reset=async()=>{
    const approved=window.confirm('Reset this browser’s isolated demo session? Open synthetic scenario cases will be closed and stored scenario results cleared. Submitted reports, uploaded readings, photographs, human evidence, baseline data and shared reference data will be preserved. Pause or wait for any calculation that is still running.');
    if(!approved)return;
    setBusy(true);setError('');setNotice('');
    try{
      const result=await send('/demo-session/reset',{});
      onReset();
      await refresh();
      setNotice(`Session reset: ${result.cleared_scenario_results} scenario runs cleared and ${result.closed_cases.length} open simulated cases closed. Reports and user evidence were preserved.`);
    }catch(e:any){setError(e.message||'The demo session could not be reset.')}
    finally{setBusy(false)}
  };
  return <section className="panel spaced demo-session-reset" data-testid="demo-session-reset">
    <SectionHead eyebrow="ISOLATED SYNTHETIC DATA" title="Reset this browser demo session"/>
    <p className="helper">This affects scenarios created in this browser’s isolated demo session. It keeps submitted reports, uploaded readings, private photographs, human evidence, baseline data, and shared reference records.</p>
    {error&&<ErrorBox error={error}/>}
    {notice&&<p className="info-banner" role="status">{notice}</p>}
    <button className="button secondary" disabled={busy} onClick={reset}><RotateCcw size={15}/>{busy?'Resetting this session…':'Reset this demo session'}</button>
  </section>;
}
