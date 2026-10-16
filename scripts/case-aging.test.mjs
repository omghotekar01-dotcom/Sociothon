import assert from 'node:assert/strict';
import test from 'node:test';
import {caseAging} from '../apps/web/src/caseAging.ts';

const now = Date.parse('2026-10-15T12:00:00Z');
const item = (overrides={}) => ({created_at:'2026-10-13T11:00:00Z', deadline_at:'2026-10-15T15:00:00Z', status:'investigating', ...overrides});

test('open cases show elapsed age and time to the administrative review target',()=>{
  assert.deepEqual(caseAging(item(),now),{ageLabel:'2d 1h',deadlineLabel:'Due in 3h',overdue:false});
});

test('overdue cases receive a distinct urgency label',()=>{
  assert.deepEqual(caseAging(item({deadline_at:'2026-10-15T10:30:00Z'}),now),{ageLabel:'2d 1h',deadlineLabel:'Overdue by 2h',overdue:true});
});

test('a target reached at this instant says due now, not overdue',()=>{
  assert.deepEqual(caseAging(item({deadline_at:'2026-10-15T12:00:00Z'}),now),{ageLabel:'2d 1h',deadlineLabel:'Due now',overdue:false});
});

test('terminal cases and invalid creation times have no aging indicator',()=>{
  assert.equal(caseAging(item({status:'resolved'}),now),null);
  assert.equal(caseAging(item({created_at:'not-a-date'}),now),null);
});

test('a case without a configured review target still reports its age',()=>{
  assert.deepEqual(caseAging(item({deadline_at:null}),now),{ageLabel:'2d 1h',deadlineLabel:null,overdue:false});
});
