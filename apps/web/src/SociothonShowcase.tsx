import {useMemo,useState} from 'react';
import {ArrowRight,Download,ShieldCheck} from 'lucide-react';
import type {Bootstrap,CivicCase} from './api';

const areas=[
  {id:'water',name:'Water',goal:'SDG 6 · Clean water'},
  {id:'electricity',name:'Electricity',goal:'SDG 7 · Clean energy'},
  {id:'roads',name:'Roads',goal:'SDG 11 · Sustainable cities'},
  {id:'drainage',name:'Drainage',goal:'SDG 11 · Resilience'},
  {id:'waste',name:'Waste',goal:'SDG 12 · Responsible consumption'},
  {id:'streetlights',name:'Streetlights',goal:'SDG 11 · Public infrastructure'},
  {id:'general',name:'Other civic services',goal:'SDG 11 · Communities'},
];
const stages=[
  ['Observe','Record a citizen report or infrastructure signal'],
  ['Corroborate','Compare readings and preserve uncertainty'],
  ['Prioritise','Review evidence and choose the next action'],
  ['Inspect','Assign a trained person to verify field conditions'],
  ['Intervene','Record what was done, by whom and when'],
  ['Follow up','Verify evidence before an authorised closure'],
];
const done=(c:CivicCase)=>['resolved','closed'].includes(c.status);
export function SociothonShowcase({data,go}:{data:Bootstrap;go:(p:string)=>void}){
  const [filter,setFilter]=useState('all');
  const cases=Array.isArray(data.cases)?data.cases:[];
  const focus=useMemo(()=>filter==='all'?cases:cases.filter(c=>c.domain===filter),[cases,filter]);
  const open=focus.filter(c=>!done(c)).length;
  const reviewed=focus.filter(done).length;
  const zones=new Set(focus.map(c=>c.zone_id)).size;
  const distribution=areas.map(a=>({...a,count:cases.filter(c=>c.domain===a.id).length}));
  const exportBrief=()=>{
    const summary={project:'CivicSignal 360 / Sociothon',source:'Authorized synthetic prototype records',generated_at:new Date().toISOString(),domain:filter,totals:{cases:focus.length,open,administratively_resolved:reviewed,zones_with_cases:zones},by_domain:distribution.map(x=>({domain:x.id,count:x.count})),limitations:['Synthetic prototype data','Administrative resolution is not independently verified repair','No real municipal integration or verified resource savings']};
    const blob=new Blob([JSON.stringify(summary,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob);const anchor=document.createElement('a');anchor.href=url;anchor.download='sociothon-impact-brief.json';anchor.click();URL.revokeObjectURL(url);
  };
  return <div className="si-showcase">
    <section className="si-hero">
      <div><div className="si-kicker">Sociothon · Evidence-to-action demonstrator</div>
        <h2>Don't just count complaints. Show what happened next.</h2>
        <p>Track infrastructure signals through a human-controlled chain of investigation, field evidence, intervention and follow-up across seven civic service domains.</p>
      </div>
      <div className="si-hero-actions">
        <button type="button" className="button secondary" onClick={exportBrief}><Download size={15}/>Export impact brief</button>
        <button type="button" className="button primary" onClick={()=>go('/demo')}>Open demo <ArrowRight size={15}/></button>
      </div>
    </section>
    <div className="si-filters" role="group" aria-label="Filter social-impact signals by infrastructure domain">
      <button className="si-filter" aria-pressed={filter==='all'} onClick={()=>setFilter('all')}>All services</button>
      {areas.map(a=><button className="si-filter" key={a.id} aria-pressed={filter===a.id} onClick={()=>setFilter(a.id)}>{a.name}</button>)}
    </div>
    <div className="si-grid">
      <div className="si-card"><div className="si-number">{focus.length}</div><strong>Visible cases</strong><p>Within the selected authorized demo scope</p></div>
      <div className="si-card"><div className="si-number">{open}</div><strong>Still open</strong><p>Evidence and coordination remain in progress</p></div>
      <div className="si-card"><div className="si-number">{reviewed}</div><strong>Administratively resolved</strong><p>Not equivalent to independently verified repairs</p></div>
      <div className="si-card"><div className="si-number">{zones}</div><strong>Zones represented</strong><p>Reporting coverage varies by geography</p></div>
    </div>
    <div className="si-layout">
      <section className="si-card"><h3 className="si-section-title">Six steps to accountable action</h3>
        <div className="si-steps">{stages.map(([label,desc],i)=><div className="si-step" key={label}><b>{String(i+1).padStart(2,'0')}</b><strong>{label}</strong><p>{desc}</p></div>)}</div>
        <div className="si-note"><ShieldCheck size={15}/> &nbsp;The system supports human decisions; it does not autonomously confirm real-world repairs, control utilities or replace civic authorities.</div>
      </section>
      <section className="si-card"><h3 className="si-section-title">Signals by service</h3>
        <p className="si-caption">Thematic SDG mapping is explanatory, not evidence of SDG achievement.</p>
        {distribution.map(a=><div className="si-case" key={a.id}><div><strong>{a.name}</strong><small>{a.goal}</small></div><strong>{a.count}</strong></div>)}
      </section>
    </div>
    <div className="si-card" style={{marginTop:16}}>
      <h3 className="si-section-title">Recent cases in this view</h3>
      {focus.length===0?<p>No cases in the selected domain and authorized scope.</p>:focus.slice(0,5).map(c=><div className="si-case" key={c.id}>
        <div><strong>{c.title}</strong><small>{c.domain} · {c.zone_id} · {c.status.replaceAll('_',' ')}</small></div>
        <span className={'badge '+(done(c)?'resolved':c.severity)}>{done(c)?'Reviewed closure':'Open / in progress'}</span>
      </div>)}
      <button type="button" className="button secondary" style={{marginTop:14}} onClick={()=>go('/incidents')}>Explore evidence and cases <ArrowRight size={14}/></button>
    </div>
    <p className="si-caption">All quantities reflect currently visible synthetic records; outputs are not validated real-world impact estimates. The exported brief contains aggregates only, not citizen report text.</p>
  </div>;
}
