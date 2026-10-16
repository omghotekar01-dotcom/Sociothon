import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseWaterReviewRecovery,serializeWaterReviewRecovery,waterReviewRecoveryKey} from '../apps/web/src/waterReviewRecovery.ts';
const pending={caseId:'case-1',body:{review:{start:'2031-01-06T00:00:00Z',end:'2031-01-07T00:00:00Z',configuration_version:4,storage_change_l:null,authorized_unmetered_l:null,accounting_note:'Unknown',schedule_mode:'historical',history_version:2},snapshot_hash:'a'.repeat(64),case_version:5,reason:'Review supplied evidence',idempotency_key:'same-request-123'}};
test('water recovery preserves the exact original request without case or meter data',()=>{
  const raw=serializeWaterReviewRecovery({...pending,source_observations:[{private:'not retained'}]},'operator','river');
  assert.deepEqual(parseWaterReviewRecovery(raw,'operator','river'),pending);
  assert.equal(raw.includes('source_observations'),false);
});
test('water recovery isolates accounts and zones and rejects malformed records',()=>{
  const raw=serializeWaterReviewRecovery(pending,'operator','river');
  assert.throws(()=>parseWaterReviewRecovery(raw,'another-user','river'));
  assert.throws(()=>parseWaterReviewRecovery(raw,'operator','hill'));
  for(const bad of ['bad json','{}',raw.replace('historical','unrecognized'),raw.replace('same-request-123','tiny'),raw.replace('2031-01-06T00:00:00Z','2031-01-06T00:00:00')])assert.throws(()=>parseWaterReviewRecovery(bad,'operator','river'));
  assert.notEqual(waterReviewRecoveryKey('a:b','c'),waterReviewRecoveryKey('a','b:c'));
});
