export type FieldKind = 'inspection'|'follow_up'|'intervention';
export type FieldSubmission = {kind:FieldKind; notes:string; checklist:Record<string,boolean>; observations?:Record<string,string|number>; version:number; idempotency_key:string};
export type FieldDraft = {schema:1; notes:string; checklist:boolean[]; electricalQualified:boolean; observations?:Record<string,string|number>; baseVersion:number; pending:FieldSubmission|null};
export const emptyFieldDraft = (version:number):FieldDraft => ({schema:1, notes:'', checklist:[false,false,false], electricalQualified:false, baseVersion:version, pending:null});
export function parseFieldDraft(raw:string|null, version:number):FieldDraft {
  if (!raw) return emptyFieldDraft(version);
  if (!raw.startsWith('{')) return {...emptyFieldDraft(version), notes:raw};
  const value=JSON.parse(raw);
  if(value.schema!==1 || typeof value.notes!=='string' || value.notes.length>10000 || !Array.isArray(value.checklist) || value.checklist.length!==3 || !value.checklist.every((v:unknown)=>typeof v==='boolean') || !Number.isInteger(value.baseVersion) || value.baseVersion<1) throw new Error('The saved draft cannot be read. Its device copy has been retained.');
  if(value.pending && (!['inspection','follow_up','intervention'].includes(value.pending.kind) || typeof value.pending.idempotency_key!=='string' || value.pending.idempotency_key.length<8 || value.pending.notes!==value.notes || value.pending.version!==value.baseVersion || typeof value.pending.checklist!=='object' || !value.pending.checklist || !Object.values(value.pending.checklist).every(v=>typeof v==='boolean'))) throw new Error('The pending submission cannot be read. Its device copy has been retained.');
  if(value.observations && (typeof value.observations!=='object'||Array.isArray(value.observations)||Object.keys(value.observations).length>20||!Object.values(value.observations).every(v=>typeof v==='string'?v.length<=500:typeof v==='number'&&Number.isFinite(v)))) throw new Error('The saved field observations cannot be read. Their device copy has been retained.');
  if(value.pending && JSON.stringify(value.pending.observations||{})!==JSON.stringify(value.observations||{})) throw new Error('Pending observations differ from the saved draft. Its device copy has been retained.');
  return {...value, electricalQualified:value.electricalQualified===true, pending:value.pending || null};
}
export function prepareFieldSubmission(draft:FieldDraft,kind:FieldKind,key:string):FieldDraft {
  // An unconfirmed submission must keep its exact payload and identifier.
  if(draft.pending) return draft;
  const checklist:Record<string,boolean>=kind==='intervention'?{observation:draft.checklist[0],action:draft.checklist[1],follow_up:draft.checklist[2]}:kind==='follow_up'?{observed:draft.checklist[0],follow_up:draft.checklist[2]}:{observed:draft.checklist[0]};
  if(draft.electricalQualified)checklist.qualified_electricity_assessment=true;
  return {...draft,pending:{kind,notes:draft.notes,checklist,...(draft.observations?{observations:{...draft.observations}}:{}),version:draft.baseVersion,idempotency_key:key}};
}
