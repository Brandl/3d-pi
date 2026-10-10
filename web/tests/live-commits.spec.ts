import {test,expect,type Page,type APIRequestContext,type WebSocketRoute} from '@playwright/test';

async function fixture(page:Page,request:APIRequestContext,count=1){
 const source=await (await request.get('/api/state')).json();
 const a=source.workspace?.revision??source.revision;
 if(!a)throw Error('Run with an isolated seeded CAD fixture');
 const b='b'.repeat(32);
 const row=await (await request.get(`/api/revisions/${a}`)).json();
 const preview=await (await request.get(`/api/revisions/${a}/artifacts/preview.json`)).json();
 await page.route(`**/api/revisions/${b}`,r=>r.fulfill({json:{...row,id:b,document:{...row.document,name:'Uncommitted preview'}}}));
 await page.route(`**/api/revisions/${b}/artifacts/preview.json`,r=>r.fulfill({json:preview}));
 const entry=(n:number,revision=a)=>({id:n.toString(16).padStart(32,'0'),generation:n,revision,name:`Design ${n}`,icon:'□',created:n,source_commit:'a'.repeat(40),source_file:'document.json'});
 const commits=Array.from({length:count},(_,i)=>entry(i+1));
 let current:any={...source,event_sequence:0,intermediates:[],generation:0,revision:null,publications:[],history:[],candidates:[b],workspace:{generation:count,revision:count?a:null,commit_id:commits.at(-1)?.id??null,commits,assets:[]}};
 let socket:WebSocketRoute|undefined;
 await page.route('**/api/state',r=>r.fulfill({json:current}));
 await page.routeWebSocket('**/api/events',ws=>{socket=ws;ws.send(JSON.stringify(current));});
 return {
  a,b,entry,commits,ready:async()=>expect.poll(()=>Boolean(socket)).toBe(true),
  snapshot:()=>structuredClone(current),send:(state:any)=>socket!.send(JSON.stringify(state)),
  push:(entries:any[],notify=true)=>{
   current={...current,event_sequence:current.event_sequence+1,intermediates:[],candidates:[],workspace:{...current.workspace,generation:entries.length,revision:entries.at(-1).revision,commit_id:entries.at(-1).id,commits:entries}};
   if(notify)socket!.send(JSON.stringify(current));
  },
  previews:(items:any[],history:any[]=[],notify=true)=>{
   current={...current,event_sequence:current.event_sequence+1,intermediates:items,history,candidates:[...new Set([...current.candidates,...items.map(i=>i.revision)])]};
   if(notify)socket!.send(JSON.stringify(current));
  },
 };
}

test('clicking the current thumbnail keeps following new live commits',async({page,request})=>{
 const f=await fixture(page,request);await page.goto('/');await f.ready();
 await page.locator('#history button').click();
 f.push([...f.commits,f.entry(2,f.b)]);
 await expect(page.locator('#history button')).toHaveCount(2);
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b);
 await expect(page.locator('#view-title')).toHaveText('Design 2');
});

test('new commits preserve historical viewing and manual strip position',async({page,request})=>{
 const f=await fixture(page,request,24);await page.goto('/');await f.ready();
 await page.locator('#history button').nth(9).click();
 const strip=page.locator('#history');await strip.evaluate(el=>el.scrollLeft=700);await page.waitForTimeout(100);
 const before=await strip.evaluate(el=>el.scrollLeft);
 f.push([...f.commits,f.entry(25,f.b)]);
 await expect(page.locator('#history button')).toHaveCount(25);
 expect(await strip.evaluate(el=>el.scrollLeft)).toBeCloseTo(before,0);
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
 await expect(page.locator('#timeline-working')).toContainText('New working design');
 await page.locator('#timeline-working').click();
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b);
 await expect(page.locator('#timeline-working')).toHaveText('Working design');
});

test('polling recovers a commit when its websocket update is missed',async({page,request})=>{
 const f=await fixture(page,request);await page.goto('/');await f.ready();
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
 f.push([...f.commits,f.entry(2,f.b)],false);
 await expect(page.locator('#view-title')).toHaveText('Design 2',{timeout:10000});
 await expect(page.locator('#history button')).toHaveCount(2);
});

