import {createRequire} from 'node:module';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.CIVIC_PLAYWRIGHT_PATH || 'playwright');
const base = process.env.CIVIC_BASE_URL || 'http://127.0.0.1:8000';
const options = {headless:true};
if (process.env.CIVIC_BROWSER_PATH) options.executablePath = process.env.CIVIC_BROWSER_PATH;

const browser = await chromium.launch(options);
const context = await browser.newContext({locale:'en-IN',timezoneId:'Asia/Kolkata'});
await context.route('**/*', route => {
  const url = new URL(route.request().url());
  return ['127.0.0.1','localhost'].includes(url.hostname) || ['data:','blob:'].includes(url.protocol)
    ? route.continue()
    : route.abort('blockedbyclient');
});
const page = await context.newPage();
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));

try {
  await page.goto(base);
  await page.getByRole('button',{name:'Enter the observatory',exact:false}).click();
  await page.waitForURL('**/overview');
  await page.getByRole('button',{name:'Open evidence passport',exact:false}).click();
  const drawer = page.getByRole('dialog');
  await drawer.waitFor();
  await drawer.getByRole('heading',{name:'Priority breakdown',exact:true}).waitFor();
  assert.equal(await drawer.getByRole('columnheader',{name:'Factor',exact:true}).count(),1);
  assert.equal(await drawer.locator('.evidence-section').filter({has:drawer.getByRole('heading',{name:'Priority breakdown',exact:true})}).locator('tbody tr').count(),6);
  await drawer.getByRole('button',{name:'Evidence assistant',exact:true}).click();
  const assistant = drawer.getByRole('region',{name:'Evidence assistant'});
  await assistant.waitFor();
  await assistant.getByText('Deterministic',{exact:true}).waitFor();
  await assistant.getByText('Source IDs',{exact:true}).waitFor();
  assert.ok(await assistant.locator('.assistant-sources code').count() >= 1,'case source id is present');
  await assistant.getByRole('button',{name:'Which records support it?',exact:true}).click();
  await assistant.getByText(/distinct account\(s\).*not proof of a fault/i).waitFor();
  await assistant.getByRole('button',{name:'What remains uncertain?',exact:true}).click();
  await assistant.getByText(/Recorded limitation:/i).waitFor();
  await assistant.getByText(/Alternative to check:/i).waitFor();
  await assistant.getByRole('button',{name:'What should a reviewer check next?',exact:true}).click();
  await assistant.getByText(/authorized human review|authorized inspection or follow-up/i).waitFor();
  assert.deepEqual(pageErrors,[],'no uncaught browser errors');
  console.log('PASS Evidence assistant is case-linked, source-labelled, uncertainty-aware and read-only');
} finally {
  await context.close();
  await browser.close();
}
