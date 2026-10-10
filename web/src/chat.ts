import {projectPath, projectId} from './project-path';
import {formatChatText} from './chat-format';
import {createProviderLogin,type ProviderAuth} from './provider-login';
type ChatMessage = {role:string;text:string;tools?:string[];tool?:string;error?:boolean;timestamp?:number|string};
type AgentState = {sessionId:string;model:string;busy:boolean;sequence:number;messages:ChatMessage[];
  partial:ChatMessage|null;activeTools:string[];error:string;providerAuth?:ProviderAuth;job?:{id?:string;status:string;error?:string}};
const element=(id:string)=>document.getElementById(id)!;
let csrf='';
let busy=false;
let pending=false;
let lastProjection='';
let authBlocked=true;
let providerLogin:ReturnType<typeof createProviderLogin>|undefined;
type Outgoing={request_key:string;text:string;draft:string;created:number};
let outgoing:Outgoing|null=null;
let stateEpoch=0;
const draftKey=`3d-pi.chat:${projectId??'dripper'}`;
function saveDraft(){
  const draft=(element('chat-input') as HTMLTextAreaElement).value;
  sessionStorage.setItem(draftKey,JSON.stringify({draft,outgoing}));
}
function restoreDraft(){
  try{
    const saved=JSON.parse(sessionStorage.getItem(draftKey)||'null');
    if(typeof saved?.draft==='string')(element('chat-input') as HTMLTextAreaElement).value=saved.draft;
    const o=saved?.outgoing;
    if(o&&typeof o.request_key==='string'&&typeof o.text==='string'&&typeof o.draft==='string'&&typeof o.created==='number')outgoing=o;
  }catch{/* Corrupt/unavailable storage must not submit anything. */}
}
function acknowledged(){
  const input=element('chat-input') as HTMLTextAreaElement;
  if(outgoing&&input.value===outgoing.draft)input.value='';
  outgoing=null;
  try{saveDraft();}catch{try{sessionStorage.removeItem(draftKey);}catch{}}
}
class RequestError extends Error {constructor(message:string,public status:number){super(message);}}

