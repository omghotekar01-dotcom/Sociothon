import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.env.CIVIC_PLAYWRIGHT_PATH||'playwright');
const base=process.env.CIVIC_BASE_URL||'http://127.0.0.1:8000';
const artifact=path.resolve('artifacts/verification');await fs.mkdir(artifact,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CIVIC_BROWSER_PATH?{executablePath:process.env.CIVIC_BROWSER_PATH}:{})});
const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
const observer=await browser.newContext();
const result={checks:[],page_errors:[],external_requests:[],started_at:new Date().toISOString()};
await context.route('**/*',route=>{const url=new URL(route.request().url());if(['localhost','127.0.0.1'].includes(url.hostname)||['data:','blob:'].includes(url.protocol))return route.continue();result.external_requests.push(url.origin);return route.abort();});
const auth=await context.request.post(base+'/api/v1/auth/login',{data:{email:'citizen@civicsignal.local',password:'CivicDemo!2026'}});assert.equal(auth.status(),200);
const csrf=(await auth.json()).csrf_token;
assert.equal((await observer.request.post(base+'/api/v1/auth/login',{data:{email:'operator@civicsignal.local',password:'CivicDemo!2026'}})).status(),200);
const page=await context.newPage();page.on('pageerror',error=>result.page_errors.push(error.message));
const button=name=>page.getByRole('button',{name,exact:true});
const widget=()=>page.getByTestId('photo-upload');
const input=()=>widget().getByLabel('खाजगी छायाचित्र जोडा',{exact:true});
const storageKey=report=>'civic-photo-pending-demo-citizen-'+report.case_id;
const stored=report=>page.evaluate(key=>localStorage.getItem(key),storageKey(report));
// A synthetic one-pixel PNG; never a user's photograph.
const bytes=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=','base64');
const original={name:'synthetic-photo.png',mimeType:'image/png',buffer:bytes};
const different={name:'different-photo.png',mimeType:'image/png',buffer:Buffer.concat([bytes,Buffer.from([0])])};
async function makeReport(suffix){
  const response=await context.request.post(base+'/api/v1/reports',{headers:{'X-CSRF-Token':csrf},data:{domain:'water',zone_id:'river',title:'Synthetic photo reconnect '+Date.now()+' '+suffix,description:'Synthetic private photo recovery verification, not a real observation.',location:'Public test landmark',idempotency_key:crypto.randomUUID()}});
  assert.equal(response.status(),201);return response.json();
}
async function open(report){await page.goto(base+'/reports');await page.getByRole('heading',{name:/Your reports, with|आपले अहवाल आणि/}).waitFor();if(await button('Switch reporting language to Marathi').count())await button('Switch reporting language to Marathi').click();await page.locator('.report-list button').filter({hasText:report.title}).click();await widget().waitFor();}
async function count(report){
  const response=await observer.request.get(base+'/api/v1/cases/'+report.case_id);assert.equal(response.status(),200);
  const body=await response.json();return {evidence:body.evidence_records.filter(e=>e.kind==='photograph').length,audits:body.audits.filter(a=>a.action==='evidence_added').length};
}
async function check(name,fn){try{await fn();result.checks.push({name,status:'passed'});console.log('PASS',name);}catch(error){result.checks.push({name,status:'failed',error:error.message});console.error('FAIL',name,error.message);await page.screenshot({path:path.join(artifact,'offline-photo-failure.png'),fullPage:true}).catch(()=>{});throw error;}}
try{
  const first=await makeReport('lost confirmation');
  await check('Offline photo selection stays in memory and reconnect never automatically uploads',async()=>{
    await open(first);await context.setOffline(true);await input().setInputFiles(original);
    await widget().getByText('निवडले: synthetic-photo.png',{exact:true}).waitFor();
    assert.equal(await button('खाजगी छायाचित्र पाठवा').isDisabled(),true);assert.equal(await stored(first),null);
    await page.screenshot({path:path.join(artifact,'photo-offline-390.png'),fullPage:true});
    await context.setOffline(false);assert.deepEqual(await count(first),{evidence:0,audits:0});
  });
  await check('Dropped post-commit confirmation recovers after reload without image storage or a second POST',async()=>{
    await widget().getByLabel('या उपकरणावर अपलोडचा पुनर्प्राप्ती संदर्भ ठेवा').check();
    let posts=0;
    await page.route('**/api/v1/cases/*/evidence',async route=>{posts++;const response=await route.fetch();assert.equal(response.status(),200,await response.text());await route.abort('connectionfailed');});
    await button('खाजगी छायाचित्र पाठवा').click();await widget().getByRole('alert').filter({hasText:'अपलोडची पुष्टी मिळाली नाही.'}).waitFor();
    const reference=JSON.parse(await stored(first));assert.deepEqual(Object.keys(reference).sort(),['hash','key','schema']);
    assert.equal(reference.hash.length,64);assert.deepEqual(await count(first),{evidence:1,audits:1});
    await open(first);await button('छायाचित्राची स्थिती तपासा').click();
    await widget().getByText('छायाचित्र सर्व्हरवर जतन झाले.',{exact:true}).waitFor();
    assert.equal(posts,1);assert.equal(await stored(first),null);assert.deepEqual(await count(first),{evidence:1,audits:1});
    const url=await widget().getByRole('link',{name:'जतन केलेले छायाचित्र पहा'}).getAttribute('href');
    assert.equal((await context.request.get(base+url)).status(),200);
    await page.unroute('**/api/v1/cases/*/evidence');
    for(const width of [390,768,1440]){await page.setViewportSize({width,height:900});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await widget().screenshot({path:path.join(artifact,`photo-confirmed-${width}.png`)});}
    await page.setViewportSize({width:390,height:844});
  });
  const second=await makeReport('before commit');
  await check('Pre-commit failure restores reference, rejects a different file and retries the original once',async()=>{
    await open(second);await input().setInputFiles(original);await widget().getByText('निवडले: synthetic-photo.png',{exact:true}).waitFor();
    await widget().getByLabel('या उपकरणावर अपलोडचा पुनर्प्राप्ती संदर्भ ठेवा').check();
    await page.route('**/api/v1/cases/*/evidence',route=>route.abort('connectionfailed'));
    await button('खाजगी छायाचित्र पाठवा').click();await widget().getByRole('alert').filter({hasText:'अपलोडची पुष्टी मिळाली नाही.'}).waitFor();
    const reference=JSON.parse(await stored(second));assert.deepEqual(await count(second),{evidence:0,audits:0});
    await page.unroute('**/api/v1/cases/*/evidence');await open(second);await button('छायाचित्राची स्थिती तपासा').click();
    await widget().getByText('या अपलोडचे जतन केलेले छायाचित्र सापडले नाही. मूळ फाइल निवडून पुन्हा प्रयत्न करा.',{exact:true}).waitFor();
    await input().setInputFiles(different);await widget().getByRole('alert').filter({hasText:'ही वेगळी फाइल आहे.'}).waitFor();
    assert.equal(await button('तेच छायाचित्र पुन्हा पाठवा').isDisabled(),true);assert.equal(JSON.parse(await stored(second)).key,reference.key);
    await input().setInputFiles(original);await widget().getByText('निवडले: synthetic-photo.png',{exact:true}).waitFor();
    await button('तेच छायाचित्र पुन्हा पाठवा').click();await widget().getByText('छायाचित्र सर्व्हरवर जतन झाले.',{exact:true}).waitFor();
    assert.deepEqual(await count(second),{evidence:1,audits:1});assert.equal(await stored(second),null);
  });
  const third=await makeReport('isolation');
  await check('Changing reports discards in-memory selection and rejected images are not acknowledged',async()=>{
    await open(second);await input().setInputFiles(original);await widget().getByText('निवडले: synthetic-photo.png',{exact:true}).waitFor();
    await page.locator('.report-list button').filter({hasText:third.title}).click();
    await page.locator('.report-tracking').getByRole('heading',{name:third.title,exact:true}).waitFor();
    assert.equal(await button('खाजगी छायाचित्र पाठवा').isDisabled(),true);assert.equal(await widget().getByText('निवडले: synthetic-photo.png',{exact:true}).count(),0);
    await input().setInputFiles({name:'invalid.png',mimeType:'image/png',buffer:Buffer.from('not an image')});await widget().getByText('निवडले: invalid.png',{exact:true}).waitFor();
    await button('खाजगी छायाचित्र पाठवा').click();await widget().getByRole('alert').filter({hasText:'हे छायाचित्र स्वीकारता आले नाही.'}).waitFor();
    assert.equal(await page.getByTestId('pending-photo').count(),0);assert.deepEqual(await count(third),{evidence:0,audits:0});assert.equal(await stored(third),null);
  });
  await check('Corrupt references are preserved until explicit clear; storage failure does not claim a saved copy',async()=>{
    await page.evaluate(key=>localStorage.setItem(key,'{"schema":999}'),storageKey(third));await open(third);
    await widget().getByRole('alert').filter({hasText:'या उपकरणावरील पुनर्प्राप्ती संदर्भ'}).waitFor();assert.equal(await input().isDisabled(),true);assert.equal(await stored(third),'{"schema":999}');
    await button('उपकरणावरील अपलोड संदर्भ काढा').click();assert.equal(await stored(third),null);
    await input().setInputFiles(original);await widget().getByText('निवडले: synthetic-photo.png',{exact:true}).waitFor();await widget().getByLabel('या उपकरणावर अपलोडचा पुनर्प्राप्ती संदर्भ ठेवा').check();
    await page.evaluate(()=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key.startsWith('civic-photo-pending-'))throw new DOMException('Simulated quota exceeded','QuotaExceededError');return original.call(this,key,value);};});
    await page.route('**/api/v1/cases/*/evidence',route=>route.abort('connectionfailed'));
    await button('खाजगी छायाचित्र पाठवा').click();await widget().getByRole('alert').filter({hasText:'अपलोडची पुष्टी मिळाली नाही.'}).waitFor();
    await widget().getByRole('alert').filter({hasText:'या उपकरणावरील पुनर्प्राप्ती संदर्भ'}).waitFor();assert.equal(await stored(third),null);assert.deepEqual(await count(third),{evidence:0,audits:0});
    await page.unroute('**/api/v1/cases/*/evidence');
  });
  assert.equal(result.page_errors.length,0);assert.equal(result.external_requests.length,0);
}finally{
  result.finished_at=new Date().toISOString();await fs.writeFile(path.join(artifact,'offline-photo-results.json'),JSON.stringify(result,null,2));await browser.close();
}
