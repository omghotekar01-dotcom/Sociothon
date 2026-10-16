import {test} from 'node:test';
import assert from 'node:assert/strict';
import {networkCases} from '../apps/web/src/networkCases.ts';

const nodes=[{id:'water-river',zone_id:'river'},{id:'water-hill',zone_id:'hill'}];
const item=(id, overrides={})=>({id,asset_id:'water-river',domain:'water',zone_id:'river',status:'needs_review',severity:'high',...overrides});

test('overlays require an exact visible water asset and zone link',()=>{
  const groups=networkCases(nodes,[item('valid'),item('no-link',{asset_id:null}),item('hidden',{asset_id:'water-market',zone_id:'market'}),item('other-domain',{domain:'electricity'}),item('wrong-zone',{zone_id:'hill'})]);
  assert.deepEqual(groups.get('water-river').open.map(c=>c.id),['valid']);
  assert.equal(groups.get('water-hill').open.length,0);
  assert.equal(groups.has('water-market'),false);
});
test('closure, resolution and reopening change open counts without discarding history',()=>{
  const initial=[item('one'),item('two',{status:'monitoring',severity:'medium'})];
  assert.equal(networkCases(nodes,initial).get('water-river').open.length,2);
  const finished=initial.map((c,i)=>({...c,status:i?'resolved':'closed'}));
  const group=networkCases(nodes,finished).get('water-river');
  assert.equal(group.all.length,2);assert.equal(group.open.length,0);assert.equal(group.severity,null);
  assert.equal(networkCases(nodes,[{...finished[0],status:'investigating'},finished[1]]).get('water-river').open.length,1);
});
test('highest recorded open severity excludes historical critical cases and preserves unknowns',()=>{
  const group=networkCases(nodes,[item('critical-history',{status:'resolved',severity:'critical'}),item('medium',{severity:'medium'}),item('low',{severity:'low'}),item('unknown',{severity:'new-rating'})]).get('water-river');
  assert.equal(group.severity,'medium');
  assert.deepEqual(group.open.map(c=>c.id),['medium','low','unknown']);
  assert.equal(networkCases(nodes,[item('unknown',{severity:'new-rating'})]).get('water-river').severity,'unrated');
});
test('duplicate input cannot inflate markers and grouping does not change case records',()=>{
  const cases=[item('b'),item('a'),item('a')];const before=structuredClone(cases);
  const group=networkCases(nodes,cases).get('water-river');
  assert.equal(group.open.length,2);assert.deepEqual(group.open.map(c=>c.id),['a','b']);
  assert.deepEqual(cases,before);
});
