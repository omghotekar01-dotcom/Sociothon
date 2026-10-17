import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.CIVIC_PLAYWRIGHT_PATH || 'playwright');
const base = process.env.CIVIC_BASE_URL || 'http://127.0.0.1:8000';
const artifact = path.resolve('artifacts/verification');
await fs.mkdir(artifact, {recursive:true});
const options = {headless:true};
if (process.env.CIVIC_BROWSER_PATH) options.executablePath = process.env.CIVIC_BROWSER_PATH;
const browser = await chromium.launch(options);
const results = {base, started_at:new Date().toISOString(), checks:[], external_requests:[], console_errors:[], api_errors:[]};
const context = await browser.newContext({viewport:{width:1440,height:1000}, reducedMotion:'reduce', locale:'en-IN', timezoneId:'Asia/Kolkata'});
await context.route('**/*', async route => {
  const url = new URL(route.request().url());
  if (['127.0.0.1','localhost'].includes(url.hostname) || ['data:','blob:'].includes(url.protocol)) return route.continue();
  results.external_requests.push(url.origin + url.pathname);
  return route.abort('blockedbyclient');
});
const page = await context.newPage();
page.on('pageerror', error => results.console_errors.push(error.message));
page.on('response', response => {
  if (response.url().includes('/api/v1/') && response.status() >= 400 && !(response.status()===401 && response.url().endsWith('/auth/me'))) results.api_errors.push({url:response.url(),status:response.status()});
});
async function check(name, fn) {
  const started=Date.now();
  try {await fn(); results.checks.push({name,status:'passed',duration_ms:Date.now()-started});console.log('PASS',name);}
  catch(error) {results.checks.push({name,status:'failed',error:error.message});console.error('FAIL',name,error.message);await page.screenshot({path:path.join(artifact,'failure-'+results.checks.length+'.png'),fullPage:true}).catch(()=>{});}
}
async function ready(){await page.locator('h1').first().waitFor({timeout:30000});await page.waitForTimeout(500);}
await check('Landing works with external network denied', async()=>{
  await page.goto(base);await ready();
  assert.match(await page.locator('h1').innerText(),/Notice an issue/i);
  await page.getByRole('heading',{name:'Where would you like to start?'}).waitFor();
  await page.screenshot({path:path.join(artifact,'landing-1440.png'),fullPage:true});
  await page.locator('.welcome-action-grid').getByRole('button',{name:/Dashboard/}).click();
  await page.waitForURL('**/overview');await page.getByText('City pulse',{exact:false}).first().waitFor();
});
for(const width of [1440,768,390]) await check('Command centre viewport '+width,async()=>{
  await page.setViewportSize({width,height:width===390?844:1000});await page.goto(base+'/overview');await ready();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
  assert.equal(overflow,false,'Page has horizontal overflow');
  await page.screenshot({path:path.join(artifact,`command-centre-${width}.png`),fullPage:true});
});
await page.setViewportSize({width:1440,height:1000});
const routes=['/incidents','/domains/water','/domains/electricity','/domains/roads','/domains/drainage','/domains/waste','/domains/streetlights','/domains/general','/network','/forecast','/scenarios','/demo','/cross-domain','/impact','/lab','/report','/reports','/inspector','/notifications','/settings','/about'];
for(const route of routes)await check('Route '+route,async()=>{
  const before=results.api_errors.length;await page.goto(base+route);await ready();
  assert.equal(await page.locator('main').count(),1);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'Horizontal overflow');
  assert.equal(results.api_errors.length,before,'Route made a failed API request: '+JSON.stringify(results.api_errors.slice(before)));
});
await check('Timeline synchronizes observations, map, chart, URL and incident register',async()=>{
  await page.goto(base+'/overview');await ready();
  const bootstrap=await (await context.request.get(base+'/api/v1/bootstrap')).json();
  await page.getByRole('button',{name:'Latest water readings',exact:true}).click();
  const query=new URL(page.url()).searchParams;
  assert.equal(query.get('hours'),'24');
  const end=Date.parse(query.get('at')), start=end-24*3600000;
  const expectedCases=bootstrap.cases.filter(c=>{
    const eventStart=Date.parse(c.evidence?.start||c.created_at);
    const eventEnd=c.evidence?.start&&c.evidence?.end?Date.parse(c.evidence.end):eventStart+1;
    return eventStart<end&&eventEnd>start;
  });
  const expectedReadings=bootstrap.series.filter(r=>Date.parse(r.timestamp)<end&&Date.parse(r.timestamp)+(r.interval_minutes||60)*60000>start);
  assert.match(await page.getByTestId('timeline-summary').innerText(),new RegExp(`${expectedCases.length} cases · ${expectedReadings.length} water intervals`));
  assert.deepEqual(await page.locator('.map-node').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-case-id'))),expectedCases.slice(0,12).map(c=>c.id));
  assert.deepEqual(await page.getByTestId('timeline-case-list').locator('.case-row').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-case-id'))),expectedCases.slice(0,6).map(c=>c.id));
  await page.getByRole('button',{name:'Data table',exact:true}).click();
  assert.equal(await page.getByTestId('signal-table').locator('tbody tr').count(),expectedReadings.length);
  assert.ok(await page.getByTestId('signal-table').getByText('Flagged',{exact:true}).count()>0);
  const summary=await page.getByTestId('timeline-summary').innerText();
  await page.reload();await ready();
  assert.equal(await page.getByTestId('timeline-summary').innerText(),summary);
  await page.getByRole('button',{name:'View incident register',exact:false}).click();
  assert.equal(new URL(page.url()).pathname,'/incidents');
  assert.equal(new URL(page.url()).searchParams.get('at'),query.get('at'));
  await page.reload();await ready();
  assert.equal(await page.locator('.case-row').count(),expectedCases.length);
  await page.goto(base+'/overview?'+query);await ready();
  await page.getByRole('slider',{name:'Observation window end'}).press('Home');
  assert.notEqual(new URL(page.url()).searchParams.get('at'),query.get('at'));
  await page.getByRole('button',{name:'Reset timeline',exact:true}).click();
  assert.equal(new URL(page.url()).searchParams.has('at'),false);
  assert.match(await page.getByTestId('timeline-summary').innerText(),new RegExp(`${bootstrap.cases.length} cases`));
});
await check('Network closures reroute, disconnect, reopen and reset without changing cases',async()=>{
  await page.goto(base+'/network');await ready();
  const before=await page.evaluate(async()=>await (await fetch('/api/v1/network')).json());
  const casesBefore=await page.evaluate(async()=>(await (await fetch('/api/v1/cases')).json()).map(c=>[c.id,c.version,c.status]));
  const result=page.getByTestId('network-result');
  await page.getByLabel('From asset',{exact:true}).selectOption('reservoir-main');
  await page.getByLabel('To asset',{exact:true}).selectOption('water-hill');
  await result.getByRole('heading',{name:'1,650 m configured path',exact:true}).waitFor();
  assert.equal(await page.locator('[data-edge-id][data-on-path="true"]').count(),2);
  await page.getByRole('button',{name:'Close pipe-06',exact:true}).focus();
  await page.keyboard.press('Enter');
  await result.getByRole('heading',{name:'2,250 m configured path',exact:true}).waitFor();
  assert.equal(await page.locator('[data-edge-id="pipe-03"]').getAttribute('data-on-path'),'true');
  assert.equal(await page.getByLabel('Close pipe-06 in scenario',{exact:true}).isChecked(),true);
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.getByRole('heading',{name:'Water network sandbox',exact:true}).click();
    await page.screenshot({path:path.join(artifact,`network-closures-${width}.png`),fullPage:true});
  }
  await page.getByLabel('Close pipe-03 in scenario',{exact:true}).check();
  await result.getByRole('heading',{name:'Target is unreachable',exact:true}).waitFor();
  assert.equal(await page.locator('[data-edge-id][data-on-path="true"]').count(),0);
  await page.getByLabel('Close pipe-06 in scenario',{exact:true}).uncheck();
  await result.getByRole('heading',{name:'1,650 m configured path',exact:true}).waitFor();
  await page.getByRole('button',{name:'Inspect Civic reservoir',exact:true}).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('button',{name:'Use as target',exact:true}).click();
  await result.getByRole('heading',{name:'0 m configured path',exact:true}).waitFor();
  await page.getByRole('button',{name:'Reset network scenario',exact:true}).click();
  await result.getByRole('heading',{name:'1,650 m configured path',exact:true}).waitFor();
  assert.equal(await page.getByLabel('Close pipe-03 in scenario',{exact:true}).isChecked(),false);
  await page.getByLabel('Network zone',{exact:true}).selectOption('river');
  await result.getByRole('heading',{name:'1,070 m configured path',exact:true}).waitFor();
  assert.equal(await page.locator('[data-node-id]').count(),3);
  assert.equal(await page.locator('[data-edge-id]').count(),2);
  const downloading=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export network scenario',exact:true}).click();
  const exportPath=path.join(artifact,'network-scenario.json');
  await (await downloading).saveAs(exportPath);
  const exported=JSON.parse(await fs.readFile(exportPath,'utf8'));
  assert.equal(exported.inputs.zone_id,'river');
  assert.deepEqual(exported.result.path_edges,['pipe-01','pipe-02']);
  await page.getByLabel('Network zone',{exact:true}).selectOption('hill');
  await result.getByRole('heading',{name:'0 m configured path',exact:true}).waitFor();
  await page.getByText('No connections exist inside this zone.',{exact:true}).waitFor();
  await page.reload();await ready();
  await result.getByRole('heading',{name:'1,650 m configured path',exact:true}).waitFor();
  assert.deepEqual(await page.evaluate(async()=>await (await fetch('/api/v1/network')).json()),before);
  assert.deepEqual(await page.evaluate(async()=>(await (await fetch('/api/v1/cases')).json()).map(c=>[c.id,c.version,c.status])),casesBefore);
  await page.setViewportSize({width:1440,height:1000});
});
await check('Network investigation overlays match authorized cases and open evidence',async()=>{
  await page.goto(base+'/network');await ready();
  await page.getByTestId('network-result').getByText('Connected',{exact:true}).waitFor();
  const snapshot=await page.evaluate(async()=>await (await fetch('/api/v1/bootstrap')).json());
  const graph=await page.evaluate(async()=>await (await fetch('/api/v1/network')).json());
  const openFor=node=>snapshot.cases.filter(c=>c.asset_id===node.id&&c.domain==='water'&&c.zone_id===node.zone_id&&!['closed','resolved'].includes(c.status));
  for(const node of graph.nodes) assert.equal(Number(await page.locator(`[data-node-id="${node.id}"]`).getAttribute('data-open-cases')),openFor(node).length);
  const flagged=graph.nodes.filter(n=>openFor(n).length);
  assert.ok(flagged.length>0,'Seeded network must have at least one open linked case');
  assert.equal(await page.locator('[data-case-marker]').count(),flagged.length);
  const countsBefore=await page.getByTestId('network-investigation-summary').innerText();
  const connectionBefore=await page.getByTestId('network-result').innerText();
  await page.getByLabel('Show investigation markers',{exact:true}).uncheck();
  assert.equal(await page.locator('[data-case-marker]').count(),0);
  assert.equal(await page.getByTestId('network-investigation-summary').innerText(),countsBefore);
  assert.equal(await page.getByTestId('network-result').innerText(),connectionBefore);
  await page.getByLabel('Show investigation markers',{exact:true}).check();
  const chosen=flagged[0];
  await page.getByRole('button',{name:`Inspect ${chosen.name}`,exact:true}).focus();await page.keyboard.press('Enter');
  const details=page.getByTestId('network-asset-details');
  assert.deepEqual((await details.locator('[data-network-case-id]').evaluateAll(els=>els.map(el=>el.dataset.networkCaseId))).sort(),openFor(chosen).map(c=>c.id).sort());
  await page.getByLabel('Include resolved and closed cases',{exact:true}).check();
  assert.equal(await details.locator('[data-network-case-id]').count(),snapshot.cases.filter(c=>c.asset_id===chosen.id&&c.domain==='water'&&c.zone_id===chosen.zone_id).length);
  await page.getByLabel('Include resolved and closed cases',{exact:true}).uncheck();
  const caseId=openFor(chosen)[0].id;
  await details.locator(`[data-network-case-id="${caseId}"]`).click();await page.getByRole('dialog').waitFor();
  const downloading=page.waitForEvent('download');
  await page.getByRole('dialog').getByRole('button',{name:'Export JSON',exact:true}).click();
  const passportPath=path.join(artifact,'network-case-evidence.json');await (await downloading).saveAs(passportPath);
  assert.equal(JSON.parse(await fs.readFile(passportPath,'utf8')).id,caseId);
  await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    if(width===390){
      await page.getByRole('button',{name:'Zoom in network',exact:true}).click();
      await page.getByRole('button',{name:'Zoom in network',exact:true}).click();
      assert.equal(await page.getByRole('region',{name:'Scrollable network diagram',exact:true}).evaluate(el=>el.scrollWidth>el.clientWidth),true);
      assert.equal(await page.getByTestId('network-investigation-summary').innerText(),countsBefore);
    }
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.locator('.topology-panel').screenshot({path:path.join(artifact,`network-investigations-${width}.png`)});
  }
  await page.getByRole('button',{name:'Fit network diagram',exact:true}).click();
  await page.getByLabel('Network zone',{exact:true}).selectOption('river');
  const river=graph.nodes.filter(n=>n.zone_id==='river');
  assert.equal(await page.locator('[data-case-marker]').count(),river.filter(n=>openFor(n).length).length);
  assert.match(await page.getByTestId('network-investigation-summary').innerText(),new RegExp(`^${river.reduce((sum,n)=>sum+openFor(n).length,0)} open investigations`));
  await page.getByRole('button',{name:'Inspect Civic reservoir',exact:true}).click();
  if(!openFor(graph.nodes.find(n=>n.id==='reservoir-main')).length) await details.getByText('No open linked investigations. This does not confirm normal service.',{exact:true}).waitFor();
  const after=await page.evaluate(async()=>await (await fetch('/api/v1/bootstrap')).json());
  assert.deepEqual(after.cases.map(c=>[c.id,c.version,c.status,c.severity]),snapshot.cases.map(c=>[c.id,c.version,c.status,c.severity]));
  await page.setViewportSize({width:1440,height:1000});
});
await check('Timeline zone filtering has honest empty telemetry and mobile controls',async()=>{
  await page.goto(base+'/overview');await ready();
  await page.getByRole('button',{name:'Latest water readings',exact:true}).click();
  await page.getByLabel('Filter by zone',{exact:true}).selectOption('hill');
  await page.getByRole('heading',{name:'No readings available',exact:true}).waitFor();
  assert.match(await page.getByTestId('timeline-summary').innerText(),/0 water intervals/);
  await page.getByLabel('Filter by zone',{exact:true}).selectOption('river');
  await page.getByRole('combobox',{name:'Observation window length',exact:true}).selectOption('6');
  assert.equal(new URL(page.url()).searchParams.get('hours'),'6');
  const before=Date.parse(new URL(page.url()).searchParams.get('at'));
  await page.getByRole('button',{name:'Move timeline back one hour',exact:true}).click();
  assert.equal(Date.parse(new URL(page.url()).searchParams.get('at')),before-3600000);
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.screenshot({path:path.join(artifact,`timeline-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
});
await check('Evidence passport opens and exports authorized data',async()=>{
  await page.goto(base+'/overview');await ready();
  await page.getByRole('button',{name:'Open evidence passport',exact:false}).click();
  await page.getByRole('dialog').waitFor();
  assert.match(await page.getByRole('dialog').innerText(),/Observation/i);
  const downloading = page.waitForEvent('download');
  await page.getByRole('dialog').getByRole('button',{name:'Export JSON',exact:true}).click();
  const exported = await downloading;
  const exportPath = path.join(artifact,'evidence-export.json');
  await exported.saveAs(exportPath);
  assert.ok(JSON.parse(await fs.readFile(exportPath,'utf8')).id);
  await page.screenshot({path:path.join(artifact,'evidence-passport.png'),fullPage:true});
  await page.keyboard.press('Escape');
  await page.getByRole('dialog').waitFor({state:'hidden'});
});
await check('Recorded scenario playback steps, pauses, restores and preserves case decisions',async()=>{
  await page.goto(base+'/scenarios');await ready();
  const [created]=await Promise.all([
    page.waitForResponse(response=>response.request().method()==='POST'&&response.url().endsWith('/api/v1/scenarios')),
    page.getByRole('button',{name:/^(Run scenario|Compute another run)$/}).click()
  ]);
  assert.equal(created.status(),202);
  const createdRun=await created.json();
  await page.waitForURL(url=>url.searchParams.get('run')===createdRun.id);
  await page.getByTestId('scenario-playback').waitFor({timeout:90000});
  const runId=new URL(page.url()).searchParams.get('run');assert.ok(runId);
  const run=await (await context.request.get(base+'/api/v1/jobs/'+runId)).json();
  assert.equal(run.status,'succeeded');
  const before=await Promise.all(run.result.case_ids.map(async id=>(await context.request.get(base+'/api/v1/cases/'+id)).json()));
  await page.getByTestId('playback-clock').filter({hasText:'Frame 1 of'}).waitFor();
  await page.getByRole('button',{name:'Next simulation frame',exact:true}).click();
  await page.getByTestId('playback-clock').filter({hasText:'Frame 2 of'}).waitFor();
  await page.getByRole('combobox',{name:'Playback speed',exact:true}).selectOption('4');
  await page.getByRole('button',{name:'Play playback',exact:true}).click();
  await page.waitForFunction(()=>Number(document.querySelector('input[aria-label="Recorded simulation frame"]')?.value)>1);
  await page.getByRole('button',{name:'Pause playback',exact:true}).click();
  await page.getByRole('button',{name:'Play playback',exact:true}).waitFor();
  const paused=await page.getByRole('slider',{name:'Recorded simulation frame',exact:true}).inputValue();
  assert.ok(Number(paused)>1);
  await page.waitForTimeout(500);
  assert.equal(await page.getByRole('slider',{name:'Recorded simulation frame',exact:true}).inputValue(),paused);
  await page.reload();await ready();await page.getByTestId('scenario-playback').waitFor();
  assert.equal(await page.getByRole('slider',{name:'Recorded simulation frame',exact:true}).inputValue(),paused);
  assert.equal(await page.getByRole('button',{name:'Play playback',exact:true}).count(),1);
  await page.getByRole('button',{name:'Show completed run',exact:true}).click();
  await page.getByTestId('scenario-playback').getByText('Playback complete',{exact:true}).waitFor();
  await page.getByTestId('playback-baseline').getByRole('button',{name:'Data table',exact:true}).click();
  await page.getByTestId('playback-modified').getByRole('button',{name:'Data table',exact:true}).click();
  assert.equal(await page.getByTestId('playback-baseline').locator('tbody tr').count(),run.result.baseline.series.length);
  assert.equal(await page.getByTestId('playback-modified').locator('tbody tr').count(),run.result.series.length);
  const linked=await page.getByTestId('scenario-playback').locator('.case-row').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-case-id')));
  assert.deepEqual([...linked].sort(),[...run.result.case_ids].sort());
  await page.getByRole('button',{name:'Restart playback',exact:true}).click();
  await page.getByTestId('playback-clock').filter({hasText:'Frame 1 of'}).waitFor();
  assert.equal(await page.getByTestId('scenario-playback').locator('.case-row').count(),0);
  await page.getByTestId('playback-baseline').getByRole('button',{name:'Chart view',exact:true}).click();
  await page.getByTestId('playback-modified').getByRole('button',{name:'Chart view',exact:true}).click();
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.screenshot({path:path.join(artifact,`scenario-playback-${width}.png`),fullPage:true});
  }
  const after=await Promise.all(run.result.case_ids.map(async id=>(await context.request.get(base+'/api/v1/cases/'+id)).json()));
  assert.deepEqual(after.map(c=>[c.id,c.status,c.version]),before.map(c=>[c.id,c.status,c.version]));
  assert.deepEqual((await (await context.request.get(base+'/api/v1/jobs/'+runId)).json()).result,run.result);
  await page.setViewportSize({width:1440,height:1000});
});
await check('Supporting team assignment, field access and removal work in the interface',async()=>{
  const bootstrap=await (await context.request.get(base+'/api/v1/bootstrap')).json();
  const title='Synthetic supporting team check '+Date.now();
  const response=await context.request.post(base+'/api/v1/reports',{headers:{'X-CSRF-Token':bootstrap.csrf_token},data:{domain:'water',zone_id:'river',title,description:'Synthetic browser verification observation from a safe public location.',location:'Public market entrance',idempotency_key:crypto.randomUUID()}});
  assert.equal(response.status(),201);const report=await response.json();
  async function openCase(){
    await page.goto(base+'/incidents');await ready();
    await page.getByLabel('Filter incidents').fill(title);
    await page.locator('.case-row').filter({hasText:title}).click();
    await page.getByRole('dialog').waitFor();
    await page.getByRole('button',{name:'Take action',exact:true}).click();
  }
  async function signIn(email){
    await page.goto(base+'/settings');await ready();
    await page.getByRole('button',{name:'Sign out',exact:false}).click();
    await page.goto(base+'/login');await ready();
    await page.getByLabel('Email address').fill(email);
    await page.getByLabel('Password',{exact:true}).fill('CivicDemo!2026');
    await page.locator('form').getByRole('button',{name:'Sign in',exact:true}).click();
    await page.waitForURL('**/overview');await ready();
  }
  async function saveTeam(){
    const saved=page.waitForResponse(r=>r.url().endsWith('/supporting-inspectors')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'Save supporting team',exact:true}).click();
    assert.equal((await saved).status(),200);
    await page.getByLabel('Supporting assignment reason').waitFor();
    await page.waitForFunction(()=>document.querySelector('.supporting-inspectors textarea')?.value==='');
  }
  await openCase();
  await page.getByLabel('Lead inspector',{exact:true}).selectOption('demo-inspector');
  await page.getByLabel('Reason / reviewed evidence').fill('Synthetic browser check: lead reviews this observation.');
  const assigned=page.waitForResponse(r=>r.url().endsWith('/assign')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Save assignment',exact:true}).click();assert.equal((await assigned).status(),200);
  await page.getByRole('checkbox',{name:'Supporting inspector: Kiran',exact:false}).check();
  await page.getByLabel('Supporting assignment reason').fill('Synthetic browser check: supporting field inspection.');
  await saveTeam();
  const team=await (await context.request.get(base+'/api/v1/cases/'+report.case_id)).json();
  assert.equal(team.assigned_to,'demo-inspector');assert.deepEqual(team.secondary_assignees,['demo-support']);
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    await page.locator('.supporting-inspectors').scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.screenshot({path:path.join(artifact,`supporting-inspectors-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  await signIn('support@civicsignal.local');
  const row=page.locator('tr').filter({hasText:title});await row.getByRole('button',{name:'Open '+title,exact:true}).click();
  await page.getByRole('button',{name:'Take action',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'Save supporting team',exact:true}).count(),0);
  await page.getByLabel('Findings and intervention notes').fill('Synthetic supporting inspector finding entered through the browser.');
  const finding=page.waitForResponse(r=>r.url().endsWith('/inspection')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Submit inspection',exact:false}).click();assert.equal((await finding).status(),200);
  await signIn('operator@civicsignal.local');await openCase();
  await page.getByRole('checkbox',{name:'Supporting inspector: Kiran',exact:false}).uncheck();
  await page.getByLabel('Supporting assignment reason').fill('Synthetic supporting task completed; access removed.');await saveTeam();
  const removed=await (await context.request.get(base+'/api/v1/cases/'+report.case_id)).json();
  assert.deepEqual(removed.secondary_assignees,[]);
  assert.ok(removed.audits.some(a=>a.action==='supporting_assignment'));
  await signIn('support@civicsignal.local');
  assert.equal(await page.locator('tr').filter({hasText:title}).count(),0);
  await signIn('operator@civicsignal.local');
});
await check('Baseline candidate evaluation, administrator promotion and rollback preserve decisions',async()=>{
  async function signIn(email){
    await page.goto(base+'/settings');await ready();await page.getByRole('button',{name:'Sign out',exact:false}).click();
    await page.goto(base+'/login');await ready();await page.getByLabel('Email address').fill(email);
    await page.getByLabel('Password',{exact:true}).fill('CivicDemo!2026');
    await page.locator('form').getByRole('button',{name:'Sign in',exact:true}).click();await page.waitForURL('**/overview');await ready();
  }
  await page.goto(base+'/lab');await ready();await page.getByRole('button',{name:'Baseline versions',exact:true}).click();
  await page.getByTestId('baseline-registry').waitFor();
  const previous=await (await context.request.get(base+'/api/v1/baselines/water')).json();
  const before=await (await context.request.get(base+'/api/v1/cases')).json();
  await page.getByLabel('Baseline review reason').fill('Synthetic browser check: review a shorter historical training window.');
  const queued=page.waitForResponse(r=>r.url().endsWith('/baselines/water/candidates')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'Evaluate candidate',exact:true}).click();
  const response=await queued;assert.equal(response.status(),202);const candidate=await response.json();
  await page.getByRole('table').filter({has:page.getByText('Candidate',{exact:true})}).waitFor({timeout:90000});
  assert.match(await page.getByTestId('active-baseline').innerText(),new RegExp(previous.active_id));
  assert.equal(await page.getByRole('button',{name:'Promote reviewed candidate',exact:true}).count(),0);
  await signIn('admin@civicsignal.local');
  await page.goto(base+'/lab');await ready();await page.getByRole('button',{name:'Baseline versions',exact:true}).click();
  await page.getByLabel('Baseline version',{exact:true}).selectOption(candidate.baseline_id);
  await page.getByLabel('Baseline review reason').fill('Synthetic administrator review: compare errors and promote candidate.');
  await page.getByRole('button',{name:'Promote reviewed candidate',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Candidate promoted.'}).waitFor();
  assert.match(await page.getByTestId('active-baseline').innerText(),new RegExp(candidate.baseline_id));
  assert.equal((await (await context.request.get(base+'/api/v1/analytics/water')).json()).baseline_id,candidate.baseline_id);
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.screenshot({path:path.join(artifact,`baseline-versions-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.getByLabel('Baseline version',{exact:true}).selectOption(previous.active_id);
  await page.getByLabel('Baseline review reason').fill('Synthetic administrator review: restore the previous baseline after verification.');
  await page.getByRole('button',{name:'Roll back to this version',exact:true}).click();
  await page.getByRole('status').filter({hasText:'Previous baseline restored.'}).waitFor();
  assert.match(await page.getByTestId('active-baseline').innerText(),new RegExp(previous.active_id));
  await page.reload();await ready();await page.getByRole('button',{name:'Baseline versions',exact:true}).click();
  await page.getByTestId('active-baseline').filter({hasText:previous.active_id}).waitFor();
  await signIn('operator@civicsignal.local');
  const after=await (await context.request.get(base+'/api/v1/cases')).json();
  // Priority/age can change list ordering; compare the actual persisted decisions.
  const decisions=rows=>rows.map(c=>[c.id,c.status,c.version]).sort((a,b)=>a[0].localeCompare(b[0]));
  assert.deepEqual(decisions(after),decisions(before));
  assert.equal((await (await context.request.get(base+'/api/v1/analytics/water')).json()).baseline_id,previous.active_id);
});
await check('Scenario worker pause survives reload and resumes to a saved result',async()=>{
  await page.goto(base+'/scenarios');await ready();
  await page.getByRole('checkbox',{name:'Create this run paused',exact:true}).check();
  const [response]=await Promise.all([
    page.waitForResponse(r=>r.url().endsWith('/scenarios')&&r.request().method()==='POST'),
    page.getByRole('button',{name:/^(Run scenario|Compute another run)$/}).click()
  ]);
  assert.equal(response.status(),202);const run=await response.json();
  assert.equal(run.status,'paused');assert.equal(run.attempts,0);
  await page.getByTestId('worker-status').filter({hasText:'Paused — waiting to calculate.'}).waitFor();
  await page.waitForTimeout(1500);
  const unchanged=await (await context.request.get(base+'/api/v1/jobs/'+run.id)).json();
  assert.equal(unchanged.status,'paused');assert.equal(unchanged.attempts,0);assert.equal(unchanged.result,null);
  await page.reload();await ready();
  await page.getByRole('button',{name:'Resume worker run',exact:true}).waitFor();
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:width===390?844:1000});
    await page.getByTestId('scenario-job-controls').scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    await page.screenshot({path:path.join(artifact,`worker-controls-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.getByLabel('Worker control reason').fill('Synthetic browser verification: resume the saved paused run.');
  await page.getByRole('button',{name:'Resume worker run',exact:true}).click();
  await page.getByTestId('scenario-playback').waitFor({timeout:90000});
  const done=await (await context.request.get(base+'/api/v1/jobs/'+run.id)).json();
  assert.equal(done.status,'succeeded');assert.ok(done.result.metadata);assert.ok(Array.isArray(done.result.case_ids));
  assert.equal(new URL(page.url()).searchParams.get('run'),run.id);
  assert.equal(await page.getByRole('button',{name:'Pause worker run',exact:true}).count(),0);
});
await check('Marathi report submission, receipt download and tracking persist',async()=>{
  await page.goto(base+'/settings');await ready();
  await page.getByRole('button',{name:'Sign out',exact:false}).click();
  await page.goto(base+'/login');await ready();
  await page.getByLabel('Email address').fill('citizen@civicsignal.local');
  await page.getByLabel('Password',{exact:true}).fill('CivicDemo!2026');
  await page.locator('form').getByRole('button',{name:'Sign in',exact:true}).click();
  await page.waitForURL('**/overview');
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/report');await ready();
  await page.getByRole('button',{name:'Switch reporting language to Marathi',exact:true}).click();
  await page.getByRole('button',{name:'पुढे',exact:true}).click();
  await page.getByLabel('ठिकाण किंवा जवळची खूण').fill('बाजाराच्या सार्वजनिक प्रवेशद्वाराजवळ');
  await page.getByRole('button',{name:'पुढे',exact:true}).click();
  const title='पाण्याचे निरीक्षण '+Date.now();
  await page.getByLabel('आपण काय पाहिले?').fill(title);
  await page.getByLabel('निरीक्षणाचे वर्णन करा').fill('सुरक्षित अंतरावरून सार्वजनिक नळाजवळ पाणी साचलेले दिसले. हा चाचणी अहवाल आहे.');
  await page.getByRole('button',{name:'पुढे',exact:true}).click();
  await page.getByRole('button',{name:'अहवाल पाठवा',exact:true}).click();
  await page.getByRole('heading',{name:'आपला अहवाल प्राप्त झाला.'}).waitFor();
  const downloading=page.waitForEvent('download');
  await page.getByRole('button',{name:'पावती डाउनलोड करा',exact:false}).click();
  const receiptPath=path.join(artifact,'report-receipt.json');
  await (await downloading).saveAs(receiptPath);
  const receipt=JSON.parse(await fs.readFile(receiptPath,'utf8'));
  assert.equal(receipt.language,'mr');assert.equal(receipt.status_label,'पुनरावलोकन आवश्यक');
  assert.match(receipt.receipt,/^CS360-/);
  await page.screenshot({path:path.join(artifact,'report-receipt-marathi-390.png'),fullPage:true});
  await page.getByRole('button',{name:'माझा अहवाल पहा',exact:false}).click();
  await page.getByRole('heading',{name:'आपले अहवाल आणि पुढील पाऊल'}).waitFor();
  await page.getByRole('button').filter({has:page.getByText(title,{exact:true})}).click();
  await page.getByText('सध्याची स्थिती',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  await page.screenshot({path:path.join(artifact,'report-tracking-marathi-390.png'),fullPage:true});
  await page.reload();await ready();
  await page.getByRole('heading',{name:'आपले अहवाल आणि पुढील पाऊल'}).waitFor();
  await page.getByRole('button').filter({has:page.getByText(title,{exact:true})}).waitFor();
});
await check('No external runtime dependencies requested',async()=>assert.equal(results.external_requests.length,0,JSON.stringify(results.external_requests)));
await check('No uncaught browser exceptions',async()=>assert.equal(results.console_errors.length,0,JSON.stringify(results.console_errors)));
results.finished_at=new Date().toISOString();
await fs.writeFile(path.join(artifact,'browser-results.json'),JSON.stringify(results,null,2));
await browser.close();
if(results.checks.some(check=>check.status==='failed'))process.exitCode=1;
