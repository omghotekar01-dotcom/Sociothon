import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const {chromium}=createRequire(import.meta.url)(process.env.CIVIC_PLAYWRIGHT_PATH||'playwright');
const base=process.env.CIVIC_BASE_URL||'http://127.0.0.1:8000';
const profile=path.resolve(process.env.CIVIC_OFFLINE_PROFILE||'.runtime/offline-startup-profile');
const mode=process.argv[2]||'prepare';
const artifact=path.resolve('artifacts/verification');
await fs.mkdir(artifact,{recursive:true});

if(mode==='prepare'){
  const context=await chromium.launchPersistentContext(profile,{headless:true,viewport:{width:390,height:844},reducedMotion:'reduce',...(process.env.CIVIC_BROWSER_PATH?{executablePath:process.env.CIVIC_BROWSER_PATH}:{})});
  try{
    const auth=await context.request.post(base+'/api/v1/auth/login',{data:{email:'citizen@civicsignal.local',password:'CivicDemo!2026'}});
    assert.equal(auth.status(),200,await auth.text());
    const page=await context.newPage();
    page.on('pageerror',error=>console.error('Browser error:',error.message));
    await page.goto(base+'/report');
    await page.getByRole('heading',{name:/Let’s get it to the right people/}).waitFor();
    await page.evaluate(async()=>{
      const registration=await navigator.serviceWorker.ready;
      if(!registration.active)throw new Error('Offline service worker is not active');
      const cache=await caches.open('civicsignal-shell-v1');
      const keys=await cache.keys();
      if(keys.filter(request=>new URL(request.url).pathname.startsWith('/assets/')).length<2)throw new Error('App JavaScript and style assets were not precached');
    });
    const ready=page.getByRole('checkbox',{name:'Keep citizen reporting ready on this device for offline use'});
    await page.waitForFunction(()=>{const input=[...document.querySelectorAll('input[type=checkbox]')].find(node=>node.parentElement?.innerText.includes('Keep citizen reporting ready'));return input&&!input.disabled;});
    await ready.check();
    await page.getByRole('button',{name:'Continue',exact:true}).click();
    await page.getByLabel('Location or nearby landmark').fill('Synthetic library entrance');
    await page.getByRole('button',{name:'Continue',exact:true}).click();
    const title='Synthetic offline startup '+Date.now();
    await page.getByLabel('What did you notice?').fill(title);
    await page.getByLabel('Describe your observation').fill('A synthetic draft used to confirm the local offline citizen entry.');
    await page.getByRole('button',{name:'Continue',exact:true}).click();
    await page.getByRole('button',{name:'Save unsent draft'}).click();
    const persisted=await page.evaluate(()=>({permit:JSON.parse(localStorage.getItem('civic-offline-citizen-v1')||'null'),draft:JSON.parse(localStorage.getItem('civic-draft-demo-citizen')||'null')}));
    assert.equal(persisted.permit?.userId,'demo-citizen');
    assert.equal(persisted.draft?.form?.title,title);
    assert.equal(persisted.draft?.form?.location,'');
    await page.screenshot({path:path.join(artifact,'offline-startup-online-390.png'),fullPage:true});
    console.log('Prepared consented offline cache and redacted synthetic draft.');
  }finally{await context.close();}
}else if(mode==='offline'){
  const context=await chromium.launchPersistentContext(profile,{headless:true,viewport:{width:390,height:844},reducedMotion:'reduce',...(process.env.CIVIC_BROWSER_PATH?{executablePath:process.env.CIVIC_BROWSER_PATH}:{})});
  const result={checks:[],page_errors:[],started_at:new Date().toISOString()};
  try{
    const page=await context.newPage();
    page.on('pageerror',error=>result.page_errors.push(error.message));
    page.on('requestfailed',request=>{if(request.url().includes('/api/v1/'))result.failed_api_requests=(result.failed_api_requests||0)+1;});
    await page.goto(base+'/network',{waitUntil:'domcontentloaded',timeout:45000});
    await page.getByRole('heading',{name:'The server is not reachable'}).waitFor({timeout:45000});
    result.checks.push({name:'Fresh direct route opens the cached shell after the local server stops',status:'passed'});
    await page.getByRole('heading',{name:'Let’s get it to the right people.'}).waitFor();
    await page.getByRole('button',{name:'Restore',exact:true}).click();
    await page.getByLabel('Location or nearby landmark').fill('Synthetic offline landmark');
    await page.getByRole('button',{name:'Continue',exact:true}).click();
    assert.equal(await page.getByLabel('What did you notice?').inputValue(),await page.evaluate(()=>JSON.parse(localStorage.getItem('civic-draft-demo-citizen')).form.title));
    await page.getByRole('button',{name:'Continue',exact:true}).click();
    const submit=page.getByRole('button',{name:'Submit report',exact:true});
    assert.equal(await submit.isDisabled(),true);
    assert.match(await page.getByRole('status').first().innerText(),/Offline\. You can edit and save a draft/);
    await page.screenshot({path:path.join(artifact,'offline-startup-restored-390.png'),fullPage:true});
    result.checks.push({name:'Saved draft restores for editing while report submission stays disabled',status:'passed'});
    const out=await page.evaluate(()=>({hasPermit:!!localStorage.getItem('civic-offline-citizen-v1'),draft:JSON.parse(localStorage.getItem('civic-draft-demo-citizen')||'null'),reportPage:!!document.querySelector('[data-testid=pending-report]')}));
    assert.equal(out.hasPermit,true);assert.equal(out.draft.form.location,'');assert.ok(out.draft.form.title.startsWith('Synthetic offline startup '));assert.equal(out.reportPage,false);
    assert.equal(result.page_errors.length,0);
    result.finished_at=new Date().toISOString();
    await fs.writeFile(path.join(artifact,'offline-startup-results.json'),JSON.stringify(result,null,2));
    console.log('Verified offline launch and local draft restoration.');
  }finally{await context.close();}
}else throw new Error('Use prepare or offline.');
