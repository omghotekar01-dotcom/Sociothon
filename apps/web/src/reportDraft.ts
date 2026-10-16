export type ReportForm = {domain:string; zone_id:string; title:string; description:string; location:string; idempotency_key:string; incident_type:string; affected_asset_id:string};
export type ReportDraft = {schema:1; form:ReportForm; step:number; pending:boolean; retainLocation:boolean};
const domains=['water','electricity','roads','drainage','waste','streetlights','general'];
export type ReportValidation = {field: 'zone_id'|'location'|'title'|'description'; en: string; mr: string};
export function validateReportStep(form: ReportForm, step: number, zoneIds: string[]): ReportValidation | null {
  if ((step === 1 || step === 3) && !zoneIds.includes(form.zone_id)) return {field:'zone_id',en:'Choose an available service zone.',mr:'उपलब्ध सेवा क्षेत्र निवडा.'};
  if ((step === 1 || step === 3) && form.location.trim().length < 3) return {field:'location',en:'Enter a nearby landmark or location (at least 3 characters).',mr:'जवळची खूण किंवा ठिकाण किमान ३ अक्षरांत लिहा.'};
  if ((step === 2 || step === 3) && form.title.trim().length < 5) return {field:'title',en:'Use a title of at least 5 characters, excluding spaces at the ends.',mr:'सुरुवातीची व शेवटची रिकामी जागा वगळून शीर्षक किमान ५ अक्षरांचे असावे.'};
  if ((step === 2 || step === 3) && form.description.trim().length < 10) return {field:'description',en:'Describe your observation in at least 10 characters, excluding spaces at the ends.',mr:'सुरुवातीची व शेवटची रिकामी जागा वगळून निरीक्षण किमान १० अक्षरांत लिहा.'};
  return null;
}
export function updateReportForm(form: ReportForm, field: keyof ReportForm, value: string): ReportForm {
  return {...form, [field]: value, ...(field === 'zone_id' && value !== form.zone_id ? {affected_asset_id:''} : {})};
}
export function parseReportDraft(raw:string):ReportDraft {
  const value=JSON.parse(raw);
  const source=value.schema===1?value.form:value;
  const form=source?{...source,incident_type:source.incident_type||'other',affected_asset_id:source.affected_asset_id||''}:source;
  if (!form || !domains.includes(form.domain) || ['zone_id','title','description','location','idempotency_key','incident_type','affected_asset_id'].some(key=>typeof form[key]!=='string') || !['power_outage','electrical_hazard','voltage_observation','other'].includes(form.incident_type) || form.idempotency_key.length<8 || form.idempotency_key.length>100 || form.title.length>180 || form.description.length>6000 || form.location.length>300) throw new Error('Invalid saved report draft');
  if(value.schema!==undefined && value.schema!==1)throw new Error('Unsupported report draft');
  if(value.schema===1 && (typeof value.pending!=='boolean' || typeof value.retainLocation!=='boolean' || !Number.isInteger(value.step) || value.step<0 || value.step>3))throw new Error('Invalid draft state');
  return {schema:1,form,step:value.schema===1?value.step:0,pending:value.schema===1?value.pending:false,retainLocation:value.schema===1?value.retainLocation:false};
}
export function serializeReportDraft(draft:ReportDraft):string {
  return JSON.stringify({...draft,form:{...draft.form,location:draft.retainLocation?draft.form.location:''}});
}
