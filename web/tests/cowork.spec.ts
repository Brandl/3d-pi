import {test,expect} from '@playwright/test';

// Against isolated native CAD data seeded by scripts/test-pi.mjs, never production.
for(const fallback of [false,true]) test(`working design, timeline, files and selection (${fallback?'image':'WebGL'})`,async({page,request})=>{
 test.skip(process.env.CAD_COWORK_TESTS!=='1','Requires isolated seeded workspace');
 if(fallback)await page.addInitScript(()=>{const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type:string,...args:unknown[]){if(type.includes('webgl'))return null;return Reflect.apply(original,this,[type,...args]);} as typeof original;});
 const state=await (await request.get('/projects/dripper/api/state')).json();
 const workspace=state.workspace;
 expect(workspace.commits.length).toBeGreaterThan(0);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test-csrf'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:{messages:[],partial:null,busy:false,activeTools:[],job:{status:'complete'},model:'test',error:''}}));
 let prompt='';
 await page.route('**/api/agent/prompt',r=>{prompt=r.request().postDataJSON().text;return r.fulfill({status:202,json:{status:'accepted'}});});
 await page.goto('/?project=dripper');
 const viewport=page.locator('#viewport');
 await expect(viewport).toHaveAttribute('data-revision',workspace.revision);
 await expect(page.locator('#history')).toContainText(workspace.commits[0].icon);
 await expect(page.locator('#history')).toContainText(workspace.commits[0].name);
 await expect(page.locator('#timeline-status')).toHaveText('Working design');
 if(fallback)await expect(page.locator('#section-view')).toBeDisabled();else{await page.locator('#section-view').click();await expect(page.locator('#section-view')).toHaveAttribute('aria-pressed','true');await expect(viewport).toHaveAttribute('data-revision',workspace.revision);}
 await page.locator('[data-component="part:enclosure"]').click();
 await expect(viewport).toHaveAttribute('data-component','part:enclosure');
 await expect(page.locator('#chat-context')).toContainText('enclosure');
 await page.locator('#chat-input').fill('Explain this part without changes');await page.locator('#chat-send').click();
 await expect.poll(()=>prompt).toContain('selected node part:enclosure');
 expect(prompt).toContain(`working revision ${workspace.revision}`);
 await page.locator('#open-files').click();
 await expect(page.locator('#related-files')).toContainText('Test variant');
 const download=page.locator('.asset-card .exports a').filter({hasText:/^STL$/}).first();
 await expect(download).toBeVisible();
 const response=await request.get((await download.getAttribute('href'))!);
 expect(response.status()).toBe(200);expect(response.headers()['content-disposition']).toContain('Test-variant');
 const range=await request.get((await download.getAttribute('href'))!,{headers:{Range:'bytes=0-9'}});expect(range.status()).toBe(206);expect((await range.body()).length).toBe(10);
 await page.locator('.asset-card button').click();await page.keyboard.press('Escape');
 await expect(viewport).toHaveAttribute('data-revision',workspace.assets[0].revision);
 await expect(viewport).toHaveAttribute('data-working-revision',workspace.revision);
 await expect(page.locator('#timeline-status')).toContainText('working design unchanged');
 await page.locator('#timeline-working').click();await expect(viewport).toHaveAttribute('data-revision',workspace.revision);
 await page.reload();await expect(viewport).toHaveAttribute('data-revision',workspace.revision);
 for(const width of [1440,768,390]){
  await page.setViewportSize({width,height:960});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const model=await viewport.boundingBox(),timeline=await page.locator('#design-timeline').boundingBox();
  expect(timeline!.y).toBeGreaterThanOrEqual(model!.y+model!.height-1);
 }
 expect((await (await request.get('/projects/dripper/api/state')).json()).workspace).toEqual(workspace);
 expect(errors).toEqual([]);
});

test('a newer build does not become a working model in an empty workspace',async({page})=>{
 test.skip(process.env.CAD_COWORK_TESTS!=='1','Isolated only');
 await page.route('**/api/state',r=>r.fulfill({json:{revision:null,generation:0,publications:[],history:[],candidates:['a'.repeat(32)],workspace:{revision:null,commit_id:null,generation:0,commits:[],assets:[]}}}));
 await page.addInitScript(()=>Object.defineProperty(window,'WebSocket',{value:class{constructor(){throw Error('Polling test');}}}));
 await page.goto('/?project=dripper');
 await expect(page.locator('#empty')).toBeVisible();
 await expect(page.locator('#viewport')).not.toHaveAttribute('data-revision');
 await expect(page.locator('#timeline-status')).toContainText('No working design');
});
