import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

test('login protects artifacts and chat; logout revokes access',async({browser,baseURL})=>{
  test.skip(!process.env.CAD_TEST_PASSWORD_FILE,'Requires a password-protected gateway');
  const context=await browser.newContext({baseURL,storageState:{cookies:[],origins:[]}});
  const page=await context.newPage();
  try {
    expect((await context.request.get('/api/state')).status()).toBe(401);
    expect((await context.request.get('/api/agent/state')).status()).toBe(401);
    const download=await context.request.get('/downloads/latest.zip',{maxRedirects:0});
    expect(download.status()).toBe(303);
    await page.goto('/');await expect(page.getByLabel('Password',{exact:true})).toBeVisible();
    await page.getByLabel('Password',{exact:true}).fill(readFileSync(process.env.CAD_TEST_PASSWORD_FILE!,'utf8').trim());
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await expect(page.locator('#chat-panel')).toBeVisible();
    await expect(page.locator('#chat-status')).toHaveText('Ready');
    await expect(page.locator('#chat-model')).not.toHaveText('');
    await expect(page.locator('#viewport')).toHaveAttribute('data-revision',/[a-f0-9]{32}/);
    // Do not invoke the real provider or change geometry in routine browser tests.
    await page.route('**/api/agent/prompt',async route=>{
      const body=route.request().postDataJSON();expect(body.text).toContain('Browser test');
      expect(route.request().headers()['x-cad-csrf']).toBeTruthy();
      await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({job:{id:body.request_key,status:'running'}})});
    });
    await page.locator('#chat-input').fill('Browser test — no real model changes');
    await page.locator('#chat-send').click();await expect(page.locator('#chat-input')).toHaveValue('');
    const denied=await page.evaluate(async()=> (await fetch('/api/agent/abort',{method:'POST'})).status);
    expect(denied).toBe(403);
    await page.reload();await expect(page.locator('#chat-panel')).toBeVisible();
    await page.locator('#logout').click();await expect(page.getByLabel('Password',{exact:true})).toBeVisible();
    expect((await context.request.get('/api/agent/state')).status()).toBe(401);
  } finally {await context.close();}
});
