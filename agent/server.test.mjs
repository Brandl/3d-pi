import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync,readFileSync,writeFileSync} from 'node:fs';
import {ReadOnlyCredentialStore} from './credentials.mjs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createBridge,visibleMessage} from './server.mjs';

function fakeSession() {
  let resolve;
  return {messages:[],sessionId:'test',model:{provider:'test',id:'fake'},calls:0,
    subscribe(){return ()=>{};},dispose(){},
    async prompt(text){this.calls++;this.messages.push({role:'user',content:text});await new Promise(r=>resolve=r);},
    async abort(){resolve?.();},finish(){resolve?.();}};
}

test('bridge authenticates, persists requests, deduplicates and stops',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'cad-agent-'));
  const session=fakeSession();const token='test-token-'.repeat(5);const journalPath=join(directory,'requests.json');
  const bridge=createBridge({session,token,journalPath});
  await new Promise(resolve=>bridge.server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${bridge.server.address().port}`;
  const headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'};
  const post=(body)=>fetch(base+'/prompt',{method:'POST',headers,body:JSON.stringify(body)});
  try {
    assert.equal((await fetch(base+'/state')).status,401);
    assert.equal((await post({text:'hello',request_key:'request-1'})).status,202);
    assert.equal((await post({text:'hello',request_key:'request-1'})).status,200);
    assert.equal(session.calls,1);
    assert.equal((await post({text:'different',request_key:'request-1'})).status,409);
    assert.equal((await post({text:'hello again',request_key:'request-2'})).status,409);
    assert.equal((await fetch(base+'/state',{headers})).status,200);
    assert.equal((await fetch(base+'/abort',{method:'POST',headers})).status,200);
    await new Promise(r=>setTimeout(r,10));
    assert.equal((await (await fetch(base+'/state',{headers})).json()).busy,false);
    assert.equal(JSON.parse(readFileSync(journalPath))[0].status,'aborted');
  } finally {
    await bridge.dispose();await new Promise(r=>bridge.server.close(r));rmSync(directory,{recursive:true});
  }
});

test('web projection excludes thinking and binary image data',()=>{
  const message=visibleMessage({role:'assistant',content:[{type:'thinking',thinking:'private thought'},
    {type:'text',text:'Visible reply'},{type:'image',data:'SECRET_IMAGE'},{type:'toolCall',name:'cad_inspect',arguments:{}}]});
  assert.equal(message.text,'Visible reply');assert.deepEqual(message.tools,['cad_inspect']);
  assert.ok(!JSON.stringify(message).includes('private thought'));
  assert.ok(!JSON.stringify(message).includes('SECRET_IMAGE'));
  assert.equal(visibleMessage({role:'compactionSummary',summary:'internal'}),null);
});

test('restart marks an unfinished request interrupted without replay',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'cad-agent-'));const journalPath=join(directory,'requests.json');
  writeFileSync(journalPath,JSON.stringify([{id:'request-1',hash:'test-hash',status:'running'}]));
  const session=fakeSession();const bridge=createBridge({session,token:'x'.repeat(40),journalPath});
  try {assert.equal(JSON.parse(readFileSync(journalPath))[0].status,'interrupted');assert.equal(session.calls,0);}
  finally {await bridge.dispose();rmSync(directory,{recursive:true});}
});

test('project transcript persists visible events without thinking or image payloads',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'cad-transcript-'));
  const session=fakeSession();let emit;
  session.subscribe=handler=>{emit=handler;return ()=>{};};
  const transcriptPath=join(directory,'transcript.md'),projectionPath=join(directory,'web-state.json');
  const bridge=createBridge({session,token:'x'.repeat(40),journalPath:join(directory,'requests.json'),transcriptPath,projectionPath});
  try {
    emit({type:'message_end',message:{role:'assistant',content:[{type:'text',text:'Project-specific reply'},{type:'thinking',thinking:'SECRET_THOUGHT'},{type:'image',data:'SECRET_IMAGE'}]}});
    const text=readFileSync(transcriptPath,'utf8');assert.match(text,/Project-specific reply/);assert.doesNotMatch(text,/SECRET/);
    assert.equal(JSON.parse(readFileSync(projectionPath)).sessionId,'test');
  }finally{await bridge.dispose();rmSync(directory,{recursive:true});}
});

for(const mode of ['idle','progress'])test(`turn timeout distinguishes ${mode} and never replays`,async()=>{
 const directory=mkdtempSync(join(tmpdir(),'cad-timeout-'));
 const session=fakeSession();let emit=()=>{};
 session.subscribe=handler=>{emit=handler;return ()=>{};};
 const bridge=createBridge({session,token:'x'.repeat(40),journalPath:join(directory,'requests.json'),idleTimeoutMs:200,turnTimeoutMs:700});
 await new Promise(resolve=>bridge.server.listen(0,'127.0.0.1',resolve));
 const base=`http://127.0.0.1:${bridge.server.address().port}`;const headers={Authorization:'Bearer '+'x'.repeat(40),'Content-Type':'application/json'};
 const timer=mode==='progress'?setInterval(()=>emit({type:'tool_execution_end',toolCallId:'test'}),30):null;
 try{
  await fetch(base+'/prompt',{method:'POST',headers,body:JSON.stringify({text:'test',request_key:'timeout-test'})});
  let state;
  for(let i=0;i<100;i++){
   state=await (await fetch(base+'/state',{headers})).json();
   if(!state.busy)break;
   await new Promise(resolve=>setTimeout(resolve,20));
  }
  assert.equal(state.job.status,'timed_out');
  assert.equal(state.job.stop_reason,mode==='idle'?'idle_timeout':'turn_timeout');
  assert.match(state.error,/Inspect existing changes/);
  assert.equal(session.calls,1);
 }finally{clearInterval(timer);await bridge.dispose();await new Promise(resolve=>bridge.server.close(resolve));rmSync(directory,{recursive:true});}
});

test('host credential bridge never invokes refresh or writes credentials',async()=>{
  const directory=mkdtempSync(join(tmpdir(),'cad-credentials-'));const path=join(directory,'auth.json');
  const original=JSON.stringify({test:{type:'oauth',access:'dummy',refresh:'dummy-refresh',expires:Date.now()+3600000}});
  writeFileSync(path,original,{mode:0o600});const store=new ReadOnlyCredentialStore(path,'test');
  try {
    assert.deepEqual(await store.list(),[{providerId:'test',type:'oauth'}]);
    assert.equal(await store.read('other'),undefined);
    let refreshed=false;
    await assert.rejects(store.modify('test',async()=>{refreshed=true;return {};}),/Read-only/);
    assert.equal(refreshed,false);assert.equal(readFileSync(path,'utf8'),original);
    writeFileSync(path,JSON.stringify({test:{type:'oauth',expires:Date.now()-1000}}));
    assert.equal(await store.read('test'),undefined);
  } finally {rmSync(directory,{recursive:true});}
});
