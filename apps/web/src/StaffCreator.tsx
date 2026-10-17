import {useState,type FormEvent} from 'react';
import {Plus,ShieldCheck,UserRoundPlus} from 'lucide-react';
import {send} from './api';
import {domains} from './components';

export function StaffCreator({zones,afterCreate}:{zones:{id:string;name:string}[];afterCreate:()=>Promise<void>}){
 const [name,setName]=useState('');const [email,setEmail]=useState('');const [password,setPassword]=useState('');
 const [role,setRole]=useState<'inspector'|'operator'>('inspector');
 const [departments,setDepartments]=useState<string[]>(['water']);const [areas,setAreas]=useState<string[]>([]);
 const [electrical,setElectrical]=useState(false);const [reason,setReason]=useState('');
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [success,setSuccess]=useState('');
 const toggle=(id:string,current:string[],setter:(v:string[])=>void)=>setter(current.includes(id)?current.filter(x=>x!==id):[...current,id]);
 const create=async(e:FormEvent<HTMLFormElement>)=>{
  e.preventDefault();setBusy(true);setError('');setSuccess('');
  try{
   const result=await send('/admin/staff',{name:name.trim(),email:email.trim().toLowerCase(),password,role,domains:departments,zones:areas,electrical_qualified:role==='inspector'&&departments.includes('electricity')&&electrical,reason:reason.trim()});
   setName('');setEmail('');setPassword('');setReason('');setSuccess(result.name+' added. Operators can now assign this staff member within their selected departments and zones.');
   await afterCreate();
  }catch(err){setError(err instanceof Error?err.message:'Unable to create staff account.')}
  finally{setBusy(false)}
 };
 return <section className="staff-create-panel"><div className="staff-create-head"><UserRoundPlus size={23}/><div><h3>Add a staff account</h3><p>New inspectors appear automatically in eligible operator assignment lists.</p></div></div>
 <form onSubmit={create} className="form-fields">
  <div className="staff-form-grid"><label>Full name<input required minLength={2} maxLength={100} value={name} onChange={e=>setName(e.target.value)} autoComplete="off"/></label>
  <label>Staff email<input required type="email" maxLength={254} value={email} onChange={e=>setEmail(e.target.value)} autoComplete="off"/></label>
  <label>Initial password<input required type="password" minLength={12} maxLength={256} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="new-password" placeholder="At least 12 characters"/></label>
  <label>New account role<select value={role} onChange={e=>setRole(e.target.value as 'inspector'|'operator')}><option value="inspector">Inspector</option><option value="operator">Operator</option></select></label></div>
  <fieldset><legend>Authorized service domains</legend><div className="staff-checks">{domains.map(d=><label className="checkbox-label" key={d.id}><input type="checkbox" checked={departments.includes(d.id)} onChange={()=>toggle(d.id,departments,setDepartments)}/>{d.name}</label>)}</div></fieldset>
  <fieldset><legend>Authorized zones</legend><div className="staff-checks">{zones.map(z=><label className="checkbox-label" key={z.id}><input type="checkbox" checked={areas.includes(z.id)} onChange={()=>toggle(z.id,areas,setAreas)}/>{z.name}</label>)}</div></fieldset>
  {role==='inspector'&&departments.includes('electricity')&&<label className="checkbox-label"><input type="checkbox" checked={electrical} onChange={e=>setElectrical(e.target.checked)}/>I have externally verified this inspector’s electrical qualification.</label>}
  <label>Reason for staff creation<textarea required minLength={5} maxLength={2000} rows={2} value={reason} onChange={e=>setReason(e.target.value)}/></label>
  <p className="helper"><ShieldCheck size={14}/> Passwords are hashed server-side and never returned. Share the initial password privately. Accounts are restricted to their assigned domains and zones.</p>
  {error&&<p role="alert" className="field-note-error">{error}</p>}{success&&<p role="status" className="staff-success">{success}</p>}
  <button className="button primary" type="submit" disabled={busy||departments.length===0||areas.length===0||reason.trim().length<5||password.length<12}><Plus size={16}/>{busy?'Creating staff…':'Create staff account'}</button>
 </form></section>;
}
