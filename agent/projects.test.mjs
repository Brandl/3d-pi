import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
async function port(){const s=http.createServer();s.listen(0,'127.0.0.1');await once(s,'listening');const p=s.address().port;await new Promise(r=>s.close(r));return p;}
test('project router pins workers, rejects busy switching and keeps project transcripts separate',async()=>{
 const root=mkdtempSync(join(tmpdir(),'cad-project-router-'));const secret='z'.repeat(48);
 writeFileSync(join(root,'token'),secret);
 const fake=join(root,'worker.mjs');
 writeFileSync(fake,`import http from 'node:http';import fs from 'node:fs';
 let busy=false;const id=process.env.PI_PROJECT_ID;
 const state=()=>({busy,sessionId:id,model:'fake',sequence:0,messages:[{role:'assistant',text:process.env.CAD_URL}],partial:null,activeTools:[],error:'',job:null});
 const s=http.createServer((req,res)=>{if(req.url==='/prompt')busy=true;if(req.url==='/abort')busy=false;
 fs.writeFileSync(process.env.PI_STATE_DIR+'/web-state.json',JSON.stringify({...state(),busy:false}));
 res.writeHead(req.url==='/prompt'?202:200,{'Content-Type':'application/json'});res.end(JSON.stringify(state()));});
 s.listen(Number(process.env.PI_WEB_PORT),'127.0.0.1');process.on('SIGTERM',()=>s.close(()=>process.exit(0)));`);
 const cad=http.createServer((req,res)=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({projects:[{id:'a',name:'A'},{id:'b',name:'B'}]}));});
 cad.listen(0,'127.0.0.1');await once(cad,'listening');
 const routerPort=await port(),workerPort=await port();
 const router=spawn(process.execPath,['projects.mjs'],{cwd:import.meta.dirname,stdio:['ignore','pipe','pipe'],env:{...process.env,
  PI_STATE_DIR:root,PI_AUTH_DIR:join(root,'auth'),PI_SEED_AUTH_FILE:'',PI_PROVIDER:'test-provider',PI_MODEL:'fake',
  PI_PROJECTS_DIR:join(root,'projects'),CAD_URL:`http://127.0.0.1:${cad.address().port}`,
  CAD_AGENT_TOKEN_FILE:join(root,'token'),PI_ROUTER_PORT:String(routerPort),PI_WORKER_PORT:String(workerPort),PI_WORKER_PATH:fake}});
 const url=`http://127.0.0.1:${routerPort}`;
 const request=(path,method='GET')=>fetch(url+path,{method,headers:{Authorization:'Bearer '+secret},...(method==='POST'?{body:'{}'}:{}),signal:AbortSignal.timeout(15000)});
 try{
  await once(router.stdout,'data');
  assert.equal((await fetch(url+'/projects')).status,401);
  assert.equal((await request('/projects')).status,200);
  const denied=await fetch(url+'/projects/a/state');
  assert.equal(denied.status,401);assert.doesNotMatch(await denied.text(),/test-provider|providerAuth/);
  const initial=await (await request('/projects/a/state')).json();
  assert.equal(initial.sessionId,null);assert.ok(['missing','external'].includes(initial.providerAuth.status));
  // Status reads must not spawn/switch a worker or make a provider request.
  await assert.rejects(fetch(`http://127.0.0.1:${workerPort}/state`));
  mkdirSync(join(root,'auth'));writeFileSync(join(root,'auth/auth.json'),JSON.stringify({'test-provider':{type:'api_key',key:'private-test-value'}}));
  const configured=await (await request('/projects/a/state')).json();
  assert.equal(configured.providerAuth.status,'configured');assert.doesNotMatch(JSON.stringify(configured),/private-test-value/);
  assert.equal((await request('/projects/a/prompt','POST')).status,202);
  const a=await (await request('/projects/a/state')).json();assert.equal(a.busy,true);assert.equal(a.providerAuth.status,'configured');assert.match(a.messages[0].text,/\/projects\/a$/);
  assert.equal((await request('/projects/b/state')).status,200); // does not evict A
  assert.equal((await request('/projects/b/prompt','POST')).status,409);
  assert.equal((await request('/projects/b/abort','POST')).status,409);
  assert.equal((await (await request('/projects/a/state')).json()).busy,true);
  await request('/projects/a/abort','POST');
  assert.equal((await request('/projects/b/prompt','POST')).status,202);
  assert.match((await (await request('/projects/b/state')).json()).messages[0].text,/\/projects\/b$/);
  const cached=await (await request('/projects/a/state')).json();assert.equal(cached.busy,false);assert.equal(cached.sessionId,'a');
  writeFileSync(join(root,'projects/a/pi/transcript.md'),'project A only');
  assert.equal(await (await request('/projects/a/transcript')).text(),'project A only');
  assert.doesNotMatch(await (await request('/projects/b/transcript')).text(),/project A only/);
  assert.equal((await request('/projects/missing/state')).status,404);
  assert.equal(JSON.parse(readFileSync(join(root,'projects/a/project.json'))).id,'a');
  await request('/projects/b/abort','POST');
  writeFileSync(join(root,'projects/a/pi/transcript.md'),Buffer.alloc(8*1024*1024,65));
  const interrupted=await request('/projects/a/transcript');await interrupted.body.cancel();
  assert.equal((await request('/projects')).status,200); // cancelled download cannot wedge the router
 }finally{
  const exited=once(router,'exit');router.kill('SIGTERM');await exited;
  await new Promise(r=>cad.close(r));rmSync(root,{recursive:true,force:true});
 }
});
