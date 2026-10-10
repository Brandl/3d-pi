import {test,expect} from '@playwright/test';
const idle={sessionId:'test',model:'test',busy:false,sequence:1,activeTools:[],partial:null,error:'',messages:[]};
test('uncertain delivery survives reload; explicit retry keeps exact payload and preserves newer draft',async({page})=>{
 const requests:any[]=[];
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:idle}));
 await page.route('**/api/agent/prompt',r=>{
  requests.push(r.request().postDataJSON());
  return requests.length===1?r.abort('failed'):r.fulfill({status:200,json:{job:{id:requests[0].request_key,status:'complete'}}});
 });
 await page.goto('/');const input=page.locator('#chat-input');await expect(input).toBeVisible();
 await input.fill('Original request');await input.press('Enter');
 await expect(page.getByRole('button',{name:'Check / retry'})).toBeVisible();
 await expect(input).toHaveValue('Original request');
 await input.fill('My next draft');await page.reload();await expect(input).toHaveValue('My next draft');
 await expect(page.locator('#chat-send')).toBeDisabled();expect(requests).toHaveLength(1);
 await page.evaluate(()=>document.getElementById('viewport')!.dataset.revision='a-different-view');
 await page.getByRole('button',{name:'Check / retry'}).click();
 await expect(page.locator('#chat-delivery')).toBeHidden();
 expect(requests).toHaveLength(2);expect(requests[1]).toEqual(requests[0]);
 await expect(input).toHaveValue('My next draft');
});
test('poll receipt reconciles a lost response without replaying it',async({page})=>{
 let job:any=null;let calls=0;
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:{...idle,job}}));
 await page.route('**/api/agent/prompt',r=>{calls++;job={id:r.request().postDataJSON().request_key,status:'complete'};return r.abort('failed');});
 await page.goto('/');const input=page.locator('#chat-input');await expect(input).toBeVisible();
 await input.fill('Only once');await input.press('Enter');
 await expect(page.locator('#chat-delivery')).toBeHidden({timeout:10000});
 await expect(input).toHaveValue('');expect(calls).toBe(1);
});
test('draft survives reload and a rejected request is not lost',async({page})=>{
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:idle}));
 await page.route('**/api/agent/prompt',r=>r.fulfill({status:422,json:{detail:'Prompt too long'}}));
 await page.goto('/');const input=page.locator('#chat-input');await expect(input).toBeVisible();
 await input.fill('Save my draft');await page.reload();await expect(input).toHaveValue('Save my draft');
 await input.press('Enter');await expect(page.locator('#chat-status')).toHaveText('Prompt too long');
 await expect(input).toHaveValue('Save my draft');await expect(page.locator('#chat-send')).toBeEnabled();
});
