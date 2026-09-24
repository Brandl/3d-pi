import {projectPath, projectId} from './project-path';
import {formatChatText} from './chat-format';
type ChatMessage = {role:string;text:string;tools?:string[];tool?:string;error?:boolean;timestamp?:number|string};
type AgentState = {sessionId:string;model:string;busy:boolean;sequence:number;messages:ChatMessage[];
  partial:ChatMessage|null;activeTools:string[];error:string;job?:{status:string;error?:string}};
const element=(id:string)=>document.getElementById(id)!;
let csrf='';
let busy=false;
let pending=false;
let lastProjection='';
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
    (state.activeTools.length?`Working · ${state.activeTools.length} active tool${state.activeTools.length===1?'':'s'}`:busy?'Thinking…':['interrupted','aborted','failed'].includes(state.job?.status??'')?`Turn ${state.job?.status}. Previous changes may remain.`:'Ready');
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
  let activity:HTMLDetailsElement|null=null;
  let toolCount=0;
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
        const card=document.createElement('details');card.className='chat-turn';card.dataset.chatKey=turnKey;card.open=expanded.get(turnKey)??errors;
        const summary=document.createElement('summary');const label=document.createElement('strong');label.textContent=errors?'Earlier request · tool error':'Earlier request';
        const prompt=document.createElement('span');const request=visibleText(message);prompt.textContent=request.slice(0,130)+(request.length>130?'…':'');
        summary.append(label,prompt);
        if(lastAnswer){const preview=document.createElement('span');preview.className='turn-preview';preview.textContent=lastAnswer.text.slice(0,200)+(lastAnswer.text.length>200?'…':'');summary.append(preview);}
        const body=document.createElement('div');body.className='chat-turn-body';card.append(summary,body);log.append(card);target=body;
      }
    }
    if(!message.text)continue;
    const planning=message.role==='assistant'&&Boolean(message.tools?.length);
    const activityMessage=message.role==='toolResult'||planning;
    const item=document.createElement(activityMessage?'details':'article');
    item.className=`chat-message ${planning?'planning':message.role}`;
    const title=document.createElement(activityMessage?'summary':'strong');
    title.textContent=message.role==='user'?'You':planning?'Progress note':message.role==='toolResult'?`${message.tool || 'Tool'}${message.error?' · error':''}`:'Pi';
    const text=document.createElement('div');
    const contextAt=message.role==='user'?Math.max(message.text.lastIndexOf('\n\n[Workspace context:'),message.text.lastIndexOf('\n\n[Viewer context:')):-1;
    text.className='chat-text';if(message.role==='toolResult')text.textContent=message.text;else formatChatText(text,contextAt<0?message.text:message.text.slice(0,contextAt));
    if(contextAt>=0){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Model context';const context=document.createElement('small');context.textContent=message.text.slice(contextAt).trim();details.append(summary,context);text.append(details);}
    item.append(title,text);
    if(message.tools?.length){const tools=document.createElement('small');tools.textContent=`Tools: ${message.tools.join(', ')}`;item.append(tools);}
    if(activityMessage){
      if(!activity){activity=document.createElement('details');activity.className='chat-activity';activity.dataset.chatKey=`${turnKey}:activity:${messageKey(message.text)}`;activity.open=expanded.get(activity.dataset.chatKey)??false;activity.append(document.createElement('summary'));target.append(activity);toolCount=0;}
      if(message.role==='toolResult')toolCount++;
      activity.firstElementChild!.textContent=toolCount?`Activity · ${toolCount} tool${toolCount===1?'':'s'}`:'Activity · planning';
      item.dataset.chatKey=`${turnKey}:tool:${messageKey((message.tool??'')+message.text)}`;
      (item as HTMLDetailsElement).open=expanded.get(item.dataset.chatKey)??Boolean(message.error);
      activity.append(item);
      if(message.error&&expanded.get(activity.dataset.chatKey!)===undefined)activity.open=true;
    }else{activity=null;target.append(item);}
  }
  log.scrollTop=atBottom?log.scrollHeight:scrollTop;
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
