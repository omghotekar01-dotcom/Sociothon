import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.CIVIC_BASE_URL;
if(!base||!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Use an isolated localhost acceptance server');
const browser=await chromium.launch({headless:true,executablePath:process.env.CIVIC_BROWSER_PATH});
const result={steps:[],errors:[]};
const contexts=[];
async function account(role,email,password){
 const ctx=await browser.newContext({viewport:{width:1440,height:920},reducedMotion:'reduce',locale:'en-IN'});
 contexts.push(ctx);
 await ctx.route('**/*',r=>new URL(r.request().url()).origin===base||/^(blob|data):/.test(r.request().url())?r.continue():r.abort());
 const auth=await ctx.request.post(base+'/api/v1/auth/login',{data:{email:email||role+'@civicsignal.local',password:password||'CivicDemo!2026'}});
 assert.equal(auth.status(),200,await auth.text());
 const {csrf_token}=await auth.json();
 const page=await ctx.newPage();
 const post=async(path,data)=>{
  const res=await ctx.request.post(base+'/api/v1'+path,{data,headers:{'X-CSRF-Token':csrf_token}});
  assert.ok(res.ok(),await res.text());return res.json();
 };
 return {ctx,page,post};
}
async function step(name,run){
 try{await run();result.steps.push({name,status:'passed'});console.log('PASS',name)}
 catch(e){result.steps.push({name,status:'failed',error:e.message});result.errors.push(name+': '+e.message);console.error('FAIL',name,e.message)}
}
await fs.mkdir('artifacts/verification',{recursive:true});
try{
 const admin=await account('admin');
 const operator=await account('operator');
 const citizen=await account('citizen');
 let inspectorId='',reportId='',caseId='';
 const unique=String(Date.now());
 const email='ward-inspector-'+unique+'@example.test',password='DemoWardInspector-'+unique;
 const title='Four-role handoff '+unique,description='Synthetic citizen observation with a specific water issue and photographs.';
 await step('Administrator creates an inspector from the UI',async()=>{
  await admin.page.goto(base+'/admin');
  await admin.page.getByRole('heading',{name:'Add a staff account'}).waitFor();
  const form=admin.page.locator('.staff-create-panel form');
  await form.getByLabel('Full name').fill('Ward Service Inspector');
  await form.getByLabel('Staff email').fill(email);
  await form.getByLabel('Initial password').fill(password);
  const boot=await(await admin.ctx.request.get(base+'/api/v1/bootstrap')).json();
  const zone=boot.zones.find(z=>z.id==='river');assert.ok(zone);
  await form.getByRole('checkbox',{name:zone.name}).check();
  await form.getByLabel('Reason for staff creation').fill('Synthetic role handoff acceptance scenario');
  const response=admin.page.waitForResponse(r=>r.url().endsWith('/api/v1/admin/staff')&&r.request().method()==='POST');
  await form.getByRole('button',{name:'Create staff account'}).click();
  const saved=await response;assert.equal(saved.status(),201,await saved.text());
  inspectorId=(await saved.json()).id;
  await admin.page.getByText('Ward Service Inspector added.',{exact:false}).waitFor();
 });
 await step('Citizen saves report and private photo',async()=>{
  const saved=await citizen.post('/reports',{
   domain:'water',zone_id:'river',title,description,
   location:'Synthetic public market entrance',idempotency_key:crypto.randomUUID()
  });
  caseId=saved.case_id;reportId=saved.id;
  const image=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLytQAAAABJRU5ErkJggg==','base64');
  const upload=await citizen.ctx.request.post(base+'/api/v1/cases/'+caseId+'/evidence',{
   headers:{'X-CSRF-Token':(await (await citizen.ctx.request.get(base+'/api/v1/auth/me')).json()).csrf_token},
   multipart:{file:{name:'demo.png',mimeType:'image/png',buffer:image},notes:'Synthetic citizen photo',idempotency_key:crypto.randomUUID()}
  });
  assert.equal(upload.status(),200,await upload.text());
  assert.ok(reportId);
 });
 await step('Operator sees saved text and photo in citizen inbox',async()=>{
  await operator.page.goto(base+'/reports');
  await operator.page.getByRole('heading',{name:'Submitted reports'}).waitFor();
  await operator.page.locator('.staff-report-list button').filter({hasText:title}).click();
  await operator.page.locator('.staff-inbox-detail').getByText(description).waitFor();
  const img=operator.page.locator('.staff-photo-grid img');
  await img.first().waitFor();
  assert.match(await img.first().getAttribute('src'),/\/api\/v1\/evidence\/.+\/download/);
  await operator.page.getByRole('button',{name:/Open Evidence Passport and assign/}).click();
  await operator.page.getByRole('dialog').waitFor();
 });
 await step('Operator selects new inspector from scoped list and saves assignment',async()=>{
  const drawer=operator.page.getByRole('dialog');
  await drawer.getByRole('button',{name:'Take action',exact:true}).click();
  await drawer.getByLabel('Reason / reviewed evidence').fill('Investigate this incoming synthetic report');
  await drawer.getByLabel('Next state',{exact:true}).selectOption('investigating');
  const review=operator.page.waitForResponse(r=>r.url().endsWith('/transition')&&r.request().method()==='POST');
  await drawer.getByRole('button',{name:'Record review decision'}).click();
  assert.equal((await review).status(),200);
  await drawer.getByLabel('Reason / reviewed evidence').fill('Assign an authorized inspector for the same zone and department');
  await drawer.getByLabel('Lead inspector').selectOption(inspectorId);
  const response=operator.page.waitForResponse(r=>r.url().endsWith('/assign')&&r.request().method()==='POST');
  await drawer.getByRole('button',{name:'Save assignment'}).click();
  assert.equal((await response).status(),200);
 });
 await step('New inspector signs in and sees assigned report and photo',async()=>{
  const inspector=await account('inspector',email,password);
  await inspector.page.goto(base+'/inspector');
  await inspector.page.getByText(title,{exact:false}).first().waitFor();
  await inspector.page.getByText(title,{exact:false}).first().click();
  const drawer=inspector.page.getByRole('dialog');await drawer.waitFor();
  await drawer.getByText(description).first().waitFor();
  assert.equal(await drawer.locator('.citizen-photo-grid img').count(),1);
  for(const width of [1440,390]){
   await inspector.page.setViewportSize({width,height:900});
   assert.equal(await inspector.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false);
  }
  await inspector.page.screenshot({path:'artifacts/verification/four-role-inspector.png',fullPage:true});
 });
}finally{
 await fs.writeFile('artifacts/verification/four-role-handoff.json',JSON.stringify(result,null,2));
 await Promise.all(contexts.map(x=>x.close().catch(()=>{})));await browser.close();
}
if(result.errors.length)process.exitCode=1;
