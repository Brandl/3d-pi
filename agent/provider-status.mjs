import {readFileSync,statSync} from 'node:fs';
import {join} from 'node:path';

// Local metadata only: never resolve key commands, refresh OAuth, or contact a
// provider. "Configured" is not a remote authentication/entitlement verdict.
export function providerAuthStatus({env=process.env,now=Date.now()}={}) {
 const provider=env.PI_PROVIDER??'openai-codex',model=env.PI_MODEL??'gpt-6-astra';
 const mode=env.PI_SEED_AUTH_FILE?'host':'container';
 const container=/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$/.test(env.PI_CONTAINER_NAME??'')?env.PI_CONTAINER_NAME:'3d-pi-agent';
 // Other providers may use ambient/custom auth without a login file. Never
 // block those solely because this intentionally narrow check found no entry.
 const result=status=>({status,mode,provider,model,container,remote_verified:false,
  blocking:['expired','unreadable'].includes(status)||(status==='missing'&&(mode==='host'||provider==='openai-codex'))});
 const path=env.PI_SEED_AUTH_FILE||join(env.PI_AUTH_DIR??join(env.PI_STATE_DIR??'/agent-state','pi'),'auth.json');
 let credential;
 try {
  const info=statSync(path);
  if(!info.isFile()||info.size>256*1024)return result('unreadable');
  const data=JSON.parse(readFileSync(path,'utf8'));
  if(!data||typeof data!=='object'||Array.isArray(data))return result('unreadable');
  credential=Object.hasOwn(data,provider)?data[provider]:undefined;
 }catch(error){if(error.code!=='ENOENT')return result('unreadable');}
 if(!credential){
  // Ambient/custom auth is deliberately not evaluated. Do not call it missing
  // when an operator has explicitly supplied an alternative configuration.
  if(mode==='container'&&(Object.keys(env).some(key=>/(_API_KEY|_AUTH_TOKEN|_OAUTH_TOKEN)$/.test(key)&&env[key])||env.AWS_PROFILE||env.GOOGLE_APPLICATION_CREDENTIALS))return result('external');
  return result('missing');
 }
 if(credential.type==='oauth'){
  if(typeof credential.access!=='string'||!credential.access.trim()||!Number.isFinite(credential.expires))return result('unreadable');
  if(credential.expires<=now+60000){
   return result(mode==='host'||typeof credential.refresh!=='string'||!credential.refresh.trim()?'expired':'refresh_pending');
  }
  return result('configured');
 }
 if(credential.type==='api_key'){
  if(typeof credential.key==='string'&&credential.key.trim())return result(/[!$]/.test(credential.key)?'external':'configured');
  if(credential.env&&typeof credential.env==='object')return result('external');
  return result('missing');
 }
 return result('unreadable');
}
