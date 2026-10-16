import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.CIVIC_BASE_URL;
if(!base||!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Set CIVIC_BASE_URL to the isolated local acceptance server.');
const browser=await chromium.launch({headless:true,executablePath:process.env.CIVIC_BROWSER_PATH});
const results={checks:[],errors:[]};
const actors={};
async function actor(role){
  const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce'});
  await context.route('**/*',route=>new URL(route.request().url()).origin===base||/^(blob|data):/.test(route.request().url())?route.continue():route.abort());
  const login=await context.request.post(base+'/api/v1/auth/login',{data:{email:role+'@civicsignal.local',password:'CivicDemo!2026'}});
  assert.equal(login.status(),200);const auth=await login.json();
  const page=await context.newPage();page.on('pageerror',error=>results.errors.push(error.message));
  const request=async(path,data,method='post')=>{const response=await context.request[method](base+'/api/v1'+path,{data,headers:{'X-CSRF-Token':auth.csrf_token}});assert.ok(response.ok(),await response.text());return response.json()};
  return {context,page,request};
}
async function check(name,fn){try{await fn();results.checks.push({name,status:'passed'});console.log('PASS',name)}catch(e){results.checks.push({name,status:'failed',error:e.message});console.error('FAIL',name,e.message);for(const [role,a] of Object.entries(actors))await a.page.screenshot({path:'artifacts/verification/completion-failure-'+role+'.png',fullPage:true}).catch(()=>{})}}
async function openCase(actor,title){
  await actor.page.goto(base+'/overview');
  await actor.page.getByLabel('Search authorized cases').fill(title);
  await actor.page.locator('.search-results button').filter({hasText:title}).click();
  const drawer=actor.page.getByRole('dialog');await drawer.waitFor();
  await drawer.getByRole('button',{name:'Take action',exact:true}).click();
  return drawer;
}
async function action(page,button,suffix){
  const [response]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(suffix)),button.click()]);
  assert.equal(response.status(),200,await response.text());
  if(['/transition','/assign'].includes(suffix))await page.waitForFunction(()=>document.querySelector('#evidence-drawer textarea[placeholder="Explain the decision and the evidence you reviewed."]')?.value==='');
  return response.json();
}
try{
  for(const role of ['admin','operator','inspector','citizen'])actors[role]=await actor(role);
  await check('Water configuration persists, review shows honest unknown accounting, Marathi and mobile layout',async()=>{
    const page=actors.admin.page;await page.goto(base+'/domains/water');await page.getByRole('button',{name:'Operations',exact:true}).click();
    const panel=page.locator('.water-operations');await panel.getByLabel('Service zone',{exact:true}).selectOption('river');
    await panel.locator('summary').click();
    const supply=panel.getByRole('group',{name:'Supply windows',exact:true});
    if(await supply.getByRole('button',{name:'Remove window'}).count()===0)await supply.getByRole('button',{name:'Add window'}).click();
    const scheduleLabel='Synthetic morning supply '+Date.now();
    await supply.getByLabel('Description',{exact:true}).first().fill(scheduleLabel);
    await panel.getByLabel('Reason and boundary assumptions').fill('Synthetic browser acceptance: record supply schedule only.');
    const saved=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().includes('/water/zones/river/operations'));
    await panel.getByRole('button',{name:'Save configuration',exact:true}).click();assert.equal((await saved).status(),200);
    await page.reload();await page.getByRole('button',{name:'Operations',exact:true}).click();await panel.locator('summary').click();
    assert.equal(await panel.getByLabel('Description',{exact:true}).first().inputValue(),scheduleLabel);
    await panel.getByRole('button',{name:'Review water observations',exact:true}).click();
    await panel.getByRole('heading',{name:'Accounting result',exact:true}).waitFor();
    assert.match(await panel.innerText(),/Unavailable/);
    assert.match(await panel.innerText(),/review outside window/);
    for(const width of [1440,768,390]){
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
      assert.equal(await panel.evaluate(node=>Array.from(node.children).some(child=>child.getBoundingClientRect().right>node.getBoundingClientRect().right+1)),false,'Water panel content is clipped');
      await page.screenshot({path:`artifacts/verification/water-operations-${width}.png`,fullPage:true});
    }
    await page.getByRole('button',{name:'Switch interface language to Marathi',exact:true}).click();
    await panel.getByRole('heading',{name:'पाणीपुरवठा आढावा',exact:true}).waitFor();
    await page.screenshot({path:'artifacts/verification/water-operations-marathi-390.png',fullPage:true});
    await page.locator('.language-toggle').click();
  });
  // The isolated fixture explicitly records a synthetic qualification.
  const registry=await (await actors.admin.context.request.get(base+'/api/v1/admin')).json();
  const inspector=registry.users.find(u=>u.id==='demo-inspector');
  await actors.admin.request('/admin/users/'+inspector.id,{role:inspector.role,domains:inspector.domains,zones:inspector.zones,active:true,electrical_qualified:true,reason:'Synthetic acceptance fixture qualification'},'patch');
  // Permission edits correctly revoke prior sessions. Authenticate with the new grant.
  await actors.inspector.context.close();actors.inspector=await actor('inspector');
  for(const domain of ['water','electricity','roads','drainage','waste','streetlights','general'])await check('Browser inspection, intervention, monitoring and human closure: '+domain,async()=>{
    const title='Acceptance '+domain+' '+Date.now();
    const report=await actors.citizen.request('/reports',{domain,zone_id:'river',title,description:'Clearly labelled synthetic acceptance observation, not a real incident.',location:'Synthetic acceptance facility',idempotency_key:crypto.randomUUID()});
    let drawer=await openCase(actors.operator,title);
    await drawer.getByLabel('Reason / reviewed evidence').fill('Synthetic review: investigate the reported condition.');
    await drawer.getByLabel('Next state',{exact:true}).selectOption('investigating');
    await action(actors.operator.page,drawer.getByRole('button',{name:'Record review decision'}),'/transition');
    await drawer.getByLabel('Reason / reviewed evidence').fill('Assign a synthetic site inspection to the responsible inspector.');
    await drawer.getByLabel('Lead inspector',{exact:true}).selectOption('demo-inspector');
    await action(actors.operator.page,drawer.getByRole('button',{name:'Save assignment',exact:true}),'/assign');
    drawer=await openCase(actors.inspector,title);
    const field=drawer.getByTestId('field-notes');
    await field.getByLabel('Findings and intervention notes',{exact:true}).fill('Synthetic inspection with a recorded observation and uncertainty.');
    await field.getByRole('checkbox',{name:'Record what you safely observed',exact:true}).check();
    if(domain==='electricity')await field.getByRole('checkbox',{name:/I confirm I am/}).check();
    const schema=await (await actors.inspector.context.request.get(base+'/api/v1/cases/'+report.case_id+'/field-schema')).json();
    const first=schema.fields[0];
    await field.getByLabel(first.label,{exact:false}).fill(first.type==='number'?'50':'Synthetic field observation');
    const inspection=await action(actors.inspector.page,field.getByRole('button',{name:'Submit inspection',exact:true}),'/inspection');
    assert.ok(inspection.evidence_records.some(r=>Object.keys(r.observations).includes(first.key)));
    await field.getByText('Synchronized with server',{exact:true}).waitFor();
    await field.getByLabel('Findings and intervention notes',{exact:true}).fill('Synthetic intervention and responsible crew recorded for acceptance.');
    for(const name of ['Record what you safely observed','Document the action and responsible crew','Specify a follow-up observation'])await field.getByRole('checkbox',{name,exact:true}).check();
    if(domain==='electricity')await field.getByRole('checkbox',{name:/I confirm I am/}).check();
    await action(actors.inspector.page,field.getByRole('button',{name:'Submit intervention',exact:true}),'/intervention');
    await field.getByText('Synchronized with server',{exact:true}).waitFor();
    await drawer.getByLabel('Next state',{exact:true}).selectOption('monitoring');
    await drawer.getByLabel('Reason / reviewed evidence').fill('Synthetic follow-up observation is now required.');
    await action(actors.inspector.page,drawer.getByRole('button',{name:'Record review decision'}),'/transition');
    await field.getByLabel('Findings and intervention notes',{exact:true}).fill('Synthetic follow-up documents current conditions for human review.');
    await field.getByRole('checkbox',{name:'Specify a follow-up observation',exact:true}).check();
    if(domain==='electricity')await field.getByRole('checkbox',{name:/I confirm I am/}).check();
    await action(actors.inspector.page,field.getByRole('button',{name:'Submit follow-up',exact:true}),'/inspection');
    drawer=await openCase(actors.operator,title);
    await drawer.getByLabel('Next state',{exact:true}).selectOption('resolved');
    await drawer.getByLabel('Reason / reviewed evidence').fill('Synthetic human review of recorded intervention and follow-up evidence.');
    const closed=await action(actors.operator.page,drawer.getByRole('button',{name:'Record review decision'}),'/transition');
    assert.equal(closed.status,'resolved');assert.ok(closed.priority_review);
    const tracked=await (await actors.citizen.context.request.get(base+'/api/v1/reports/'+report.id)).json();
    assert.equal(tracked.status,'resolved');
  });
}finally{await fs.writeFile('artifacts/verification/completion-browser.json',JSON.stringify(results,null,2));await browser.close()}
if(results.errors.length||results.checks.some(c=>c.status!=='passed'))process.exitCode=1;
