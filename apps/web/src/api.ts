export type CivicCase={id:string,title:string,domain:string,zone_id:string,asset_id?:string,severity:string,status:string,summary:string,created_at:string,updated_at:string,deadline_at?:string|null,provenance:string,priority:number|Record<string,unknown>,evidence:any,version:number,assigned_to?:string,[key:string]:any};
export type Bootstrap={user:any,zones:any[],assets:any[],cases:CivicCase[],metrics:any,series:any[],notifications:any[],domain_stats:any,config:any,[key:string]:any};
let csrf='';
type DisplayTimezone = 'Asia/Kolkata' | 'UTC';
let displayTimezone:DisplayTimezone='Asia/Kolkata';
export class ApiError extends Error {status:number; constructor(message:string,status:number){super(message);this.status=status;}}
export function setCsrf(value:string){csrf=value||''}
export function setDisplayTimezone(value?:string){displayTimezone=value==='UTC'?'UTC':'Asia/Kolkata'}
export function getDisplayTimezone(){return displayTimezone}
export function getDisplayTimezoneLabel(){return displayTimezone==='UTC'?'UTC':'IST'}
export function dateTimeLocalValue(timestamp:number|string|Date){const instant=timestamp instanceof Date?timestamp:new Date(timestamp);if(!Number.isFinite(instant.getTime()))return '';const parts=new Intl.DateTimeFormat('en-CA',{timeZone:displayTimezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(instant);const values=Object.fromEntries(parts.map(part=>[part.type,part.value]));return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`}
export function dateTimeLocalToIso(value:string){const match=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);if(!match)throw new Error('Enter a valid date and time.');const [,year,month,day,hour,minute]=match.map(Number);const epoch=Date.UTC(year,month-1,day,hour,minute)-(displayTimezone==='Asia/Kolkata'?330:0)*60_000;const parsed=new Date(epoch);if(!Number.isFinite(epoch)||dateTimeLocalValue(parsed)!==value)throw new Error('Enter a valid date and time.');return parsed.toISOString()}
export async function upload(path:string,file:File,notes='',idempotencyKey?:string){const form=new FormData();form.append('file',file);form.append('notes',notes);if(idempotencyKey)form.append('idempotency_key',idempotencyKey);const r=await fetch('/api/v1'+path,{method:'POST',credentials:'include',headers:{'X-CSRF-Token':csrf},body:form});const result=await r.json().catch(()=>({detail:'The service returned an unreadable response.'}));if(!r.ok)throw new ApiError(typeof result.detail==='string'?result.detail:'Upload failed',r.status);if(!result.id||!result.url)throw new Error('Upload confirmation is unreadable');return result}
export async function api(path:string, options:RequestInit={}){
 const r=await fetch('/api/v1'+path,{credentials:'include',...options,headers:{'Content-Type':'application/json',...(options.method&&options.method!=='GET'?{'X-CSRF-Token':csrf}:{}),...options.headers}});
 const body=await r.json().catch(()=>({detail:'The service returned an unreadable response.'}));
 if(!r.ok)throw new ApiError(typeof body.detail==='string'?body.detail:body.detail?JSON.stringify(body.detail):body.message||`Request failed (${r.status})`,r.status);
 if(body.csrf_token)setCsrf(body.csrf_token);return body;
}
export const send=(path:string,body:any,method='POST')=>api(path,{method,body:JSON.stringify(body)});
export function download(value:any,name:string){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)}
export function fmt(v:any,digits=0){return typeof v==='number'?v.toLocaleString('en-IN',{maximumFractionDigits:digits}):v??'—'}
export function date(v?:string){return v?new Date(v).toLocaleString('en-IN',{timeZone:displayTimezone,day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'Not recorded'}
