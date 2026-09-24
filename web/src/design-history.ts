import {projectPath} from './project-path';
export type DesignCommit={id:string;generation:number;revision:string;name:string;icon:string;created:number;source_commit:string;source_file:string};
type Asset={id:string;commit_id:string;revision:string;role:string;name:string;note:string};
export type Workspace={commit_id:string|null;generation:number;revision:string|null;commits:DesignCommit[];assets:Asset[]};
type Entry={key:string;revision:string;name:string;icon:string;detail:string;commit?:string};
type State={revision:string|null;generation:number;candidates?:string[];candidate_names?:Record<string,string>;publications?:{generation:number;revision:string;name?:string|null;operation:string}[];workspace?:Workspace|null};
const $=(id:string)=>document.getElementById(id)!;
export function createHistory(changed:()=>void){
 let entries:Entry[]=[],index=-1,key='',assetsKey='',assetEpoch=0;
 let params=new URL(location.href).searchParams;
 let commit=params.get('commit'),version=params.get('version'),candidate=params.get('candidate');
 const restore=document.createElement('button');restore.id='timeline-restore';restore.textContent='Ask π to restore';restore.hidden=true;$('timeline-working').before(restore);
 const choose=(entry:Entry|null,revision?:string)=>{
  commit=entry?.commit??null;version=entry&&!entry.commit?entry.key.slice(2):null;candidate=revision??null;
  const url=new URL(location.href);for(const n of ['commit','version','candidate'])url.searchParams.delete(n);
  if(commit)url.searchParams.set('commit',commit);if(version)url.searchParams.set('version',version);if(candidate)url.searchParams.set('candidate',candidate);
  history.replaceState(null,'',url);changed();
 };
 $('timeline-previous').onclick=()=>{if(index>0)choose(entries[index-1]);};
 $('timeline-next').onclick=()=>{if(index<entries.length-1)choose(entries[index+1]);};
 $('timeline-latest').onclick=$('timeline-working').onclick=()=>choose(null);
 $('timeline-position').oninput=e=>{const entry=entries[Number((e.target as HTMLInputElement).value)];if(entry)choose(entry);};
 $('draft-select').onchange=e=>choose(null,(e.target as HTMLSelectElement).value||undefined);
 window.addEventListener('cad:view',e=>choose(null,(e as CustomEvent).detail.revision??undefined));
 window.addEventListener('popstate',()=>{params=new URL(location.href).searchParams;commit=params.get('commit');version=params.get('version');candidate=params.get('candidate');changed();});
 async function files(assets:Asset[],owner:string){
  const next=JSON.stringify([owner,assets]);if(next===assetsKey)return;assetsKey=next;const epoch=++assetEpoch;
  const target=$('related-files');target.replaceChildren();
  if(!assets.length){const p=document.createElement('p');p.className='hint';p.textContent='No named print files attached. Viewed geometry and other builds are below.';target.append(p);return;}
  for(const asset of assets.filter(a=>a.role!=='inspection')){
   const card=document.createElement('article');card.className='asset-card';const role=document.createElement('span');role.className='asset-role';role.textContent=asset.role==='test'?'Test fixture':'Print files';const h=document.createElement('h3');h.textContent=asset.name;const p=document.createElement('p');p.textContent=asset.note;const view=document.createElement('button');view.textContent='View';view.onclick=()=>choose(null,asset.revision);const links=document.createElement('div');links.className='exports';links.textContent='Loading files…';card.append(role,h);if(asset.note.length>300){const instructions=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Printing and assembly instructions';instructions.append(summary,p);card.append(instructions);}else card.append(p);card.append(view,links);target.append(card);
   try{const r=await fetch(projectPath(`/api/revisions/${asset.revision}`));if(!r.ok)throw Error('unavailable');const row=await r.json();if(epoch!==assetEpoch)return;links.replaceChildren();for(const [format,filename] of Object.entries(row.result.exports) as [string,string][]){const a=document.createElement('a');a.href=projectPath(`/downloads/sets/${asset.id}/${encodeURIComponent(format)}`);a.textContent=format.toUpperCase().replaceAll('_',' ');a.download=`${asset.name.replace(/[^A-Za-z0-9_-]+/g,'-')}-${format.replace(':','-')}.${filename.split('.').pop()}`;links.append(a);}if(asset.note){const notes=document.createElement('a');notes.href=projectPath(`/downloads/sets/${asset.id}/instructions.txt`);notes.textContent='Instructions';notes.download='instructions.txt';links.append(notes);}}catch{if(epoch===assetEpoch){links.textContent='Files unavailable; retrying.';assetsKey='';}}
  }
 }
 return (state:State)=>{
  const workspace=state.workspace;
  const working=workspace?.revision??state.revision;
  const legacy=(state.publications??[]).slice().sort((a,b)=>a.generation-b.generation).map(p=>({key:'p:'+p.generation,revision:p.revision,name:p.name??`Version ${p.generation}`,icon:'◷',detail:`Legacy ${p.operation} · v${p.generation} · ${p.revision}`}));
  entries=[...legacy,...(workspace?.commits??[]).map(c=>({key:'c:'+c.id,revision:c.revision,name:c.name,icon:c.icon,detail:`${c.name}\nGit ${c.source_commit}\n${c.source_file}\nCAD ${c.revision}`,commit:c.id}))];
  let selected=commit?entries.find(e=>e.commit===commit):version?entries.find(e=>e.key==='p:'+version):undefined;
  const asset=workspace?.assets.find(a=>a.revision===candidate);
  if(asset)selected=entries.find(e=>e.commit===asset.commit_id);
  const allowed=new Set([...(state.candidates??[]),...entries.map(e=>e.revision),...(workspace?.assets??[]).map(a=>a.revision)]);
  const invalid=Boolean(candidate&&!allowed.has(candidate)||commit&&!selected||version&&!selected);
  const viewed=!invalid&&candidate?candidate:selected?.revision??working;
  restore.hidden=!selected||viewed!==selected.revision||viewed===working;
  restore.onclick=()=>window.dispatchEvent(new CustomEvent('cad:draft',{detail:{text:`Restore design revision ${selected?.revision} (${selected?.name}) as a NEW working-design commit, preserving history. Inspect its source and the current working design first; restore corresponding project source, verify geometry, and commit with a short name and Unicode icon. Do not publish.`}}));
  const owner=selected?.commit??workspace?.commit_id??'';
  const related=workspace?.assets.filter(a=>a.commit_id===owner)??[];
  index=selected?entries.indexOf(selected):entries.map(e=>e.revision).lastIndexOf(working??'');
  const listKey=JSON.stringify(entries);
  if(key!==listKey){key=listKey;$('history').replaceChildren();for(const entry of entries){const li=document.createElement('li');li.dataset.key=entry.key;const button=document.createElement('button');button.type='button';button.title=entry.detail;button.setAttribute('aria-label',entry.name);const icon=document.createElement('span');icon.className='commit-icon';icon.textContent=entry.icon;const label=document.createElement('span');label.className='commit-label';label.textContent=entry.name;const thumb=document.createElement('img');thumb.className='revision-thumb';thumb.alt='';thumb.loading='lazy';thumb.decoding='async';thumb.src=projectPath(`/api/revisions/${entry.revision}/artifacts/review-iso.png`);let fallback=false;thumb.onerror=()=>{if(!fallback){fallback=true;thumb.src=projectPath(`/api/revisions/${entry.revision}/artifacts/render-iso.png`);}else{thumb.hidden=true;button.classList.add('thumb-unavailable');}};button.append(thumb,icon,label);button.onclick=()=>choose(entry);li.append(button);$('history').append(li);}}
  Array.from($('history').children).forEach((li,i)=>{li.classList.toggle('current',i===index);li.querySelector('button')!.setAttribute('aria-pressed',String(i===index));});
  const pos=$('timeline-position') as HTMLInputElement;pos.max=String(Math.max(0,entries.length-1));pos.value=String(Math.max(0,index));pos.disabled=entries.length<2;
  ($('timeline-previous') as HTMLButtonElement).disabled=index<=0;($('timeline-next') as HTMLButtonElement).disabled=index<0||index>=entries.length-1;
  ($('timeline-latest') as HTMLButtonElement).disabled=!candidate&&!commit&&!version;
  $('timeline-status').textContent=invalid?'Requested view unavailable · working design unchanged':asset?`${asset.name} · ${asset.role==='inspection'?'inspection':'output'} · working design unchanged`:candidate&&candidate!==working?'Build preview · not the working design':selected?`${selected.name} · browsing only` :working?'Working design':'No working design · ask π to commit a model';
  const viewport=$('viewport');viewport.dataset.workingRevision=working??'';viewport.dataset.workspaceGeneration=String(workspace?.generation??0);viewport.dataset.designCommit=workspace?.commit_id??'';
  const select=$('draft-select') as HTMLSelectElement;select.replaceChildren(new Option('Working design',''));for(const id of state.candidates??[]){select.add(new Option(state.candidate_names?.[id]??id.slice(0,8),id));}select.value=candidate??'';
  const views=$('representation') as HTMLSelectElement;const assembly=selected?.revision??working;views.replaceChildren(new Option('Assembly',assembly??''));for(const a of related.filter(a=>a.role==='inspection'))views.add(new Option(a.name,a.revision));if(viewed&&!Array.from(views.options).some(o=>o.value===viewed))views.add(new Option(asset?.name??'Build preview',viewed));views.value=viewed??'';views.disabled=!viewed;
  void files(related,owner);
  return viewed??null;
 };
}
