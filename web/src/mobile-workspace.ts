import './mobile-workspace.css';

export function initMobileWorkspace(){
 const $=(id:string)=>document.getElementById(id)!;
 const compact=matchMedia('(max-width: 900px)');
 const parts=document.querySelector<HTMLElement>('main > aside')!;
 parts.id='model-parts';
 const nav=document.createElement('nav');nav.id='mobile-navigation';nav.setAttribute('aria-label','Workspace views');
 const panes=['model','parts','chat'] as const;
 type Pane=typeof panes[number];
 let pane:Pane='model';
 let activeCommit='';
 function revealCommit(){
  if(!compact.matches||pane!=='model')return;
  const current=$('history').querySelector<HTMLElement>('.current');
  if(current&&current.dataset.key!==activeCommit){activeCommit=current.dataset.key??'';current.scrollIntoView({block:'nearest',inline:'nearest'});}
 }
 function show(next:Pane){
  pane=next;document.body.dataset.mobilePane=next;
  for(const button of Array.from(nav.querySelectorAll('button')))button.setAttribute('aria-pressed',String(button.dataset.pane===next));
  if(next==='model'){activeCommit='';requestAnimationFrame(revealCommit);}
 }
 for(const name of panes){
  const button=document.createElement('button');button.type='button';button.dataset.pane=name;button.textContent=name[0].toUpperCase()+name.slice(1);button.setAttribute('aria-controls',name==='model'?'viewport':name==='parts'?'model-parts':'chat-panel');button.onclick=()=>show(name);nav.append(button);
 }
 document.body.append(nav);show('model');
 const chatButton=nav.querySelector<HTMLButtonElement>('[data-pane=chat]')!;
 const availability=()=>{chatButton.disabled=$('chat-panel').hidden;if(chatButton.disabled&&pane==='chat')show('model');};
 new MutationObserver(availability).observe($('chat-panel'),{attributes:true,attributeFilter:['hidden']});availability();
 new MutationObserver(revealCommit).observe($('history'),{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
 function ask(){if(compact.matches){show('chat');($('chat-input') as HTMLTextAreaElement).focus();}}
 $('ask-selection').addEventListener('click',ask);window.addEventListener('cad:draft',ask);
 $('files-drawer').addEventListener('click',event=>{const target=(event.target as HTMLElement).closest('.asset-card button');if(target?.textContent==='View'){($('files-drawer') as HTMLDialogElement).close();if(compact.matches)show('model');}});
 // Secondary actions stay reachable without filling a phone header with account controls.
 const account=document.createElement('div');account.id='mobile-account';
 for(const [id,label] of [['project-new','New project'],['logout','Sign out']]){
  const original=$(id);const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=()=>original.click();
  const sync=()=>{button.hidden=original.hidden;};sync();new MutationObserver(sync).observe(original,{attributes:true,attributeFilter:['hidden']});account.append(button);
 }
 $('files-drawer').append(account);
 function size(){
  const v=window.visualViewport;
  document.documentElement.style.setProperty('--mobile-height',`${v?.height??innerHeight}px`);
  document.documentElement.style.setProperty('--mobile-top',`${v?.offsetTop??0}px`);
 }
 window.visualViewport?.addEventListener('resize',size);window.visualViewport?.addEventListener('scroll',size);window.addEventListener('resize',size);
 compact.addEventListener('change',()=>{size();activeCommit='';revealCommit();});size();
}
