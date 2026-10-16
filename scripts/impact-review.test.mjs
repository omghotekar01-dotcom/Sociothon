import assert from 'node:assert/strict';
import test from 'node:test';
import {rankCasesForReview} from '../apps/web/src/impactReview.ts';

const now=Date.parse('2026-10-16T12:00:00Z');
const sample=(id,overrides={})=>({
  id,title:'Synthetic case',domain:'water',zone_id:'zone-1',severity:'low',
  status:'investigating',summary:'',created_at:'2026-10-16T10:00:00Z',
  updated_at:'2026-10-16T10:00:00Z',deadline_at:null,provenance:'synthetic',
  priority:0,evidence:[],version:1,assigned_to:'inspector-1',...overrides
});

test('overdue critical cases outrank ordinary open cases and expose every factor',()=>{
  const ranked=rankCasesForReview([
    sample('routine'),
    sample('critical',{severity:'critical',assigned_to:'',created_at:'2026-10-01T10:00:00Z',deadline_at:'2026-10-15T12:00:00Z'})
  ],now);
  assert.equal(ranked[0].case.id,'critical');
  assert.equal(ranked[0].score,11);
  assert.equal(ranked[0].band,'High priority review');
  assert.ok(ranked[0].reasons.includes('Administrative review target overdue'));
  assert.equal(ranked[1].band,'Routine follow-up');
});

test('administratively closed cases are excluded; display does not certify repairs',()=>{
  const ranked=rankCasesForReview([sample('closed',{status:'closed'}),sample('resolved',{status:'resolved'}),sample('open')],now);
  assert.deepEqual(ranked.map(x=>x.case.id),['open']);
});

test('invalid timestamps are ignored and ties are sorted by stable case id',()=>{
  const ranked=rankCasesForReview([
    sample('b',{created_at:'invalid',deadline_at:'invalid'}),
    sample('a',{created_at:'invalid',deadline_at:'invalid'})
  ],now);
  assert.deepEqual(ranked.map(x=>x.case.id),['a','b']);
  assert.deepEqual(ranked[0].reasons,['Standard human review']);
});

test('review targets within 24 hours are labelled, not marked overdue',()=>{
  const next=rankCasesForReview([sample('soon',{deadline_at:'2026-10-17T11:30:00Z'})],now)[0];
  assert.equal(next.score,1);
  assert.ok(next.reasons.includes('Review target within 24 hours'));
});
