import {projectPath, projectId} from './project-path';
type ChatMessage = {role:string;text:string;tools?:string[];tool?:string;error?:boolean};
type AgentState = {sessionId:string;model:string;busy:boolean;sequence:number;messages:ChatMessage[];
  partial:ChatMessage|null;activeTools:string[];error:string;job?:{status:string;error?:string}};
const element=(id:string)=>document.getElementById(id)!;
let csrf='';
let busy=false;
let pending=false;
let lastProjection='';
function login() {
  location.assign('/auth/login?next='+encodeURIComponent(location.pathname+location.search));
}
async function call(path:string,body?:unknown) {
  const response=await fetch(projectPath(path),{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
    headers:body===undefined?{}:{'Content-Type':'application/json','X-CAD-CSRF':csrf},
    body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
  if(response.status===401){login();throw new Error('Please sign in');}
  const data=await response.json();
  if(!response.ok)throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}
function controls() {
  (element('chat-send') as HTMLButtonElement).disabled=busy||pending;
  (element('chat-stop') as HTMLButtonElement).disabled=!busy;
}
function render(state:AgentState) {
  busy=state.busy;controls();
  element('chat-model').textContent=state.model||'No model configured';
  element('chat-status').textContent=state.error ||
    (state.activeTools.length?`Working: ${state.activeTools.join(', ')}`:busy?'Working…':['interrupted','aborted','failed'].includes(state.job?.status??'')?`Turn ${state.job?.status}. Previous changes may remain.`:'Ready');
  const projection=JSON.stringify([state.messages,state.partial]);
  if(projection===lastProjection)return;
  lastProjection=projection;
  const log=element('chat-messages');
  const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<70;
  log.replaceChildren();
  const messages=[...state.messages,...(state.partial?[state.partial]:[])];
  for(const message of messages) {
    if(!message.text && !message.tools?.length)continue;
    const item=document.createElement(message.role==='toolResult'?'details':'article');
    item.className=`chat-message ${message.role}`;
    const title=document.createElement(message.role==='toolResult'?'summary':'strong');
    title.textContent=message.role==='user'?'You':message.role==='toolResult'?`${message.tool || 'Tool'}${message.error?' · error':''}`:'Pi';
    const text=document.createElement('div');
    text.className='chat-text';text.textContent=message.text;
    item.append(title,text);
    if(message.tools?.length){const tools=document.createElement('small');tools.textContent=`Tools: ${message.tools.join(', ')}`;item.append(tools);}
    log.append(item);
  }
  if(atBottom)log.scrollTop=log.scrollHeight;
}
async function poll() {
  try {render(await call('/api/agent/state'));}
  catch(error){element('chat-status').textContent=String(error);}
  finally{setTimeout(poll,busy?700:2500);}
}
async function init() {
  // The private, loopback CAD service can still serve a viewer without web-agent UI.
  const response=await fetch('/auth/session',{credentials:'same-origin',cache:'no-store'});
  if(response.status===401){login();return;}
  if(!response.ok)return;
  csrf=(await response.json()).csrf;
  element('chat-panel').hidden=false;
  element('logout').hidden=false;
  document.body.classList.add('agent-enabled');
  element('chat-form').addEventListener('submit',async event=>{
    event.preventDefault();
    if(busy||pending)return;
    const input=element('chat-input') as HTMLTextAreaElement;
    const text=input.value.trim();if(!text)return;
    pending=true;controls();
    try {
      // Record the viewed version as context, never as a request to restore it.
      const data=element('viewport').dataset;
      const context=`\n\n[Workspace context: project ${projectId??'dripper'}; working revision ${data.workingRevision||'none'}; workspace generation ${data.workspaceGeneration||'0'}; viewed revision ${data.revision||'none'}; selected node ${data.component||'assembly'} (${data.part||'whole model'}); visual clipping ${data.sectioned==='true'?'on (not an exact solid section)':'off'}. Selection/view are context, not permission to restore. Inspect live state before edits. Actual design commits require a short name and Unicode icon via cad_commit; attach views/print/test outputs separately.]`;
      await call('/api/agent/prompt',{text:text+context,request_key:crypto.randomUUID()});
      input.value='';busy=true;render(await call('/api/agent/state'));
    } catch(error) {element('chat-status').textContent=String(error);}
    finally{pending=false;controls();}
  });
  element('chat-stop').addEventListener('click',async()=>{
    try{await call('/api/agent/abort',{});render(await call('/api/agent/state'));}
    catch(error){element('chat-status').textContent=String(error);}
  });
  element('logout').addEventListener('click',async()=>{
    try{await call('/auth/logout',{});login();}
    catch(error){element('chat-status').textContent=String(error);}
  });
  void poll();
}
const view=element('viewport');
function contextLabel(){const data=view.dataset;const label=document.getElementById('chat-context');if(label)label.textContent=`${data.part||'Whole model'}${data.revision&&data.workingRevision&&data.revision!==data.workingRevision?' · viewing a related or historical output':''}`;}
new MutationObserver(contextLabel).observe(view,{attributes:true,attributeFilter:['data-part','data-component','data-revision','data-working-revision']});
window.addEventListener('cad:draft',e=>{const input=element('chat-input') as HTMLTextAreaElement;input.value=(e as CustomEvent).detail.text;input.focus();});
void init().catch(()=>{});
