import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.CIVIC_PLAYWRIGHT_PATH || 'playwright');
const base=process.env.CIVIC_BASE_URL || 'http://127.0.0.1:8000';
const output=path.resolve('artifacts/verification');await fs.mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CIVIC_BROWSER_PATH?{executablePath:process.env.CIVIC_BROWSER_PATH}:{})});
const inspector=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const operator=await browser.newContext();
const results={checks:[],page_errors:[],external_requests:[],started_at:new Date().toISOString()};
await inspector.route('**/*',route=>{
  const url=new URL(route.request().url());
  if(['127.0.0.1','localhost'].includes(url.hostname)||['data:','blob:'].includes(url.protocol))return route.continue();
  results.external_requests.push(url.origin);return route.abort();
});
async function login(context,role){const response=await context.request.post(base+'/api/v1/auth/login',{data:{email:role+'@civicsignal.local',password:'CivicDemo!2026'}});assert.equal(response.status(),200);return {'X-CSRF-Token':(await response.json()).csrf_token};}
const opHeaders=await login(operator,'operator');await login(inspector,'inspector');
const title='Synthetic offline field verification '+Date.now();
const reportResponse=await operator.request.post(base+'/api/v1/reports',{headers:opHeaders,data:{domain:'water',zone_id:'river',title,description:'Synthetic test of draft recovery and safe retry after connection loss.',location:'Public test site',idempotency_key:crypto.randomUUID()}});
assert.equal(reportResponse.status(),201);const report=await reportResponse.json();const id=report.case_id;
const fetchCase=async()=>await (await operator.request.get(base+'/api/v1/cases/'+id)).json();
let current=await fetchCase();
const assigned=await operator.request.post(base+'/api/v1/cases/'+id+'/assign',{headers:opHeaders,data:{inspector_id:'demo-inspector',version:current.version,reason:'Assign synthetic offline verification'}});assert.equal(assigned.status(),200);
const page=await inspector.newPage();page.on('pageerror',error=>results.page_errors.push(error.message));
const field=page.getByTestId('field-notes');
async function open(){await page.goto(base+'/inspector');await page.getByRole('button',{name:'Open '+title,exact:true}).click();await page.getByRole('button',{name:'Take action',exact:true}).click();await field.waitFor();}
async function check(name,run){try{await run();results.checks.push({name,status:'passed'});console.log('PASS',name);}catch(error){results.checks.push({name,status:'failed',error:error.message});console.error('FAIL',name,error.message);await page.screenshot({path:path.join(output,'offline-field-failure.png'),fullPage:true}).catch(()=>{});throw error;}}
const notes='Synthetic offline inspection: observation safely recorded with a planned follow-up.';
try{
  await check('Offline editing persists notes and checklist; reconnect requires manual submission',async()=>{
    await open();await field.getByLabel('Keep these notes on this device until I submit or clear them',{exact:true}).check();
    await inspector.setOffline(true);
    await field.getByText('Offline. Keep editing your draft; reconnect before submitting.',{exact:true}).waitFor();
    await field.getByLabel('Findings and intervention notes',{exact:true}).fill(notes);
    await field.getByLabel('Record what you safely observed',{exact:true}).check();
    await field.getByLabel('Specify a follow-up observation',{exact:true}).check();
    assert.equal(await field.getByRole('button',{name:'Submit inspection',exact:true}).isDisabled(),true);
    await field.getByRole('button',{name:'Save draft',exact:true}).click();
    await page.getByRole('button',{name:'The evidence',exact:true}).click();
    await page.getByRole('button',{name:'Take action',exact:true}).click();
    assert.equal(await field.getByLabel('Findings and intervention notes',{exact:true}).inputValue(),notes);
    await page.setViewportSize({width:390,height:844});
    await field.getByLabel('Findings and intervention notes',{exact:true}).scrollIntoViewIfNeeded();
    assert.equal(await page.locator('.drawer-content').evaluate(el=>el.scrollWidth>el.clientWidth+1),false);
    await page.screenshot({path:path.join(output,'field-draft-offline-390.png')});
    await inspector.setOffline(false);await open();
    assert.equal(await field.getByLabel('Findings and intervention notes',{exact:true}).inputValue(),notes);
    assert.equal(await field.getByLabel('Record what you safely observed',{exact:true}).isChecked(),true);
    assert.equal(await field.getByLabel('Specify a follow-up observation',{exact:true}).isChecked(),true);
    assert.equal((await fetchCase()).evidence_records.length,0);
  });
  await check('Server commit with lost response restores and retries without duplicate evidence or audit',async()=>{
    const endpoint='**/api/v1/cases/'+id+'/inspection';let dropped=false;
    await page.route(endpoint,async route=>{
      if(route.request().method()==='POST'&&!dropped){dropped=true;const committed=await route.fetch();assert.equal(committed.status(),200);await route.abort('connectionfailed');}else await route.continue();
    });
    await field.getByRole('button',{name:'Submit inspection',exact:true}).click();
    await field.getByRole('button',{name:'Retry pending submission',exact:true}).waitFor();
    await field.getByText('Submission not confirmed. Your notes are retained. Retry the pending submission when the connection returns.',{exact:true}).waitFor();
    current=await fetchCase();assert.equal(current.evidence_records.length,1);
    const committedVersion=current.version;
    await page.unroute(endpoint);await open();
    assert.equal(await field.getByLabel('Findings and intervention notes',{exact:true}).isDisabled(),true);
    await field.getByRole('button',{name:'Retry pending submission',exact:true}).click();
    await field.getByText('Synchronized with server',{exact:true}).waitFor();
    current=await fetchCase();assert.equal(current.version,committedVersion);assert.equal(current.evidence_records.length,1);
    assert.equal(current.audits.filter(a=>a.action==='inspection').length,1);
    assert.equal(await page.evaluate(key=>localStorage.getItem(key),'civic-notes-demo-inspector-'+id),null);
  });
  await check('Concurrent case changes preserve the draft until explicit latest-version review',async()=>{
    await field.getByLabel('Findings and intervention notes',{exact:true}).fill('Synthetic second field observation awaiting concurrent review.');
    current=await fetchCase();
    const changed=await operator.request.post(base+'/api/v1/cases/'+id+'/transition',{headers:opHeaders,data:{status:'investigating',version:current.version,reason:'Synthetic concurrent reviewer changes case'}});assert.equal(changed.status(),200);
    await field.getByRole('button',{name:'Submit inspection',exact:true}).click();
    await field.getByRole('button',{name:'Refresh case for review',exact:true}).waitFor();
    assert.equal((await fetchCase()).evidence_records.length,1);
    await field.getByRole('button',{name:'Refresh case for review',exact:true}).click();
    await field.getByRole('button',{name:'Use reviewed case version',exact:true}).click();
    await field.getByRole('button',{name:'Submit inspection',exact:true}).click();
    await field.getByText('Synchronized with server',{exact:true}).waitFor();
    assert.equal((await fetchCase()).evidence_records.length,2);
    await field.getByText('Synchronized with server',{exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'field-draft-confirmed-390.png')});
  });
  await check('Draft storage is separated by account on the same browser',async()=>{
    const privateDraft='Synthetic inspector-only device draft.';
    await field.getByLabel('Findings and intervention notes',{exact:true}).fill(privateDraft);
    await page.keyboard.press('Escape');await page.goto(base+'/settings');await page.getByRole('button',{name:'Sign out',exact:false}).click();
    await login(inspector,'admin');await page.goto(base+'/incidents');await page.getByLabel('Filter incidents').fill(title);await page.locator('.case-row').filter({hasText:title}).click();
    await page.getByRole('button',{name:'Take action',exact:true}).click();
    assert.equal(await field.getByLabel('Findings and intervention notes',{exact:true}).inputValue(),'');
    assert.match(await page.evaluate(key=>localStorage.getItem(key),'civic-notes-demo-inspector-'+id),/Synthetic inspector-only device draft/);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  });
  assert.equal(results.page_errors.length,0);assert.equal(results.external_requests.length,0);
}catch{process.exitCode=1;}finally{
  results.finished_at=new Date().toISOString();await fs.writeFile(path.join(output,'offline-field-results.json'),JSON.stringify(results,null,2));await browser.close();
}
