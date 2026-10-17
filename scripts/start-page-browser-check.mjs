import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=createRequire(import.meta.url)('playwright');
const base=process.env.CIVIC_BASE_URL;
if(!base||!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(base))throw new Error('Set CIVIC_BASE_URL to an isolated local acceptance server.');
const browser=await chromium.launch({headless:true,executablePath:process.env.CIVIC_BROWSER_PATH});
const result={checks:[],errors:[]};
async function check(name,run){
 try{await run();result.checks.push({name,status:'passed'});console.log('PASS',name)}
 catch(error){result.checks.push({name,status:'failed',error:String(error)});console.error('FAIL',name,error);result.errors.push(String(error))}
}
const context=await browser.newContext({locale:'en-IN',viewport:{width:1440,height:950},reducedMotion:'reduce'});
const page=await context.newPage();page.on('pageerror',e=>result.errors.push(e.message));
try{
 await check('Public welcome has chat guide and four visible functional shortcuts',async()=>{
  await page.goto(base+'/');await page.getByRole('heading',{name:/Notice an issue/i}).waitFor();
  for(const title of ['Add a case','My reports','Dashboard','Live demo'])assert.equal(await page.locator('.welcome-action-grid').getByRole('button',{name:new RegExp(title,'i')}).count(),1);
  await page.getByRole('button',{name:'Report a water leak',exact:true}).click();
  assert.match(await page.locator('.welcome-message-guide').last().innerText(),/Start a new report/);
  assert.equal(await page.locator('.welcome-result-link').count(),1);
 });
 await check('Welcome is readable and unclipped on 390/768/1440 viewports',async()=>{
  for(const width of [390,768,1440]){
   await page.setViewportSize({width,height:950});
   const metrics=await page.evaluate(()=>{
    const elements=[...document.querySelectorAll('.welcome-layout,.welcome-intro,.welcome-guide,.welcome-action-grid,.welcome-services')];
    return {scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth,offenders:elements.filter(e=>{const r=e.getBoundingClientRect();return r.right>innerWidth+2||r.left<-2}).map(e=>e.className)};
   });
   assert.ok(metrics.scrollWidth<=metrics.viewport+2,JSON.stringify(metrics));
   assert.deepEqual(metrics.offenders,[],JSON.stringify(metrics));
   await page.screenshot({path:`artifacts/verification/welcome-${width}.png`,fullPage:true});
  }
 });
 await check('Public Add a case requires sign-in then opens actual case report form',async()=>{
  await page.goto(base+'/');
  await page.getByRole('button',{name:/Add a case/i}).click();
  assert.match(new URL(page.url()).search,/next=report/);
  await page.getByRole('button',{name:'Citizen',exact:true}).click();
  await page.locator('.report-layout').waitFor();
  assert.ok(new URL(page.url()).pathname==='/report');
 });
 await check('Signed-in start page and guide route to preselected road report',async()=>{
  await page.goto(base+'/start');
  await page.getByRole('heading',{name:/Notice an issue/i}).waitFor();
  await page.getByRole('textbox',{name:'What would you like to do?'}).fill('File a pothole complaint');
  await page.getByRole('button',{name:'Find the right page'}).click();
  await page.getByRole('button',{name:/Open this page/}).click();
  await page.locator('.report-layout').waitFor();
  assert.equal(new URL(page.url()).searchParams.get('domain'),'roads');
  assert.equal(await page.locator('.report-categories button.selected').innerText().then(x=>x.includes('Roads')),true);
 });
} finally {await fs.writeFile('artifacts/verification/start-page-browser.json',JSON.stringify(result,null,2));await context.close();await browser.close()}
if(result.errors.length)process.exitCode=1;
