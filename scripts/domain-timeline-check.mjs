import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.CIVIC_BASE_URL;
if(!base||!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Use the isolated local verification server.');
const browser=await chromium.launch({headless:true,executablePath:process.env.CIVIC_BROWSER_PATH});
const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});const page=await context.newPage();
const results={checks:[],errors:[]};page.on('pageerror',e=>results.errors.push(e.message));
await context.route('**/*',route=>new URL(route.request().url()).origin===base||/^(blob|data):/.test(route.request().url())?route.continue():route.abort());
try{
  const signed=await context.request.post(base+'/api/v1/auth/login',{data:{email:'operator@civicsignal.local',password:'CivicDemo!2026'}});assert.equal(signed.status(),200);
  const bootstrap=await (await context.request.get(base+'/api/v1/bootstrap')).json();
  for(const domain of ['water','electricity','roads','drainage','waste','streetlights','general']){
    const response=await context.request.get(base+'/api/v1/analytics/'+domain);assert.ok(response.ok());const data=await response.json();
    const rows=data.series||[],dated=rows.filter(r=>Number.isFinite(Date.parse(r.timestamp)));
    const end=dated.length?Math.max(...dated.map(r=>Date.parse(r.timestamp)+(r.interval_minutes>0?r.interval_minutes:60)*60000)):Date.parse('2026-10-13T00:00:00Z');
    const start=end-6*3600000;
    const expected=rows.filter(r=>{const asset=bootstrap.assets.find(a=>a.id===r.asset_id);if(r.domain&&r.domain!==domain||asset&&asset.domain!==domain||asset&&r.zone_id&&asset.zone_id!==r.zone_id)return false;const zone=r.zone_id||asset?.zone_id,timestamp=Date.parse(r.timestamp);return zone==='river'&&timestamp<end&&timestamp+(r.interval_minutes>0?r.interval_minutes:60)*60000>start});
    await page.goto(base+`/domains/${domain}?zone=river&at=${encodeURIComponent(new Date(end).toISOString())}&hours=6`);
    const panel=page.getByTestId('domain-observation-timeline');await panel.waitFor();
    const downloaded=page.waitForEvent('download');await panel.getByRole('button',{name:'Export visible observations',exact:true}).click();
    const exported=JSON.parse(await fs.readFile(await (await downloaded).path(),'utf8'));
    assert.equal(exported.domain,domain);assert.equal(exported.zone,'river');assert.deepEqual(exported.observations,expected);
    assert.equal(exported.window_utc.start,new Date(start).toISOString());assert.equal(exported.window_utc.end_exclusive,new Date(end).toISOString());
    if(expected.length){await panel.getByRole('button',{name:'Data table',exact:true}).click();assert.equal(await panel.getByTestId('signal-table').locator('tbody tr').count(),expected.length)}else await panel.getByText('No readings available',{exact:true}).waitFor();
    await page.reload();await panel.waitFor();assert.equal(new URL(page.url()).searchParams.get('hours'),'6');
    if(domain==='electricity'){
      await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
      await page.screenshot({path:'artifacts/verification/domain-timeline-390.png',fullPage:true});await page.setViewportSize({width:1440,height:1000});
      await page.getByRole('button',{name:'Command centre',exact:true}).click();assert.equal(new URL(page.url()).searchParams.get('at'),new Date(end).toISOString());assert.equal(new URL(page.url()).searchParams.get('zone'),'river');
    }
    results.checks.push({name:domain+' chart/export uses its own observations and the shared zone/window across reload',status:'passed'});
  }
}catch(e){results.errors.push(e.stack||e.message);await page.screenshot({path:'artifacts/verification/domain-timeline-failure.png',fullPage:true}).catch(()=>{})}
finally{await fs.mkdir('artifacts/verification',{recursive:true});await fs.writeFile('artifacts/verification/domain-timeline.json',JSON.stringify(results,null,2));await browser.close()}
console.log(JSON.stringify(results,null,2));if(results.errors.length)process.exitCode=1;