function visibleText(message:ChatMessage){
  const at=message.role==='user'?Math.max(message.text.lastIndexOf('\n\n[Workspace context:'),message.text.lastIndexOf('\n\n[Viewer context:')):-1;
  return at<0?message.text:message.text.slice(0,at);
}
function messageKey(text:string){let hash=2166136261;for(let i=0;i<text.length;i++)hash=Math.imul(hash^text.charCodeAt(i),16777619);return (hash>>>0).toString(36);}
function login() {
  location.assign('/auth/login?next='+encodeURIComponent(location.pathname+location.search));
}
async function call(path:string,body?:unknown) {
  const response=await fetch(projectPath(path),{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
    headers:body===undefined?{}:{'Content-Type':'application/json','X-CAD-CSRF':csrf},
    body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
  if(response.status===401){login();throw new Error('Please sign in');}
  const data=await response.json();
  if(!response.ok)throw new RequestError(data.detail || `HTTP ${response.status}`,response.status);
  return data;
}
function controls() {
  (element('chat-send') as HTMLButtonElement).disabled=busy||pending||Boolean(outgoing)||authBlocked;
  element('chat-send').textContent=pending?'Sending…':'Send →';
  (element('chat-stop') as HTMLButtonElement).disabled=!busy;
  const notice=document.getElementById('chat-delivery');
  if(notice){
    notice.hidden=!outgoing;
    notice.querySelector('span')!.textContent=pending?'Sending your request…':'Delivery unconfirmed. Your request is saved; check or retry the same request, not a new turn.';
    for(const button of Array.from(notice.querySelectorAll('button'))){button.disabled=pending||(button.textContent==='Check / retry'&&authBlocked);button.hidden=pending;}
  }
}
function render(state:AgentState) {
  if(outgoing&&state.job?.id===outgoing.request_key)acknowledged();
  authBlocked=providerLogin?.update(state.providerAuth)??false;
  busy=state.busy;controls();
  element('chat-model').textContent=state.model||'No model configured';
  element('chat-status').textContent=state.error ||
    (state.activeTools.length?`Working · ${state.activeTools.length} active tool${state.activeTools.length===1?'':'s'}`:busy?'Thinking…':authBlocked?'Pi login needed — see setup above':['interrupted','aborted','failed','timed_out'].includes(state.job?.status??'')?`Turn ${state.job?.status}. Previous changes may remain.`:'Ready');
  element('chat-status').title=state.activeTools.join(', ');
  const projection=JSON.stringify([state.sessionId,state.messages,state.partial]);
  if(projection===lastProjection)return;
  lastProjection=projection;
  const log=element('chat-messages');
  const scrollTop=log.scrollTop;
  const atBottom=log.scrollHeight-scrollTop-log.clientHeight<70;
  const expanded=new Map(Array.from(log.querySelectorAll<HTMLDetailsElement>('details[data-chat-key]')).map(d=>[d.dataset.chatKey!,d.open]));
  log.replaceChildren();
  const messages=[...state.messages,...(state.partial?[state.partial]:[])];
  const lastUser=messages.map(m=>m.role).lastIndexOf('user');
  let target:HTMLElement=log;
  let activity:HTMLElement|null=null;
  let toolCount=0,errorCount=0;
  let turnKey='initial';
  const occurrences=new Map<string,number>();
  for(const [index,message] of messages.entries()) {
    if(message.role==='user'){
      activity=null;target=log;
      const hash=messageKey(message.text);const occurrence=(occurrences.get(hash)??0)+1;occurrences.set(hash,occurrence);turnKey=`${state.sessionId}:${message.timestamp??`${hash}:${occurrence}`}`;
      if(index<lastUser){
        const next=messages.findIndex((m,i)=>i>index&&m.role==='user');
        const turn=messages.slice(index,next<0?messages.length:next);
        const lastAnswer=[...turn].reverse().find(m=>m.role==='assistant'&&m.text&&!m.tools?.length);
        const errors=turn.some(m=>m.error);
        const card=document.createElement('details');card.className='chat-turn';card.dataset.chatKey=turnKey;card.open=expanded.get(turnKey)??false;
        const summary=document.createElement('summary');const label=document.createElement('strong');label.textContent=errors?'Earlier request · tool error':'Earlier request';
        const prompt=document.createElement('span');const request=visibleText(message);prompt.textContent=request.slice(0,130)+(request.length>130?'…':'');
        summary.append(label,prompt);
        if(lastAnswer){const preview=document.createElement('span');preview.className='turn-preview';formatChatText(preview,lastAnswer.text.slice(0,200)+(lastAnswer.text.length>200?'…':''));summary.append(preview);}
        const body=document.createElement('div');body.className='chat-turn-body';card.append(summary,body);log.append(card);target=body;
      }
    }
    if(!message.text)continue;
    const planning=message.role==='assistant'&&Boolean(message.tools?.length);
    const activityMessage=message.role==='toolResult'||planning;
    const item=document.createElement(message.role==='toolResult'?'details':'article');
    item.className=`chat-message ${planning?'planning':message.role}`;
    const title=document.createElement(message.role==='toolResult'?'summary':'strong');
    title.textContent=message.role==='user'?'You':planning?'Progress note':message.role==='toolResult'?`${message.tool || 'Tool'}${message.error?' · error':''}`:'Pi';
    const text=document.createElement('div');
    const contextAt=message.role==='user'?Math.max(message.text.lastIndexOf('\n\n[Workspace context:'),message.text.lastIndexOf('\n\n[Viewer context:')):-1;
    text.className='chat-text';if(message.role==='toolResult')text.textContent=message.text;else formatChatText(text,contextAt<0?message.text:message.text.slice(0,contextAt));
    if(contextAt>=0){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Model context';const context=document.createElement('small');context.textContent=message.text.slice(contextAt).trim();details.append(summary,context);text.append(details);}
    item.append(title,text);
    if(message.role==='assistant'&&!planning&&index>=lastUser&&message!==state.partial){
      const actions=document.createElement('div');actions.className='chat-response-actions';
      const model=document.createElement('button');model.type='button';model.textContent='View model';model.onclick=()=>{
        if(matchMedia('(max-width:900px)').matches)document.querySelector<HTMLButtonElement>('#mobile-navigation [data-pane=model]')?.click();
        else document.querySelector<HTMLButtonElement>('.studio-tabs button[aria-controls=viewport]')?.click();
      };
      const files=document.createElement('button');files.type='button';files.textContent='Open files';files.onclick=()=>element('open-files').click();
      actions.append(model,files);item.append(actions);
    }
    if(message.tools?.length){const tools=document.createElement('small');tools.textContent=`Tools: ${message.tools.join(', ')}`;item.append(tools);}
    if(activityMessage){
      if(!activity){activity=document.createElement('section');activity.className='chat-activity';const heading=document.createElement('div');heading.className='chat-activity-heading';activity.append(heading);target.append(activity);toolCount=0;errorCount=0;}
      if(message.role==='toolResult')toolCount++;
      if(message.error)errorCount++;
      activity.firstElementChild!.textContent=(toolCount?`Activity · ${toolCount} tool${toolCount===1?'':'s'}`:'Activity · planning')+(errorCount?` · ${errorCount} error${errorCount===1?'':'s'}`:'');
      item.dataset.chatKey=`${turnKey}:tool:${messageKey((message.tool??'')+message.text)}`;
      if(message.role==='toolResult')(item as HTMLDetailsElement).open=expanded.get(item.dataset.chatKey)??Boolean(message.error);
      activity.append(item);
    }else{activity=null;target.append(item);}
  }
  log.scrollTop=atBottom?log.scrollHeight:scrollTop;
}
async function poll(repeat=true) {
  const epoch=stateEpoch;
  try {const state=await call('/api/agent/state');if(epoch===stateEpoch&&!pending)render(state);}
  catch{providerLogin?.unavailable();element('chat-status').textContent='Connection interrupted — reconnecting. This does not stop the agent.';}
  finally{if(repeat)setTimeout(()=>void poll(),busy?700:2500);}
}
async function deliver(){
  if(!outgoing||pending||authBlocked)return;
  // Never automatically replay, and never assign a new key to an uncertain send.
  if(Date.now()-outgoing.created>24*60*60*1000){element('chat-status').textContent='This saved request is over a day old. Inspect project history before recovering it; automatic resubmission is disabled.';return;}
  pending=true;stateEpoch++;controls();
  try{
    const result=await call('/api/agent/prompt',{text:outgoing.text,request_key:outgoing.request_key});
    acknowledged();busy=result.job?.status==='running';
    element('chat-status').textContent=busy?'Request received · working…':'Request already received.';
  }catch(error){
    // Explicit client rejection means nothing was accepted. Network/5xx results
    // are ambiguous: retain the immutable payload and key for an explicit retry.
    if(error instanceof RequestError&&[400,403,409,413,422].includes(error.status)){
      outgoing=null;try{saveDraft();}catch{}element('chat-status').textContent=error.message;
    }else element('chat-status').textContent='Could not confirm delivery. Your request and draft are saved.';
  }finally{pending=false;stateEpoch++;controls();}
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
  restoreDraft();
  providerLogin=createProviderLogin(()=>poll(false));
  const delivery=document.createElement('div');delivery.id='chat-delivery';delivery.setAttribute('role','status');delivery.hidden=true;
  const deliveryText=document.createElement('span');const retry=document.createElement('button');retry.type='button';retry.textContent='Check / retry';retry.onclick=()=>void deliver();
  const dismiss=document.createElement('button');dismiss.type='button';dismiss.textContent='Keep draft only';dismiss.onclick=()=>{
    if(pending||!confirm('This does not cancel an accepted request. Inspect project history first. Remove the local delivery receipt and keep your draft?'))return;
    outgoing=null;try{saveDraft();}catch{}controls();
  };
  delivery.append(deliveryText,retry,dismiss);element('chat-form').before(delivery);
  const hint=document.createElement('small');hint.className='chat-compose-hint';hint.textContent='Enter to send · Shift+Enter for a new line';element('chat-form').append(hint);
  element('chat-input').addEventListener('input',()=>{try{saveDraft();}catch{element('chat-status').textContent='Draft cannot be saved in this browser. Keep this tab open.';}});
  controls();
  element('chat-input').addEventListener('keydown',event=>{
    if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){
      event.preventDefault();
      if(!busy&&!pending&&!outgoing&&!authBlocked)(element('chat-form') as HTMLFormElement).requestSubmit();
    }
  });
  element('chat-input').setAttribute('aria-description','Enter to send. Shift+Enter for a new line.');
  element('chat-form').addEventListener('submit',async event=>{
    event.preventDefault();
    if(busy||pending||outgoing||authBlocked)return;
    const input=element('chat-input') as HTMLTextAreaElement;
    const text=input.value.trim();if(!text)return;
    try {
      // Record the viewed version as context, never as a request to restore it.
      const data=element('viewport').dataset;
      const context=`\n\n[Workspace context: project ${projectId??'dripper'}; working revision ${data.workingRevision||'none'}; workspace generation ${data.workspaceGeneration||'0'}; viewed revision ${data.revision||'none'}; intermediary preview ${data.revision&&data.intermediaryRevision===data.revision?'yes (not committed)':'no'}; selected node ${data.component||'assembly'} (${data.part||'whole model'}); visual clipping ${data.sectioned==='true'?'on (not an exact solid section)':'off'}. Selection/view are context, not permission to restore. Inspect live state before edits. Actual design commits require a short name and Unicode icon via cad_commit; attach views/print/test outputs separately.]`;
      outgoing={text:text+context,draft:input.value,request_key:crypto.randomUUID(),created:Date.now()};
      try{saveDraft();}catch{outgoing=null;throw new Error('Message not sent: browser storage is unavailable. Your draft is still here.');}
      await deliver();
    } catch(error) {element('chat-status').textContent=String(error);controls();}
  });
  element('chat-stop').addEventListener('click',async()=>{
    try{stateEpoch++;await call('/api/agent/abort',{});render(await call('/api/agent/state'));}
    catch(error){element('chat-status').textContent=String(error);}
  });
  element('logout').addEventListener('click',async()=>{
    try{await call('/auth/logout',{});for(const key of Object.keys(sessionStorage))if(key.startsWith('3d-pi.chat:'))sessionStorage.removeItem(key);login();}
    catch(error){element('chat-status').textContent=String(error);}
  });
  void poll();
}
const view=element('viewport');
function contextLabel(){const data=view.dataset;const label=document.getElementById('chat-context');if(label)label.textContent=`${data.part||'Whole model'}${data.revision&&data.intermediaryRevision===data.revision?' · intermediary preview (not committed)':data.revision&&data.workingRevision&&data.revision!==data.workingRevision?' · viewing a related or historical output':''}`;}
new MutationObserver(contextLabel).observe(view,{attributes:true,attributeFilter:['data-part','data-component','data-revision','data-working-revision','data-intermediary-revision']});
window.addEventListener('cad:draft',e=>{const input=element('chat-input') as HTMLTextAreaElement;input.value=(e as CustomEvent).detail.text;input.dispatchEvent(new Event('input'));input.focus();});
void init().catch(()=>{});
