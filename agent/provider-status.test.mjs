import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {providerAuthStatus} from './provider-status.mjs';

test('local provider status is bounded, non-secret, read-only and distinguishes auth ownership',()=>{
 const root=mkdtempSync(join(tmpdir(),'pi-auth-status-'));const file=join(root,'pi','auth.json');mkdirSync(join(root,'pi'));
 const env={PI_STATE_DIR:root,PI_PROVIDER:'test-provider',PI_MODEL:'test-model',PI_CONTAINER_NAME:'custom-agent'};
 const secret='never-return-credential-values';const now=100000;
 const status=(extra={})=>providerAuthStatus({env:{...env,...extra},now});
 try{
  assert.equal(status().status,'missing');assert.equal(status().blocking,false);
  assert.equal(status({PI_PROVIDER:'openai-codex'}).blocking,true);
  for(const [credential,expected] of [
   [{type:'api_key',key:secret},'configured'],
   [{type:'api_key',key:'!do-not-execute-this'},'external'],
   [{type:'api_key',key:'$MISSING_ENV'},'external'],
   [{type:'oauth',access:secret,refresh:secret,expires:now+120000},'configured'],
   [{type:'oauth',access:secret,refresh:secret,expires:now-1},'refresh_pending'],
   [{type:'oauth',access:secret,expires:now-1},'expired'],
   [{type:'oauth',access:secret,expires:'invalid'},'unreadable'],
   [{type:'api_key',key:''},'missing'],
  ]){
   const raw=JSON.stringify({'test-provider':credential});writeFileSync(file,raw);
   const result=status();assert.equal(result.status,expected);assert.equal(result.remote_verified,false);
   assert.deepEqual(Object.keys(result).sort(),['status','mode','provider','model','container','remote_verified','blocking'].sort());
   assert.doesNotMatch(JSON.stringify(result),/never-return|do-not-execute|MISSING_ENV/);
   assert.equal(readFileSync(file,'utf8'),raw);
  }
  writeFileSync(file,JSON.stringify({'test-provider':{type:'oauth',access:secret,refresh:secret,expires:now-1}}));
  assert.equal(status({PI_SEED_AUTH_FILE:file}).status,'expired');assert.equal(status({PI_SEED_AUTH_FILE:file}).mode,'host');
  writeFileSync(file,'malformed '+secret);assert.equal(status().status,'unreadable');assert.doesNotMatch(JSON.stringify(status()),new RegExp(secret));
  writeFileSync(file,'x'.repeat(256*1024+1));assert.equal(status().status,'unreadable');
  writeFileSync(file,'{}');assert.equal(status({OTHER_API_KEY:secret}).status,'external');
  assert.equal(status({PI_SEED_AUTH_FILE:file,OTHER_API_KEY:secret}).status,'missing');
  assert.equal(status({PI_CONTAINER_NAME:'bad; command'}).container,'3d-pi-agent');
 }finally{rmSync(root,{recursive:true,force:true});}
});
