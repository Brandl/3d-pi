import {test,expect} from '@playwright/test';

test('project uploads, notes, downloads and mobile form',async({page,request})=>{
 test.skip(process.env.CAD_UPLOAD_TESTS!=='1','Isolated native CAD service only');
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:{messages:[],busy:false,activeTools:[],job:{status:'complete'}}}));
 await page.addInitScript(()=>Object.defineProperty(window,'WebSocket',{value:class{constructor(){throw Error('Polling test');}}}));
 const project=(await (await request.post('/api/projects',{data:{name:'Upload test'}})).json()).id;
 const base=`/projects/${project}`;
 const before=await (await request.get(`${base}/api/state`)).json();
 await page.goto(`/?project=${project}`);
 await page.locator('#open-files').click();
 await expect(page.locator('#upload-list')).toContainText('No project uploads');
 await page.locator('#upload-file').setInputFiles({name:'reference.html',mimeType:'text/html',buffer:Buffer.from('<script>window.pwned=true</script>')});
 await page.locator('#upload-note').fill('Reference <img src=x onerror="alert(1)">');
 await page.getByRole('button',{name:'Upload file',exact:true}).click();
 const card=page.locator('.upload-card');await expect(card).toHaveCount(1);
 await expect(card.locator('.upload-note')).toHaveText('Reference <img src=x onerror="alert(1)">');
 await expect(card.locator('img')).toHaveCount(0);
 const href=(await card.locator('a').getAttribute('href'))!;
 const download=await request.get(href);expect(await download.text()).toContain('window.pwned');expect(download.headers()['content-disposition']).toContain('attachment;');
 expect(await page.evaluate(()=>Object.hasOwn(window,'pwned'))).toBe(false);
 await card.locator('summary').click();await card.locator('textarea').fill('Updated note ✓');await card.getByRole('button',{name:'Save note'}).click();
 await expect(card.locator('.upload-note')).toHaveText('Updated note ✓');
 await page.reload();await page.locator('#open-files').click();await expect(card.locator('.upload-note')).toHaveText('Updated note ✓');
 for(const width of [320,390,768,1440]){
  await page.setViewportSize({width,height:844});await expect(page.locator('#upload-file')).toBeVisible();
  expect(await page.locator('#project-uploads').evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);
 }
 await page.setViewportSize({width:390,height:844});
 const row=(await (await request.get(`${base}/api/uploads`)).json()).uploads[0];
 await card.locator('summary').click();await card.locator('textarea').fill('My unsaved draft');
 await request.patch(`${base}/api/uploads/${row.id}`,{data:{note:'Another session',version:row.version}});
 await card.getByRole('button',{name:'Save note'}).click();await expect(card).toContainText('Note changed elsewhere');await expect(card.locator('textarea')).toHaveValue('My unsaved draft');
 expect((await (await request.get('/projects/dripper/api/uploads')).json()).uploads).toEqual([]);
 expect(await (await request.get(`${base}/api/state`)).json()).toEqual(before);
 page.once('dialog',d=>d.accept());await card.getByRole('button',{name:'Delete upload'}).click();await expect(card).toHaveCount(0);
 expect((await request.get(href)).status()).toBe(404);
});
