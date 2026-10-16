import {test} from 'node:test';
import assert from 'node:assert/strict';
import {playbackFrames,reconcilePlayback,visiblePlaybackRows} from '../apps/web/src/replayState.ts';

const t0='2026-10-12T00:00:00Z',t1='2026-10-12T01:00:00Z',t2='2026-10-12T02:00:00Z';

test('clock schedule is the sorted union of actual baseline and modified timestamps',()=>{
  assert.deepEqual(playbackFrames([{timestamp:t2},{timestamp:t0}],[{timestamp:t1},{timestamp:t0},{timestamp:'invalid'}]),[t0,t1,t2].map(Date.parse));
});

test('equivalent UTC offsets represent one stored instant',()=>{
  assert.deepEqual(playbackFrames([{timestamp:'2026-10-12T01:00:00+01:00'}],[{timestamp:t0}]),[Date.parse(t0)]);
});

test('snapshot-only domains use their recorded clock; unavailable clocks stay empty',()=>{
  assert.deepEqual(playbackFrames([],[],t0),[Date.parse(t0)]);
  assert.deepEqual(playbackFrames([],[],'invalid'),[]);
  assert.deepEqual(playbackFrames([{timestamp:t1}],[],t0),[Date.parse(t1)]);
});

test('frames preserve gaps and never turn missing observations into zeroes',()=>{
  const rows=[{timestamp:t0,actual:null},{timestamp:t2,actual:0}];
  assert.equal(playbackFrames(rows,[]).length,2);
  assert.deepEqual(visiblePlaybackRows(rows,Date.parse(t1)),[rows[0]]);
  assert.equal(visiblePlaybackRows(rows,Date.parse(t1))[0].actual,null);
  assert.deepEqual(visiblePlaybackRows(rows,Date.parse(t2)),rows);
  assert.deepEqual(visiblePlaybackRows(rows,undefined),[]);
});

test('cutoff reveals only real rows at or before the server clock',()=>{
  const rows=[{timestamp:t0,id:'before'},{timestamp:t1,id:'at'},{timestamp:t2,id:'after'}];
  assert.deepEqual(visiblePlaybackRows(rows,Date.parse(t1)).map(row=>row.id),['before','at']);
});

test('a late playing response cannot undo a newer pause or backwards seek',()=>{
  const old={job_id:'run-a',version:3,cursor:10,updated_at:t1,status:'playing'};
  const paused={...old,version:4,cursor:2,updated_at:t2,status:'paused'};
  assert.equal(reconcilePlayback(old,paused,'run-a'),paused);
  assert.equal(reconcilePlayback(paused,old,'run-a'),paused);
  assert.equal(reconcilePlayback(paused,{...paused,job_id:'run-b'},'run-a'),paused);
});

test('out-of-order worker polls cannot move a run backwards within one control version',()=>{
  const earlier={job_id:'run-a',version:3,cursor:10,updated_at:t1,status:'playing'};
  const later={...earlier,cursor:11,updated_at:t2,status:'paused'};
  assert.equal(reconcilePlayback(earlier,later,'run-a'),later);
  assert.equal(reconcilePlayback(later,earlier,'run-a'),later);
  assert.equal(reconcilePlayback(later,{...later,updated_at:t1,status:'playing'},'run-a'),later);
});
