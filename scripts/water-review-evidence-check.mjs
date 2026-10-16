import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.CIVIC_BASE_URL;
if(!base||!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Use an isolated local acceptance server.');
const results={checks:[],errors:[]};
const browser=await chromium.launch({headless:true,executablePath:process.env.CIVIC_BROWSER_PATH});
const contexts=[];
async function actor(role){
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});contexts.push(context);
  await context.route('**/*',route=>new URL(route.request().url()).origin===base||/^(blob|data):/.test(route.request().url())?route.continue():route.abort());
  const response=await context.request.post(base+'/api/v1/auth/login',{data:{email:role+'@civicsignal.local',password:'CivicDemo!2026'}});
  assert.equal(response.status(),200);const auth=await response.json();
  const page=await context.newPage();page.on('pageerror',e=>results.errors.push(e.message));
  const request=(path,data,method='post')=>context.request[method](base+'/api/v1'+path,{data,headers:{'X-CSRF-Token':auth.csrf_token}});
  return {context,page,request};
}
let page;
try{
  const citizen=await actor('citizen'),operator=await actor('operator'),admin=await actor('admin');page=operator.page;
  const response=await citizen.request('/reports',{domain:'water',zone_id:'river',title:'Synthetic saved review '+Date.now(),description:'Synthetic browser verification; not a real incident.',location:'Synthetic review facility',idempotency_key:crypto.randomUUID()});
  assert.ok(response.ok(),await response.text());const report=await response.json();
  const getCase=async()=>{const r=await operator.context.request.get(base+'/api/v1/cases/'+report.case_id);assert.ok(r.ok());return r.json()};
  const before=await getCase();
  async function review(){
    await page.goto(base+'/domains/water');await page.getByRole('button',{name:'Operations',exact:true}).click();
    const panel=page.locator('.water-operations');await panel.getByLabel('Service zone',{exact:true}).selectOption('river');
    const pending=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/water/zones/river/review'));
    await panel.getByRole('button',{name:'Review water observations',exact:true}).click();
    const r=await pending;assert.equal(r.status(),200);const snapshot=await r.json();
    const attach=page.getByRole('region',{name:'Attach water review',exact:true});
    await attach.getByLabel('Water case for this review').selectOption(report.case_id);
    await attach.getByLabel('Why this review is relevant').fill('Synthetic review of supply context for this reported condition.');
    return {snapshot,attach};
  }
  const {snapshot,attach}=await review();
  const path='/api/v1/water/zones/river/cases/'+report.case_id+'/reviews';let dropped=false;
  await page.route('**'+path,async route=>{if(!dropped){dropped=true;const r=await route.fetch();assert.equal(r.status(),200);await route.abort('failed')}else await route.continue()});
  await attach.getByRole('checkbox',{name:/Retain this pending attachment/}).check();
  await attach.getByRole('button',{name:'Attach reviewed snapshot',exact:true}).click();
  await attach.getByText(/Confirmation is unavailable/).waitFor();
  const stored=await page.evaluate(()=>Object.entries(localStorage).filter(([key])=>key.startsWith('civic-water-review-v1:')));
  assert.equal(stored.length,1);const retained=JSON.parse(stored[0][1]);assert.equal(retained.pending.caseId,report.case_id);assert.equal(JSON.stringify(retained).includes('source_observations'),false);
  await page.reload();await page.getByRole('button',{name:'Operations',exact:true}).click();
  await attach.getByRole('button',{name:'Retry exact attachment',exact:true}).waitFor();
  await attach.getByRole('button',{name:'Retry exact attachment',exact:true}).click();
  await attach.getByRole('button',{name:'Open saved Evidence Passport',exact:true}).waitFor();
  const after=await getCase();assert.equal(after.evidence_records.length,1);assert.equal(after.status,before.status);
  assert.equal(after.version,before.version+1);assert.equal(after.audits.filter(a=>a.action==='water_review_attached').length,1);
  assert.deepEqual(after.evidence_records[0].observations.water_review,snapshot);
  assert.equal(await page.evaluate(()=>Object.keys(localStorage).filter(key=>key.startsWith('civic-water-review-v1:')).length),0);
  results.checks.push({name:'Lost confirmation survives an opted-in reload and retries the exact attachment without duplicate evidence or decision changes',status:'passed'});
  await attach.getByRole('button',{name:'Open saved Evidence Passport',exact:true}).click();
  const saved=page.getByTestId('saved-water-review');await saved.waitFor();
  assert.match(await saved.innerText(),/not a confirmed leak or field inspection/);
  const downloaded=page.waitForEvent('download');await saved.getByRole('button',{name:'Export saved water review',exact:true}).click();
  assert.deepEqual(JSON.parse(await fs.readFile(await (await downloaded).path(),'utf8')),snapshot);
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await page.screenshot({path:`artifacts/verification/saved-water-review-${width}.png`,fullPage:true})}
  results.checks.push({name:'Evidence Passport displays and exports the exact saved snapshot on desktop and mobile',status:'passed'});
  await page.setViewportSize({width:1440,height:1000});
  const stale=await review();
  const configPath='/water/zones/river/operations';const config=await (await admin.context.request.get(base+'/api/v1'+configPath)).json();
  const changed=await admin.request(configPath,{...config.configuration,outside_rate_lph:config.configuration.outside_rate_lph+1,reason:'Synthetic stale-review acceptance'},'put');assert.ok(changed.ok());const updated=await changed.json();
  try{
    const rejection=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(path));
    await stale.attach.getByRole('button',{name:'Attach reviewed snapshot',exact:true}).click();assert.equal((await rejection).status(),409);
    await stale.attach.getByRole('alert').filter({hasText:/Configuration changed/}).waitFor();
    const final=await getCase();assert.equal(final.evidence_records.length,1);assert.deepEqual(final.evidence_records[0].observations.water_review,snapshot);
    results.checks.push({name:'Changed configuration rejects a stale attachment and preserves historical saved evidence',status:'passed'});
  }finally{assert.ok((await admin.request(configPath,{...config.configuration,version:updated.version,reason:'Restore synthetic acceptance configuration'},'put')).ok())}
}catch(e){results.errors.push(e.stack||e.message);await page?.screenshot({path:'artifacts/verification/water-review-evidence-failure.png',fullPage:true}).catch(()=>{})}
finally{await fs.mkdir('artifacts/verification',{recursive:true});await fs.writeFile('artifacts/verification/water-review-evidence.json',JSON.stringify(results,null,2));await browser.close()}
console.log(JSON.stringify(results,null,2));if(results.errors.length)process.exitCode=1;
