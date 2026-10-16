import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.env.CIVIC_PLAYWRIGHT_PATH||'playwright');
const base=process.env.CIVIC_BASE_URL||'http://127.0.0.1:8000';
const artifact=path.resolve('artifacts/verification');await fs.mkdir(artifact,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CIVIC_BROWSER_PATH?{executablePath:process.env.CIVIC_BROWSER_PATH}:{})});
const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'});
const result={checks:[],page_errors:[],external_requests:[],started_at:new Date().toISOString()};
await context.route('**/*',route=>{const url=new URL(route.request().url());if(['localhost','127.0.0.1'].includes(url.hostname)||['data:','blob:'].includes(url.protocol))return route.continue();result.external_requests.push(url.origin);return route.abort();});
const auth=await context.request.post(base+'/api/v1/auth/login',{data:{email:'citizen@civicsignal.local',password:'CivicDemo!2026'}});assert.equal(auth.status(),200);
const page=await context.newPage();page.on('pageerror',error=>result.page_errors.push(error.message));
const storageKey='civic-draft-demo-citizen';
const title='Synthetic Marathi reconnect '+Date.now();
const location='सार्वजनिक बाजाराच्या प्रवेशद्वाराजवळ';
const description='सुरक्षित अंतरावरून पाणी साचलेले दिसले. हा जोडणी पुनर्प्राप्तीचा कृत्रिम चाचणी अहवाल आहे.';
const button=name=>page.getByRole('button',{name,exact:true});
const reports=async()=>await (await context.request.get(base+'/api/v1/reports')).json();
async function open(){await page.goto(base+'/report');await page.getByRole('heading',{name:/Let’s get it|योग्य विभागापर्यंत/}).waitFor();if(await button('Switch reporting language to Marathi').count())await button('Switch reporting language to Marathi').click();}
async function fillReport(value){await button('पुढे').click();await page.getByLabel('ठिकाण किंवा जवळची खूण').fill(location);await button('पुढे').click();await page.getByLabel('आपण काय पाहिले?').fill(value);await page.getByLabel('निरीक्षणाचे वर्णन करा').fill(description);await button('पुढे').click();await button('मसुदा जतन करा').click();}
async function check(name,fn){try{await fn();result.checks.push({name,status:'passed'});console.log('PASS',name);}catch(error){result.checks.push({name,status:'failed',error:error.message});console.error('FAIL',name,error.message);await page.screenshot({path:path.join(artifact,'offline-report-failure.png'),fullPage:true}).catch(()=>{});throw error;}}
let savedKey;
try{
  await check('Marathi offline draft restores text and omits location until explicitly retained',async()=>{
    await open();await context.setOffline(true);await fillReport(title);
    assert.equal(await button('अहवाल पाठवा').isDisabled(),true);
    const stored=JSON.parse(await page.evaluate(key=>localStorage.getItem(key),storageKey));savedKey=stored.form.idempotency_key;
    assert.equal(stored.form.location,'');assert.equal(stored.form.title,title);assert.equal(stored.pending,false);
    await page.screenshot({path:path.join(artifact,'citizen-offline-draft-390.png'),fullPage:true});
    await context.setOffline(false);await open();await button('पुन्हा उघडा').click();
    assert.equal(await page.getByLabel('ठिकाण किंवा जवळची खूण').inputValue(),'');
    await page.getByLabel('ठिकाण किंवा जवळची खूण').fill(location);await button('पुढे').click();
    assert.equal(await page.getByLabel('आपण काय पाहिले?').inputValue(),title);assert.equal(await page.getByLabel('निरीक्षणाचे वर्णन करा').inputValue(),description);
    await button('पुढे').click();assert.equal((await reports()).filter(r=>r.title===title).length,0);
  });
  await check('Lost report confirmation recovers the original receipt after reload without location or another POST',async()=>{
    let posted=0;
    await page.route('**/api/v1/reports',async route=>{if(route.request().method()==='POST'){posted++;const response=await route.fetch();assert.equal(response.status(),201);await route.abort('connectionfailed');}else await route.continue();});
    await button('अहवाल पाठवा').click();await page.getByTestId('pending-report').waitFor();
    await page.getByText('अहवालाची पुष्टी मिळालेली नाही. याच अहवालाची स्थिती तपासा किंवा पुन्हा प्रयत्न करा; दुसरी प्रत तयार करू नका.',{exact:true}).waitFor();
    const pending=JSON.parse(await page.evaluate(key=>localStorage.getItem(key),storageKey));assert.equal(pending.pending,true);assert.equal(pending.form.location,'');assert.equal(pending.form.idempotency_key,savedKey);
    const stored=(await reports()).filter(r=>r.title===title);assert.equal(stored.length,1);
    await open();await button('पुन्हा उघडा').click();await button('अहवालाची स्थिती तपासा').click();
    await page.getByRole('heading',{name:'आपला अहवाल प्राप्त झाला.',exact:true}).waitFor();
    assert.equal(posted,1);assert.ok((await page.locator('.receipt').innerText()).includes(stored[0].receipt));
    assert.equal(await page.evaluate(key=>localStorage.getItem(key),storageKey),null);
    assert.equal((await reports()).filter(r=>r.title===title).length,1);
    await page.unroute('**/api/v1/reports');
    await page.screenshot({path:path.join(artifact,'citizen-recovered-receipt-390.png'),fullPage:true});
  });
  await check('Failure before commit restores pending report and accepts the complete re-entered location',async()=>{
    const second=title+' before commit';await open();await fillReport(second);
    await page.route('**/api/v1/reports',route=>route.request().method()==='POST'?route.abort('connectionfailed'):route.continue());
    await button('अहवाल पाठवा').click();await page.getByTestId('pending-report').waitFor();
    await page.getByText('अहवालाची पुष्टी मिळालेली नाही. याच अहवालाची स्थिती तपासा किंवा पुन्हा प्रयत्न करा; दुसरी प्रत तयार करू नका.',{exact:true}).waitFor();
    await page.unroute('**/api/v1/reports');await open();await button('पुन्हा उघडा').click();await button('अहवालाची स्थिती तपासा').click();
    await page.getByText('अद्याप जतन केलेला अहवाल सापडला नाही. याच अहवालासाठी पुन्हा प्रयत्न करा.',{exact:true}).waitFor();
    await page.getByLabel('मूळ ठिकाण पुन्हा लिहा').fill(location);
    assert.equal(await page.getByLabel('मूळ ठिकाण पुन्हा लिहा').inputValue(),location);
    assert.equal(await button('मागे').isDisabled(),true);
    await button('तोच अहवाल पुन्हा पाठवा').click();await page.getByRole('heading',{name:'आपला अहवाल प्राप्त झाला.',exact:true}).waitFor();
    const saved=(await reports()).filter(r=>r.title===second);assert.equal(saved.length,1);assert.equal(saved[0].location,location);
  });
  await check('Location opt-in restores full draft and malformed drafts show a recoverable error',async()=>{
    await open();await fillReport(title+' optional location');
    await page.getByLabel('उपकरणावरील मसुद्यात अहवालाचे ठिकाणही जतन करा').check();
    assert.equal(JSON.parse(await page.evaluate(key=>localStorage.getItem(key),storageKey)).form.location,location);
    await open();await button('पुन्हा उघडा').click();assert.ok((await page.locator('.review-report').innerText()).includes(location));
    await page.evaluate(key=>localStorage.setItem(key,'{"schema":999}'),storageKey);await open();await button('पुन्हा उघडा').click();
    await page.getByRole('alert').filter({hasText:'जतन केलेला मसुदा वाचता आला नाही.'}).waitFor();
    assert.equal(await page.evaluate(key=>localStorage.getItem(key),storageKey),'{"schema":999}');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await button('काढा').click();assert.equal(await page.evaluate(key=>localStorage.getItem(key),storageKey),null);
  });
  assert.equal(result.page_errors.length,0);assert.equal(result.external_requests.length,0);
}catch{process.exitCode=1;}finally{result.finished_at=new Date().toISOString();await fs.writeFile(path.join(artifact,'offline-report-results.json'),JSON.stringify(result,null,2));await browser.close();}
