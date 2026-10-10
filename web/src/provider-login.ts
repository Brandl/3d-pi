export type ProviderAuth={status:'missing'|'expired'|'unreadable'|'configured'|'refresh_pending'|'external';mode:'host'|'container';provider:string;model:string;container:string;remote_verified:false;blocking:boolean};

export function createProviderLogin(recheck:()=>Promise<void>){
 const panel=document.createElement('details');panel.id='chat-provider-login';panel.open=true;
 const summary=document.createElement('summary');summary.textContent='Checking Pi login…';panel.append(summary);
 document.getElementById('chat-messages')!.before(panel);
 let key='';
 const unavailable=()=>{
  key='';panel.hidden=false;panel.open=true;
  const title=document.createElement('summary');title.textContent='Cannot check Pi login';
  const note=document.createElement('p');note.textContent='The agent service could not be reached. This does not mean your provider login is missing. Check the service, then recheck. Existing work is not cancelled.';
  panel.replaceChildren(title,note,button());
 };
 function button(){
  const check=document.createElement('button');check.type='button';check.textContent='Recheck Pi login';
  check.onclick=async()=>{check.disabled=true;try{await recheck();}finally{check.disabled=false;}};
  return check;
 }
 function update(auth?:ProviderAuth){
  // Older servers do not report auth metadata. Preserve compatibility, never
  // fabricate an authentication verdict from a successful website login.
  if(!auth){panel.hidden=true;key='';return false;}
  const needsSetup=['missing','expired','unreadable'].includes(auth.status);
  const blocked=auth.blocking??needsSetup;
  const next=JSON.stringify(auth);if(next===key)return blocked;key=next;
  panel.hidden=false;panel.open=needsSetup;
  const title=document.createElement('summary');
  title.textContent=({missing:'No stored Pi login found',expired:'Pi login expired or expiring',unreadable:'Pi login could not be read',configured:'Pi login available locally',refresh_pending:'Pi login stored · renewal needed',external:'Pi authentication not checked (external configuration)'})[auth.status]??'Pi authentication status unavailable';
  const model=document.createElement('p');model.textContent=`Configured: ${auth.provider} / ${auth.model}`;
  const note=document.createElement('p');note.textContent='This is a local credential check, not a provider connection test. It does not evaluate ambient/custom authentication or verify model access, billing or revoked credentials.';
  const instruction=document.createElement('p');instruction.textContent=auth.mode==='host'
   ?'This installation uses a read-only host login. While the agent is idle, run Pi on the owning host and use /login for the configured provider. Do not log in inside the container for this mode.'
   :'While the agent is idle, open a terminal on the server and run the command below. In Pi, use /login and choose the configured provider.';
  const command=document.createElement('pre');const code=document.createElement('code');
  const container=/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$/.test(auth.container)?auth.container:'3d-pi-agent';
  code.textContent=auth.mode==='host'?'pi\n# In Pi: /login':`podman exec -it ${container} pi\n# In Pi: /login`;command.append(code);
  const finish=document.createElement('p');finish.textContent=auth.mode==='host'
   ?'If host renewal replaced the credential file, recreate the agent container with the same persistent volumes while idle so its bind mount sees the renewed file. Then recheck here.'
   :'Follow Pi’s authorization link/code prompts, then exit the terminal client before browser work. Credentials persist in the agent volume. Recheck here; requests are not automatically resent.';
  const safety=document.createElement('p');safety.textContent='Never paste provider keys, tokens or authorization codes into this chat. Verify PI_PROVIDER and PI_MODEL in the server configuration; a terminal /model choice does not change the web configuration.';
  panel.replaceChildren(title,model,instruction,command,finish,safety,note);
  if(auth.status==='refresh_pending'){
   const refresh=document.createElement('p');refresh.textContent='Pi owns this login and can attempt OAuth renewal on the next request. No renewal was attempted by this check.';panel.append(refresh);
  }
  if(auth.status==='external'){
   const external=document.createElement('p');external.textContent='Environment, ambient credentials and key commands are not evaluated by this check. They may or may not authorize the configured provider.';panel.append(external);
  }
  panel.append(button());return blocked;
 }
 return {update,unavailable};
}
