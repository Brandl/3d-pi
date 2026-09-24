import {test,expect} from '@playwright/test';

test('selected thumbnail is revealed without snapping manual scrolling on every poll',async({page,request})=>{
 const state=await (await request.get('/api/state')).json();
 const revision=state.workspace?.revision??state.revision;
 test.skip(!revision,'Requires a model fixture');
 const commits=Array.from({length:24},(_,i)=>({id:(i+1).toString(16).padStart(32,'0'),generation:i+1,revision,name:`Change ${i+1}`,icon:'✦',created:1,source_commit:'a'.repeat(40),source_file:'document.json'}));
 await page.route('**/api/state',r=>r.fulfill({json:{...state,workspace:{revision,generation:24,commit_id:commits.at(-1)!.id,commits,assets:[]}}}));
 await page.goto('/');
 const strip=page.locator('#history');
 await expect.poll(()=>strip.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
 const active=await page.locator('#history .current').boundingBox(),bounds=await strip.boundingBox();
 expect(active!.x).toBeGreaterThanOrEqual(bounds!.x-1);expect(active!.x+active!.width).toBeLessThanOrEqual(bounds!.x+bounds!.width+1);
 await strip.evaluate(el=>{el.scrollLeft=0;});
 await page.waitForTimeout(4500);
 expect(await strip.evaluate(el=>el.scrollLeft)).toBe(0);
});

for(const width of [1024,1440]) test(`studio conversation left, thumbnail history and compact exchanges at ${width}px`,async({page,request})=>{
 await page.setViewportSize({width,height:960});
 let extra=false;
 const messages=[
  {role:'user',text:'Make a small enclosure with a removable lid.'},
  {role:'assistant',text:'I will inspect the dimensions first.',tools:['cad_measure']},
  {role:'toolResult',tool:'cad_measure',text:'Original dimensions: 80 × 50 × 24 mm'},
  {role:'assistant',text:'The enclosure is ready for review. Geometry checks passed; physical fit is still untested.'},
  {role:'user',text:'Show me the inside before we print it.'},
  {role:'assistant',text:'We can inspect a full section before choosing print settings. Nothing has been published.'},
 ];
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:{sessionId:'studio-test',model:'test',busy:false,sequence:extra?2:1,activeTools:[],partial:null,error:'',messages:extra?[...messages,{role:'assistant',text:'A new detail from inspection.'}]:messages}}));
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const before=await (await request.get('/api/state')).json();
 await page.goto('/');
 await expect(page.locator('#chat-input')).toBeVisible();
 const chat=await page.locator('#chat-panel').boundingBox(),model=await page.locator('#viewport').boundingBox();
 expect(chat!.x+chat!.width).toBeLessThanOrEqual(model!.x+1);
 expect(model!.width).toBeGreaterThan(width-370);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(page.locator('#model-parts')).toBeHidden();
 const card=page.locator('.chat-turn');await expect(card).toHaveCount(1);
 await expect(card).not.toHaveAttribute('open','');
 await expect(card.locator('summary').first()).toContainText('Make a small enclosure');
 await expect(card.locator('.chat-turn-body')).toBeHidden();
 await card.locator('summary').first().click();
 await expect(card.locator('.chat-turn-body')).toContainText('Original dimensions');
 extra=true;
 await expect(page.locator('#chat-messages')).toContainText('A new detail from inspection.');
 await expect(card).toHaveAttribute('open','');
 await card.locator('summary').first().click();
 await page.locator('#chat-input').fill('Keep this unsent direction');
 await page.getByRole('navigation',{name:'Design workspace',exact:true}).getByRole('button',{name:'Parts',exact:true}).click();
 await expect(page.locator('#model-parts')).toBeVisible();
 await page.getByRole('navigation',{name:'Design workspace',exact:true}).getByRole('button',{name:'Model',exact:true}).click();
 await expect(page.locator('#chat-input')).toHaveValue('Keep this unsent direction');
 if(before.publications?.length||before.workspace?.commits?.length){
  const thumb=page.locator('#history .revision-thumb').first();
  await expect(thumb).toBeVisible();
  await expect(thumb).toHaveAttribute('data-rendered','true');
  await expect.poll(()=>thumb.evaluate((el:HTMLImageElement)=>el.naturalWidth)).toBe(320);
  await page.locator('#history button').first().click();
  await expect(page.locator('#timeline-status')).toContainText('browsing only');
  const after=await (await request.get('/api/state')).json();
  expect(after.workspace).toEqual(before.workspace);expect(after.generation).toEqual(before.generation);
  await page.locator('#timeline-working').click();
 }
 await page.screenshot({path:`test-results/studio-${width}.png`});
 await page.getByRole('navigation',{name:'Design workspace',exact:true}).getByRole('button',{name:'Make',exact:true}).click();
 await expect(page.locator('#make-panel')).toBeVisible();
 await expect(page.locator('#chat-input')).toBeVisible();
 await expect(page.locator('#viewport')).toBeHidden();
 await page.screenshot({path:`test-results/studio-make-${width}.png`});
 await page.locator('#open-files').click();await expect(page.locator('#files-drawer')).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.locator('#make-panel #related-files')).toBeVisible();
 expect(errors).toEqual([]);
});
