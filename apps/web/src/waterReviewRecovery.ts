export type WaterReviewAttachment={review:Record<string,unknown>;snapshot_hash:string;case_version:number;reason:string;idempotency_key:string};
export type PendingWaterReview={caseId:string;body:WaterReviewAttachment};
export function waterReviewRecoveryKey(userId:string,zone:string){return 'civic-water-review-v1:'+encodeURIComponent(userId)+':'+encodeURIComponent(zone)}
export function serializeWaterReviewRecovery(pending:PendingWaterReview,userId:string,zone:string){
  // Store only the exact submission, not original meter observations or a full case.
  return JSON.stringify({schema:1,userId,zone,pending:{caseId:pending.caseId,body:{review:pending.body.review,snapshot_hash:pending.body.snapshot_hash,case_version:pending.body.case_version,reason:pending.body.reason,idempotency_key:pending.body.idempotency_key}}});
}
export function parseWaterReviewRecovery(raw:string,userId:string,zone:string):PendingWaterReview{
  const value=JSON.parse(raw),p=value.pending,b=p?.body,r=b?.review;
  if(raw.length>20000||value.schema!==1||value.userId!==userId||value.zone!==zone||typeof p?.caseId!=='string'||!p.caseId||p.caseId.length>100||!b||!r||typeof r!=='object'||Array.isArray(r))throw new Error('Invalid saved water review');
  const allowed=['start','end','configuration_version','storage_change_l','authorized_unmetered_l','accounting_note','schedule_mode','history_version'];
  const aware=(v:unknown)=>typeof v==='string'&&/(Z|[+-]\d{2}:\d{2})$/.test(v)&&Number.isFinite(Date.parse(v));
  if(Object.keys(r).some(k=>!allowed.includes(k))||!aware(r.start)||!aware(r.end)||Date.parse(r.end)<=Date.parse(r.start)||Date.parse(r.end)-Date.parse(r.start)>31*86400000||!Number.isInteger(r.configuration_version)||r.configuration_version<0||!Number.isInteger(b.case_version)||b.case_version<1||typeof b.reason!=='string'||b.reason.trim().length<5||b.reason.length>2000||!/^([a-f0-9]{64})$/.test(b.snapshot_hash)||typeof b.idempotency_key!=='string'||b.idempotency_key.length<8||b.idempotency_key.length>100)throw new Error('Invalid saved water review');
  for(const key of ['storage_change_l','authorized_unmetered_l'])if(r[key]!=null&&(typeof r[key]!=='number'||!Number.isFinite(r[key])||Math.abs(r[key])>1e12))throw new Error('Invalid accounting input');
  if(r.authorized_unmetered_l!=null&&r.authorized_unmetered_l<0)throw new Error('Invalid accounting input');
  if(r.accounting_note!=null&&(typeof r.accounting_note!=='string'||r.accounting_note.length>2000))throw new Error('Invalid accounting source');
  if(r.schedule_mode!=null&&!['current','historical'].includes(r.schedule_mode))throw new Error('Invalid schedule mode');
  if(r.history_version!=null&&(!Number.isInteger(r.history_version)||r.history_version<0))throw new Error('Invalid schedule history');
  if(r.schedule_mode==='historical'&&r.history_version==null)throw new Error('Missing schedule history');
  return {caseId:p.caseId,body:{review:{...r},snapshot_hash:b.snapshot_hash,case_version:b.case_version,reason:b.reason,idempotency_key:b.idempotency_key}};
}