test('a viewed candidate gets its commit name without reloading geometry or the page',async({page,request})=>{
 const f=await fixture(page,request);await page.goto('/?candidate='+f.b);await f.ready();
 await expect(page.locator('#view-title')).toHaveText('Uncommitted preview');
 const canvas=await page.locator('#viewport canvas').elementHandle();
 f.push([...f.commits,f.entry(2,f.b)]);
 await expect(page.locator('#history button')).toHaveCount(2);
 await expect(page.locator('#view-title')).toHaveText('Design 2');
 expect(await canvas!.evaluate(el=>el===document.querySelector('#viewport canvas'))).toBe(true);
});

test('successful intermediary streams, survives failures and stale events, then becomes a commit',async({page,request})=>{
 const f=await fixture(page,request);const writes:string[]=[];let previewLoads=0;
 page.on('request',r=>{if(['POST','PUT','PATCH','DELETE'].includes(r.method()))writes.push(r.url());if(r.url().endsWith(f.b+'/artifacts/preview.json'))previewLoads++;});
 await page.goto('/');await f.ready();await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
 const old=f.snapshot();const intermediates=[{revision:f.b,name:'Changed box',created:2}];
 f.previews(intermediates);
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b);
 await expect(page.locator('#viewport')).toHaveAttribute('data-working-revision',f.a);
 await expect(page.locator('#view-basis')).toHaveText('Intermediary state · not committed');
 await expect(page.locator('#history li.intermediary')).toHaveCount(1);
 await expect(page.locator('#timeline-restore')).toBeHidden();
 await expect(page.locator('#make-panel .make-intro')).toContainText('saved design, not the uncommitted');
 for(const bad of [{id:'c'.repeat(32),status:'failed'},{id:'d'.repeat(32),status:'ready',valid:false}]){
  f.previews(intermediates,[bad]);await expect(page.locator('#notice')).toContainText('keeping last good preview');
  await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b);
 }
 f.send(old);await page.waitForTimeout(150);
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b);
 await expect(page.locator('#history li.intermediary img')).toHaveAttribute('data-rendered','true');
 const loadedBeforePromotion=previewLoads;
 f.push([...f.commits,f.entry(2,f.b)]);
 await expect(page.locator('#view-title')).toHaveText('Design 2');
 await expect(page.locator('#view-basis')).toHaveText('Working design · geometry preview');
 await expect(page.locator('#history li.intermediary')).toHaveCount(0);
 expect(previewLoads).toBe(loadedBeforePromotion);expect(writes).toEqual([]);
});

for(const width of [1440,320])test(`history and saved mode stay put; Live resumes previews at ${width}px`,async({page,request})=>{
 await page.setViewportSize({width,height:900});
 const f=await fixture(page,request,3);await page.goto('/');await f.ready();
 await page.locator('#history button').first().click();
 f.previews([{revision:f.b,name:'Changed box',created:4}]);
 await expect(page.locator('#history li.intermediary')).toHaveCount(1);
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
 await expect(page.locator('#timeline-latest')).toHaveText('New preview');
 await page.locator('#timeline-latest').click();
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b);
 await page.locator('#timeline-working').click();
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
 await expect(page).toHaveURL(/view=working/);
 await page.reload();await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
 await page.locator('#timeline-latest').click();await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('first successful preview appears in an empty project via polling',async({page,request})=>{
 const f=await fixture(page,request,0);await page.goto('/');await f.ready();
 await expect(page.locator('#empty')).toBeVisible();
 f.previews([{revision:f.b,name:'First model',created:1}],[],false);
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.b,{timeout:10000});
 await expect(page.locator('#viewport')).toHaveAttribute('data-working-revision','');
 await expect(page.locator('#view-basis')).toHaveText('Intermediary state · not committed');
});

test('an unavailable intermediary artifact keeps the last good model',async({page,request})=>{
 const f=await fixture(page,request);await page.route(`**/api/revisions/${f.b}/artifacts/preview.json`,r=>r.fulfill({status:503,body:'Unavailable'}));
 await page.goto('/');await f.ready();await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
 f.previews([{revision:f.b,name:'Changed box',created:2}]);
 await expect(page.locator('#notice')).toContainText('Unable to load preview; keeping last good model');
 await expect(page.locator('#viewport')).toHaveAttribute('data-revision',f.a);
});
