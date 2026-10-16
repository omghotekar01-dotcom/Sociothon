import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseReportDraft,serializeReportDraft} from '../apps/web/src/reportDraft.ts';
const form={domain:'water',zone_id:'river',title:'Test observation',description:'Synthetic observation recorded safely.',location:'Public test location',idempotency_key:'submission-12345',incident_type:'other',affected_asset_id:''};
const draft={schema:1,form,step:3,pending:true,retainLocation:false};
test('location is omitted by default while the pending submission identifier survives',()=>{
  const restored=parseReportDraft(serializeReportDraft(draft));
  assert.equal(restored.form.location,'');assert.equal(restored.form.idempotency_key,form.idempotency_key);assert.equal(restored.pending,true);
  assert.equal(form.location,'Public test location');
});
test('explicit location retention restores the exact pending request',()=>{
  assert.deepEqual(parseReportDraft(serializeReportDraft({...draft,retainLocation:true})),{...draft,retainLocation:true});
});
test('legacy drafts remain editable; corrupt and unsupported records are rejected',()=>{
  assert.equal(parseReportDraft(JSON.stringify(form)).pending,false);
  const oldForm={...form};delete oldForm.incident_type;delete oldForm.affected_asset_id;
  assert.equal(parseReportDraft(JSON.stringify(oldForm)).form.incident_type,'other');
  assert.throws(()=>parseReportDraft('{'));
  assert.throws(()=>parseReportDraft(JSON.stringify({...draft,schema:3})));
  assert.throws(()=>parseReportDraft(JSON.stringify({...draft,form:{...form,idempotency_key:''}})));
  assert.throws(()=>parseReportDraft(JSON.stringify({...draft,step:42})));
});
