import {test} from 'node:test';
import assert from 'node:assert/strict';
import {emptyFieldDraft,parseFieldDraft,prepareFieldSubmission} from '../apps/web/src/fieldDraft.ts';
test('legacy notes restore without inventing checklist confirmation',()=>{
  const draft=parseFieldDraft('An older saved observation',7);
  assert.equal(draft.notes,'An older saved observation');assert.deepEqual(draft.checklist,[false,false,false]);assert.equal(draft.electricalQualified,false);assert.equal(draft.baseVersion,7);
});
test('electrical field confirmation is preserved in the exact pending record',()=>{
  const draft=prepareFieldSubmission({...emptyFieldDraft(2),notes:'Safe qualified electrical assessment recorded.',electricalQualified:true},'inspection','electrical-12345');
  assert.equal(draft.pending.checklist.qualified_electricity_assessment,true);
  assert.deepEqual(parseFieldDraft(JSON.stringify(draft),9),draft);
});
test('pending submission survives serialization and never adopts a new case version',()=>{
  const draft=prepareFieldSubmission({...emptyFieldDraft(4),notes:'A saved observation',checklist:[true,true,true]},'intervention','submission-123');
  const restored=parseFieldDraft(JSON.stringify(draft),99);
  assert.deepEqual(restored,draft);
  assert.deepEqual(prepareFieldSubmission(restored,'inspection','different-key'),draft);
});
test('corrupt saved records are rejected rather than silently treated as valid drafts',()=>{
  assert.throws(()=>parseFieldDraft('{"schema":99}',1));
  const draft=prepareFieldSubmission({...emptyFieldDraft(1),notes:'An observation'},'inspection','submission-456');
  assert.throws(()=>parseFieldDraft(JSON.stringify({...draft,notes:'Changed after pending submission'}),1));
});

test('domain measurements survive offline retry and cannot change a pending payload',()=>{
  const source={...emptyFieldDraft(2),notes:'Measured synthetic water observation',observations:{measured_volume_l:0,measurement_minutes:5,measurement_method:'Timed sample'}};
  const draft=prepareFieldSubmission(source,'inspection','domain-observation-001');
  assert.deepEqual(parseFieldDraft(JSON.stringify(draft),9),draft);
  source.observations.measured_volume_l=10;
  assert.equal(draft.pending.observations.measured_volume_l,0);
  assert.throws(()=>parseFieldDraft(JSON.stringify({...draft,observations:source.observations}),9));
});
