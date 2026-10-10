import {test,expect} from '@playwright/test';

for(const width of [1440,390,320])test(`missing Pi login shows setup and preserves drafts at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});
 let status='missing',prompts=0;
 const state=()=>({sessionId:'setup',model:'provider/model',busy:false,sequence:0,messages:[],partial:null,activeTools:[],error:'',providerAuth:{status,mode:'container',provider:'provider',model:'model',container:'custom-agent',remote_verified:false,blocking:status==='missing'}});
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:state()}));
 await page.route('**/api/agent/prompt',r=>{prompts++;return r.fulfill({status:202,json:{job:{status:'complete'}}});});
 await page.goto('/');
 if(width<900)await page.locator('#mobile-navigation').getByRole('button',{name:'Chat',exact:true}).click();
 const panel=page.locator('#chat-provider-login');await expect(panel).toContainText('No stored Pi login found');
 await expect(panel).toContainText('podman exec -it custom-agent pi');
 await expect(panel).toContainText('Never paste provider keys');
 await page.locator('#chat-input').fill('Keep this draft');await page.locator('#chat-input').press('Enter');
 await expect(page.locator('#chat-send')).toBeDisabled();expect(prompts).toBe(0);
 await page.reload();
 if(width<900)await page.locator('#mobile-navigation').getByRole('button',{name:'Chat',exact:true}).click();
 await expect(page.locator('#chat-input')).toHaveValue('Keep this draft');
 status='configured';await panel.getByRole('button',{name:'Recheck Pi login'}).click();
 await expect(panel).toContainText('Pi login available locally');
 await expect(page.locator('#chat-send')).toBeEnabled();expect(prompts).toBe(0);
 await expect(page.locator('#chat-input')).toHaveValue('Keep this draft');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.locator('#chat-send').click();await expect.poll(()=>prompts).toBe(1);
});

test('host expiry has host-only renewal instructions and does not disable Stop',async({page})=>{
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:{sessionId:'setup',model:'provider/model',busy:true,sequence:0,messages:[],partial:null,activeTools:[],error:'',providerAuth:{status:'expired',mode:'host',provider:'provider',model:'model',container:'3d-pi-agent',remote_verified:false,blocking:true}}}));
 await page.goto('/');const panel=page.locator('#chat-provider-login');
 await expect(panel).toContainText('Pi login expired');await expect(panel).toContainText('owning host');
 await expect(panel.locator('pre')).not.toContainText('podman exec');
 await expect(panel).toContainText('recreate the agent container');
 await expect(page.locator('#chat-send')).toBeDisabled();await expect(page.locator('#chat-stop')).toBeEnabled();
});

test('unreachable agent is not misreported as missing provider login',async({page})=>{
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({status:503,json:{detail:'Unavailable'}}));
 await page.goto('/');await expect(page.locator('#chat-provider-login')).toContainText('Cannot check Pi login');
 await expect(page.locator('#chat-provider-login')).toContainText('does not mean your provider login is missing');
 await expect(page.locator('#chat-send')).toBeDisabled();
});

test('missing stored credentials do not block a custom provider with unverified ambient auth',async({page})=>{
 await page.route('**/auth/session',r=>r.fulfill({json:{csrf:'test'}}));
 await page.route('**/api/agent/state',r=>r.fulfill({json:{sessionId:'setup',model:'custom/model',busy:false,sequence:0,messages:[],partial:null,activeTools:[],error:'',providerAuth:{status:'missing',mode:'container',provider:'custom',model:'model',container:'3d-pi-agent',remote_verified:false,blocking:false}}}));
 await page.goto('/');await expect(page.locator('#chat-provider-login')).toContainText('No stored Pi login found');
 await expect(page.locator('#chat-send')).toBeEnabled();
});
