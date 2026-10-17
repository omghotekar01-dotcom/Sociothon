import test from 'node:test';
import assert from 'node:assert/strict';
import {classifyWaterFollowup} from '../apps/web/src/waterFollowup.ts';
const sample=(before,after,status='comparison_available',issues=[])=>({before_total_l:before,after_total_l:after,status,issues});
test('matching valid windows with recorded reduction produce a qualified interpretation',()=>{
 const x=classifyWaterFollowup(sample(1000,900));
 assert.equal(x.category,'observed_reduction');
 assert.match(x.reason,/does not establish/);
});
test('small changes and increases are not misrepresented as savings',()=>{
 assert.equal(classifyWaterFollowup(sample(1000,990)).category,'no_clear_change');
 assert.equal(classifyWaterFollowup(sample(1000,1050)).category,'increased');
});
test('missing or inconsistent readings remain insufficient evidence',()=>{
 assert.equal(classifyWaterFollowup(sample(null,900)).category,'insufficient');
 assert.equal(classifyWaterFollowup(sample(1000,900,'insufficient_followup',['missing rows'])).category,'insufficient');
 assert.equal(classifyWaterFollowup(sample(0,0)).category,'insufficient');
});
