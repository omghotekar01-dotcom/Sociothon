import {useState, type FormEvent} from 'react';
import {ArrowRight,BookOpen,LayoutDashboard,MessageCircle,Plus,Send,ShieldCheck,PlayCircle,ArrowUpRight} from 'lucide-react';
import {Brand,domains} from './components';
import {ThemeSwitcher} from './ThemeSwitcher';
import {guideRequest,type GuideResult} from './startGuide';

type Props={authenticated:boolean;role?:string;onAction:(path:string)=>void|Promise<void>};
const actions=[
 {title:'Add a case',description:'Report a civic issue',path:'/report',icon:Plus,main:true},
 {title:'My reports',description:'Track your submissions',path:'/reports',icon:BookOpen},
 {title:'Dashboard',description:'See the city overview',path:'/overview',icon:LayoutDashboard},
 {title:'Live demo',description:'Try a sample scenario',path:'/demo',icon:PlayCircle}
];
const suggestions=['Report a water leak','Track my case','Open the dashboard'];

export function StartPage({authenticated,role,onAction}:Props){
 const [input,setInput]=useState('');
 const [asked,setAsked]=useState('');
 const [result,setResult]=useState<GuideResult|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const open=async(path:string)=>{
   setBusy(true);setError('');
   try{await onAction(path)}
   catch(err){setError(err instanceof Error?err.message:'Could not open this page. Please try again.')}
   finally{setBusy(false)}
 };
 const ask=(question:string)=>{
   const trimmed=question.trim();
   if(!trimmed)return;
   setAsked(trimmed.slice(0,200));
   setResult(guideRequest(trimmed));
   setInput('');
 };
 const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();ask(input)};
 return <div className="welcome-page">
   <header className="welcome-header">
     <button type="button" className="welcome-brand" onClick={()=>void open('/start')} aria-label="CivicSignal 360 home"><Brand/></button>
     <div className="welcome-header-actions">
       <span className="welcome-demo-label"><span/>Synthetic demo</span>
       <ThemeSwitcher/>
       <button type="button" className="welcome-header-link" disabled={busy} onClick={()=>void open(authenticated?'/overview':'/login')}>{authenticated?'Go to dashboard':'Sign in'}<ArrowUpRight size={15}/></button>
     </div>
   </header>
   <main id="main" className="welcome-main">
     <div className="welcome-layout">
       <section className="welcome-intro" aria-labelledby="welcome-title">
         <span className="welcome-eyebrow"><span/>CivicSignal 360 · City services, connected</span>
         <h1 id="welcome-title">Notice an issue?<br/><span>Make it count.</span></h1>
         <p className="welcome-lead">Report local problems, follow what happens next, and explore how civic teams work with evidence.</p>
         <div className="welcome-action-grid" aria-label="Quick actions">
           {actions.map(({title,description,path,icon:Icon,main})=><button type="button" className={'welcome-action'+(main?' welcome-action-primary':'')} key={path} disabled={busy} onClick={()=>void open(path)}>
             <span className="welcome-action-icon"><Icon size={21}/></span>
             <span className="welcome-action-label"><strong>{title}</strong><small>{description}</small></span>
             <ArrowRight size={18} className="welcome-action-arrow"/>
           </button>)}
         </div>
         <p className="welcome-access-note"><ShieldCheck size={15}/>{authenticated?'You are signed in. Actions use your current permissions.':'Try the demo, or sign in to create and track a report.'}</p>
       </section>
       <section className="welcome-guide" aria-labelledby="guide-title">
         <div className="welcome-guide-heading"><span className="welcome-guide-mark"><MessageCircle size={19}/></span><div><h2 id="guide-title">Where would you like to start?</h2><p>Quick guide · not an AI chat</p></div><span className="welcome-guide-status">Ready</span></div>
         <div className="welcome-conversation" aria-live="polite" aria-relevant="additions text">
           <div className="welcome-message welcome-message-guide"><span className="welcome-message-avatar">CS</span><div className="welcome-message-body"><strong>CivicSignal guide</strong><p>Hi! I can help you find the right page. What do you need to do?</p></div></div>
           {asked&&<div className="welcome-message welcome-message-user"><div className="welcome-message-body"><p>{asked}</p></div></div>}
           {result&&<div className="welcome-message welcome-message-guide"><span className="welcome-message-avatar">CS</span><div className="welcome-message-body"><strong>{result.title}</strong><p>{result.detail}</p><button type="button" className="welcome-result-link" disabled={busy} onClick={()=>void open(result.path)}>Open this page <ArrowRight size={15}/></button></div></div>}
         </div>
         <div className="welcome-guide-bottom">
           <div className="welcome-prompt-list" role="group" aria-label="Suggested prompts">
             {suggestions.map(label=><button key={label} type="button" onClick={()=>ask(label)}>{label}</button>)}
           </div>
           <form className="welcome-command" onSubmit={submit}>
             <label className="welcome-visually-hidden" htmlFor="welcome-ask">What would you like to do?</label>
             <input id="welcome-ask" autoComplete="off" value={input} onChange={event=>setInput(event.target.value)} maxLength={200} placeholder="e.g. Report a pothole near me"/>
             <button type="submit" disabled={!input.trim()||busy} aria-label="Find the right page"><Send size={18}/></button>
           </form>
           <p className="welcome-guide-note">This guide only suggests pages. Reports are submitted through the report form.</p>
         </div>
       </section>
     </div>
     <section className="welcome-services" aria-labelledby="welcome-services-title">
       <div><span className="welcome-services-kicker">Explore the city</span><h2 id="welcome-services-title">Start with a service</h2></div>
       <div className="welcome-service-list">
         {domains.map(d=><button key={d.id} type="button" disabled={busy} onClick={()=>void open(role==='citizen'?'/report?domain='+d.id:'/domains/'+d.id)}><d.icon size={18} color={d.color}/><span>{d.name}</span><ArrowRight size={14}/></button>)}
       </div>
     </section>
   </main>
   {error&&<div className="welcome-error" role="alert">{error}<button type="button" onClick={()=>setError('')}>Dismiss</button></div>}
   <footer className="welcome-footer"><span><ShieldCheck size={14}/> Independent student prototype · not a government service.</span><button type="button" onClick={()=>void open('/about')}>How it works <ArrowRight size={13}/></button><span>{role==='citizen'?'Citizen workspace':authenticated?'Staff workspace':'Synthetic data only'}</span></footer>
 </div>;
}
