import {test,expect} from '@playwright/test';
test('Enter sends once, Shift+Enter and IME do not, busy preserves draft',async({page})=>{
 let busy=false;const sent:string[]=[];
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:{sessionId:'test',model:'test',busy,sequence:1,activeTools:[],partial:null,error:'',messages:[]}}));
 await page.route('**/api/agent/prompt',r=>{sent.push(r.request().postDataJSON().text);busy=true;return r.fulfill({status:202,json:{job:{status:'running'}}});});
 await page.goto('/');const input=page.locator('#chat-input');await expect(input).toBeVisible();
 await input.fill('First line');await input.press('Shift+Enter');await input.press('a');
 await expect(input).toHaveValue('First line\na');expect(sent).toHaveLength(0);
 await input.dispatchEvent('keydown',{key:'Enter',isComposing:true});expect(sent).toHaveLength(0);
 await input.press('Enter');await expect.poll(()=>sent.length).toBe(1);
 expect(sent[0]).toContain('First line\na');await expect(input).toHaveValue('');
 await input.fill('Keep my next draft');await input.press('Enter');
 expect(sent).toHaveLength(1);await expect(input).toHaveValue('Keep my next draft');
});
