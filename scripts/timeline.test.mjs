import {test} from 'node:test';
import assert from 'node:assert/strict';
import {caseInterval, overlaps, readingInterval, timelineBounds, parseTimeline, resolveWindow, filterReadings, domainReadings, HOUR} from '../apps/web/src/timeline.ts';
const time = value => Date.parse(value);
const window = {start:time('2026-10-12T00:00:00Z'),end:time('2026-10-13T00:00:00Z')};

test('domain charts use their own observations, registry zones and exact shared interval window',()=>{
  const assets=[{id:'e',domain:'electricity',zone_id:'river'},{id:'w',domain:'water',zone_id:'river'}];
  const rows=[{asset_id:'e',timestamp:'2026-10-12T01:00:00Z',actual:null},{asset_id:'e',zone_id:'hill',timestamp:'2026-10-12T01:00:00Z',actual:10},{asset_id:'w',timestamp:'2026-10-12T01:00:00Z',actual:20},{asset_id:'e',timestamp:'2026-10-13T00:00:00Z',actual:30},{asset_id:'unknown',timestamp:'2026-10-12T01:00:00Z',actual:0}];
  assert.deepEqual(domainReadings(rows,'electricity',assets,'river',window),[rows[0]]);
  assert.deepEqual(domainReadings(rows,'electricity',assets,'all',window),[rows[0],rows[4]]);
  assert.equal(domainReadings(rows,'electricity',assets,'hill',window).length,0);
});

test('sensor events use observation intervals even when cases were created later',()=>{
  const item={created_at:'2026-10-14T10:00:00Z',evidence:{start:'2026-10-12T23:00:00Z',end:'2026-10-13T01:00:00Z'}};
  assert.equal(overlaps(caseInterval(item),window),true);
  assert.equal(overlaps(caseInterval({...item,evidence:{}}),window),false);
});
test('half-open time windows exclude touching events without double counting',()=>{
  assert.equal(overlaps({start:window.start-HOUR,end:window.start},window),false);
  assert.equal(overlaps({start:window.end,end:window.end+HOUR},window),false);
  assert.equal(overlaps({start:window.start,end:window.end},window),true);
});
test('point reports include the start and exclude the end',()=>{
  assert.equal(overlaps(caseInterval({created_at:'2026-10-12T00:00:00Z'}),window),true);
  assert.equal(overlaps(caseInterval({created_at:'2026-10-13T00:00:00Z'}),window),false);
});
test('bad dates remain unavailable and all-time view can still include undated cases',()=>{
  assert.equal(caseInterval({created_at:'invalid',evidence:{start:'invalid'}}),null);
  assert.equal(readingInterval({timestamp:'invalid'}),null);
  assert.equal(overlaps(null,window),false);
  assert.equal(overlaps(null,null),true);
  assert.equal(timelineBounds([],[]),null);
});
test('interval duration and explicit timezone offsets are honored',()=>{
  const row=readingInterval({timestamp:'2026-10-12T05:30:00+05:30',interval_minutes:30});
  assert.equal(row.start,window.start);assert.equal(row.end-row.start,HOUR/2);
  assert.equal(readingInterval({timestamp:'2026-10-12T00:00:00Z',interval_minutes:-60}).end,window.start+HOUR);
});
test('zone and domain filters preserve missing rows and never relabel water as electricity',()=>{
  const rows=[{timestamp:'2026-10-12T01:00:00Z',zone_id:'river',actual:null},{timestamp:'2026-10-12T01:00:00Z',zone_id:'hill',actual:0},{timestamp:'2026-10-13T00:00:00Z',zone_id:'river',actual:9}];
  assert.deepEqual(filterReadings(rows,'river','water',window),[rows[0]]);
  assert.deepEqual(filterReadings(rows,'river','electricity',window),[]);
  assert.equal(filterReadings(rows,'hill','all',window)[0].actual,0);
});
test('shareable selection validates spans and relative presets anchor to recorded time',()=>{
  const selected=parseTimeline('?at=2026-10-13T00:00:00Z&hours=24');
  assert.deepEqual(resolveWindow(selected,'all',0),window);
  assert.deepEqual(resolveWindow(null,'1',window.end),window);
  assert.equal(parseTimeline('?at=invalid&hours=24'),null);
  assert.equal(parseTimeline('?at=2026-10-13T00:00:00Z&hours=-6'),null);
  assert.equal(resolveWindow(null,'all',window.end),null);
});
test('timeline bounds include complete final intervals and one-point data',()=>{
  assert.deepEqual(timelineBounds([],[{timestamp:'2026-10-12T00:00:00Z',interval_minutes:60}]),{start:window.start,end:window.start+HOUR});
  assert.deepEqual(timelineBounds([{created_at:'2026-10-12T00:00:00Z'}],[]),{start:window.start,end:window.start+HOUR});
});
