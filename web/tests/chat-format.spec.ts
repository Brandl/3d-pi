import {test,expect} from '@playwright/test';
test('safe inline conversation, visible activity and self-hosted emoji fallback',async({page})=>{
 await page.route('**/auth/session',route=>route.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',route=>route.fulfill({json:{sessionId:'test',model:'test',busy:false,sequence:1,activeTools:[],partial:null,error:'',messages:[
  {role:'user',text:'Check the model.\n\n[Workspace context: revision test; no permission to restore.]'},
  {role:'assistant',text:'Checking the model now.',tools:['cad_inspect']},
  {role:'toolResult',tool:'cad_inspect',text:'Read only.'},
  {role:'toolResult',tool:'cad_capabilities',text:'No changes.'},
  {role:'assistant',text:'**Lock** `document.json` [Files](/projects/dripper/downloads/test.stl) <img src=x onerror="document.body.dataset.injected=1"> [bad](javascript:alert(1)) [invalid](https://[broken)'}
 ]}}));
 await page.goto('/');
 await expect(page.locator('#chat-messages .chat-text strong')).toHaveText('Lock');
 await expect(page.locator('#chat-messages code')).toHaveText('document.json');
 await expect(page.locator('#chat-messages a')).toHaveCount(1);
 await expect(page.locator('#chat-messages img')).toHaveCount(0);
 await expect(page.locator('.chat-text details>summary')).toHaveText('Model context');
 await expect(page.locator('.chat-text details')).not.toHaveAttribute('open','');
 await expect(page.locator('.chat-activity-heading')).toHaveText('Activity · 2 tools');
 await expect(page.locator('.chat-message.planning')).toBeVisible();
 await expect(page.locator('details.chat-activity')).toHaveCount(0);
 await expect(page.locator('.toolResult>summary')).toHaveCount(2);
 expect(await page.evaluate(()=>document.body.dataset.injected)).toBeUndefined();
 expect(await page.evaluate(async()=>{const fonts=await document.fonts.load('22px "CAD Emoji"','🔒');return fonts[0]?.status;})).toBe('loaded');
});
