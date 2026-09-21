import {test,expect} from '@playwright/test';

test.skip(process.env.CAD_PROJECT_TESTS!=='1','Creates a project: run only against isolated project staging');

test('project navigation, candidate preview, creation and transcript download',async({page})=>{
  await page.goto('/');
  const catalog=await page.evaluate(async()=>{const response=await fetch('/api/projects');return {status:response.status,data:await response.json()};});
  expect(catalog.status).toBe(200);
  const projects=catalog.data.projects;
  const existing=projects.find((p:{name:string})=>p.name==='Scoped integration');expect(existing).toBeTruthy();
  await page.goto('/?project='+existing.id);
  await expect(page.locator('#viewport')).toHaveAttribute('data-revision',/[a-f0-9]{32}/);
  const original=await page.locator('#viewport').getAttribute('data-revision');
  await expect(page.locator('#project-select')).toHaveValue(existing.id);
  const candidates=await page.locator('#draft-select option').evaluateAll(options=>options.map(o=>(o as HTMLOptionElement).value).filter(Boolean));
  expect(candidates.length).toBeGreaterThan(0);
  await page.locator('#open-files').click();
  await page.getByText('Other build outputs',{exact:true}).click();
  await page.locator('#draft-select').selectOption(candidates[0]);
  await page.keyboard.press('Escape');
  await expect(page.locator('#viewport')).toHaveAttribute('data-revision',candidates[0]);
  await expect(page.locator('#timeline-status')).toContainText('Build preview');
  const state=await page.evaluate(async id=>(await fetch(`/projects/${id}/api/state`)).json(),existing.id);
  expect(state.revision).toBe(original);
  await expect(page.locator('#chat-status')).toHaveText('Ready');
  page.once('dialog',dialog=>dialog.accept('Isolated browser project'));
  await page.locator('#project-new').click();
  await expect(page).not.toHaveURL(new RegExp(existing.id));
  await expect(page.locator('#project-select option:checked')).toHaveText('Isolated browser project');
  await expect(page.locator('#empty')).toBeVisible();
  await expect(page.locator('#chat-status')).toHaveText('Ready');
  await expect(page.locator('#chat-messages .chat-message')).toHaveCount(0);
  await page.locator('#open-files').click();
  const download=page.waitForEvent('download');await page.locator('#project-transcript').click();
  expect((await download).suggestedFilename()).toBe('pi-transcript.md');
  await page.keyboard.press('Escape');
  await page.locator('#project-select').selectOption(existing.id);
  await expect(page.locator('#viewport')).toHaveAttribute('data-revision',original!);
});

test('project endpoints remain authenticated',async({browser,baseURL})=>{
 const context=await browser.newContext();
 try{
  for(const path of ['/api/projects','/projects/dripper/api/state','/projects/dripper/api/agent/transcript']){
   const response=await context.request.get(baseURL+path);expect(response.status()).toBe(401);
  }
  const path=`/projects/dripper/downloads/${'a'.repeat(32)}/model.stl`;
  const redirect=await context.request.get(baseURL+path,{maxRedirects:0});
  expect(redirect.status()).toBe(303);
  expect(redirect.headers().location).toContain(encodeURIComponent(path));
 }finally{await context.close();}
});
