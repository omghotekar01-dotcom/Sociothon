import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.CIVIC_BASE_URL;
if(!base||!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Use an isolated local acceptance server.');
const browser=await chromium.launch({headless:true,executablePath:process.env.CIVIC_BROWSER_PATH});
const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'en-IN',timezoneId:'Asia/Kolkata',acceptDownloads:true});
let cleanup=null;
const results={checks:[],errors:[]};const page=await context.newPage();page.on('pageerror',e=>results.errors.push(e.message));
await context.route('**/*',route=>new URL(route.request().url()).origin===base||/^(blob|data):/.test(route.request().url())?route.continue():route.abort());
try{
  const login=await context.request.post(base+'/api/v1/auth/login',{data:{email:'admin@civicsignal.local',password:'CivicDemo!2026'}});assert.equal(login.status(),200);
  const headers={'X-CSRF-Token':(await login.json()).csrf_token};
  async function request(path,data,method='post'){const r=await context.request[method](base+'/api/v1'+path,{data,headers});assert.ok(r.ok(),await r.text());return r.json()}
  const zone='river', fixture='water-history-'+Date.now(), sourceReference='Synthetic supply notice '+fixture, ids=[fixture+'-in',fixture+'-a',fixture+'-b'];
  for(const [i,id] of ids.entries())await request('/admin/assets',{id,name:'Synthetic meter '+i,domain:'water',zone_id:zone,kind:'meter',x:20+i*10,y:20,provenance:'Synthetic',reason:'Synthetic meter comparison fixture'});
  const start=Date.parse('2031-01-06T00:00:00Z');let csv='id,asset_id,zone_id,timestamp,interval_minutes,quantity,unit,source,quality_flag\n';
  for(const id of ids.slice(1))for(const hour of [...Array(24).keys(),...Array.from({length:24},(_,i)=>168+i)])csv+=`${id}-${hour},${id},${zone},${new Date(start+hour*3600000).toISOString()},60,${hour<24?100:80},L,Synthetic,valid\n`;
  const preview=await context.request.post(base+'/api/v1/uploads/preview',{headers,multipart:{file:{name:'synthetic-water-history.csv',mimeType:'text/csv',buffer:Buffer.from(csv)}}});assert.ok(preview.ok());const upload=await preview.json();assert.equal(upload.rejected,0);await request('/uploads/'+upload.id+'/commit',{});
  const path='/water/zones/'+zone;
  const current=await (await context.request.get(base+'/api/v1'+path+'/operations')).json();
  cleanup=async()=>{
    let loaded=await (await context.request.get(base+'/api/v1'+path+'/operations')).json();
    const active=loaded.schedule_history.entries.find(e=>e.source_reference===sourceReference&&!e.revoked_at);
    if(active)await request(path+'/schedule-history/'+active.id+'/revoke',{version:loaded.schedule_history.version,reason:'Close synthetic browser fixture; retain audited history.'});
    loaded=await (await context.request.get(base+'/api/v1'+path+'/operations')).json();
    await request(path+'/operations',{...current.configuration,version:loaded.configuration.version,reason:'Restore configuration after isolated synthetic acceptance'},'put');
  };
  const config=await request(path+'/operations',{...current.configuration,timezone:'UTC',supply_windows:[{days:[0,1,2,3,4,5,6],start_minute:0,end_minute:1440,label:'Synthetic all-day supply'}],inlet_ids:[ids[0]],consumption_ids:ids.slice(1),outlet_ids:[],meter_parents:{[ids[1]]:ids[0],[ids[2]]:ids[0]},boundary_confirmed:true,reason:'Synthetic independent sibling meter boundary'},'put');
  async function open(){await page.goto(base+'/domains/water');await page.getByRole('button',{name:'Operations',exact:true}).click();await page.getByLabel('Service zone',{exact:true}).selectOption(zone);await page.locator('.water-operations').getByRole('button',{name:'Review water observations',exact:true}).waitFor()}
  await open();
  let history=page.getByRole('region',{name:'Historical supply schedules',exact:true});await history.getByRole('button',{name:/Historical supply schedules/}).click();
  await history.getByLabel('Effective from',{exact:true}).fill('2031-01-06T05:30');await history.getByLabel('Effective until (exclusive)',{exact:true}).fill('2031-01-14T05:30');
  await history.getByLabel('Schedule source reference',{exact:true}).fill(sourceReference);await history.getByLabel('Reason for this historical record',{exact:true}).fill('Synthetic known schedule over both comparison windows.');
  await history.getByRole('button',{name:'Record effective schedule',exact:true}).click();await history.getByText('Effective schedule recorded.',{exact:true}).waitFor();
  const frozen=await (await context.request.get(base+'/api/v1'+path+'/operations')).json();
  const changed=await request(path+'/operations',{...config,supply_windows:[{days:[0,1,2,3,4,5,6],start_minute:360,end_minute:420,label:'Different current supply'}],reason:'Current schedule changes must not rewrite recorded history'},'put');
  await open();await page.getByLabel('Schedule context to review',{exact:true}).selectOption('historical');
  const reviewed=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(path+'/review'));await page.getByRole('button',{name:'Review water observations',exact:true}).click();
  const snapshot=await (await reviewed).json();const fixtureRows=snapshot.schedule.filter(r=>ids.includes(r.asset_id));assert.equal(fixtureRows.length,48);assert.ok(fixtureRows.every(r=>r.status==='within_window'));assert.equal(snapshot.schedule_history_snapshot.entries.find(e=>e.source_reference===sourceReference).configuration_version,config.version);assert.equal(snapshot.configuration_version,changed.version);
  results.checks.push({name:'Effective schedule survives reload and current changes; historical review selects recorded periods',status:'passed'});
  const group=page.getByRole('region',{name:'Multi-meter impact comparison',exact:true});await group.getByRole('button',{name:'Compare multiple meters',exact:true}).click();
  for(const i of [1,2])await group.getByRole('checkbox',{name:'Synthetic meter '+i,exact:true}).check();
  await group.getByLabel('Comparison assumptions and supply context',{exact:true}).fill('Synthetic independent sibling meters, matched weekday and supply.');await group.getByRole('checkbox',{name:/I checked that selected meters/}).check();
  await group.getByRole('button',{name:'Compare selected meters',exact:true}).click();const comparison=page.getByTestId('water-group-comparison-result');await comparison.waitFor();assert.match(await comparison.innerText(),/960/);
  const download=page.waitForEvent('download');await group.getByRole('button',{name:'Export meter comparison',exact:true}).click();const exported=JSON.parse(await fs.readFile(await (await download).path(),'utf8'));assert.equal(exported.observed_reduction_l,960);assert.equal(exported.source_observations.after.length,48);assert.equal(exported.closure_eligible,false);
  results.checks.push({name:'Two independent meters compare exact complete windows and export original sources',status:'passed'});
  await group.getByLabel('Before start',{exact:true}).fill('2031-01-07T05:30');await group.getByLabel('Before end (exclusive)',{exact:true}).fill('2031-01-08T05:30');await group.getByLabel('After start',{exact:true}).fill('2031-01-14T05:30');await group.getByLabel('After end (exclusive)',{exact:true}).fill('2031-01-15T05:30');await group.getByRole('button',{name:'Compare selected meters',exact:true}).click();await comparison.getByText(/Unavailable/).first().waitFor();
  history=page.getByRole('region',{name:'Historical supply schedules',exact:true});await history.getByRole('button',{name:/Historical supply schedules/}).click();await history.getByLabel('Record to revoke',{exact:true}).selectOption(frozen.schedule_history.entries.find(e=>e.source_reference===sourceReference).id);await history.getByLabel('Correction reason',{exact:true}).fill('Synthetic correction; preserve original record.');await history.getByRole('button',{name:'Revoke selected record',exact:true}).click();await history.getByText('Record revoked; its audit history is retained.',{exact:true}).waitFor();
  const missing=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith(path+'/review'));await page.getByRole('button',{name:'Review water observations',exact:true}).click();assert.ok((await (await missing).json()).schedule.filter(r=>ids.includes(r.asset_id)).every(r=>r.status==='history_missing'));
  results.checks.push({name:'Missing meter windows stay unavailable; revoked schedule stays in history and creates an explicit gap',status:'passed'});
  for(const width of [1440,768,390]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await page.screenshot({path:`artifacts/verification/water-history-${width}.png`,fullPage:true})}
  await page.getByRole('button',{name:'Switch interface language to Marathi',exact:true}).click();await page.getByRole('region',{name:'ऐतिहासिक पुरवठा वेळापत्रके',exact:true}).waitFor();await page.getByRole('region',{name:'अनेक मीटरची परिणाम तुलना',exact:true}).waitFor();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
  results.checks.push({name:'History and comparison controls support Marathi and 390/768/1440 layouts',status:'passed'});
}catch(e){results.errors.push(e.stack||e.message);await page.screenshot({path:'artifacts/verification/water-history-failure.png',fullPage:true}).catch(()=>{})}
finally{if(cleanup)await cleanup().catch(e=>results.errors.push('Fixture cleanup: '+e.message));await fs.mkdir('artifacts/verification',{recursive:true});await fs.writeFile('artifacts/verification/water-history.json',JSON.stringify(results,null,2));await browser.close()}
console.log(JSON.stringify(results,null,2));if(results.errors.length)process.exitCode=1;
