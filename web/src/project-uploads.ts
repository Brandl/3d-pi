import {projectPath} from './project-path';
type Upload={id:string;filename:string;size:number;note:string;created:number;version:number};
export function initProjectUploads(drawer:HTMLDialogElement){
 const section=document.createElement('section');section.id='project-uploads';
 const heading=document.createElement('h3');heading.textContent='Project uploads';
 const hint=document.createElement('p');hint.className='hint';hint.textContent='Reference files for this project—not CAD revisions. Up to 10 MiB per file, 512 MiB / 500 files per project. Files are stored, not opened or executed.';
 const form=document.createElement('form');
 const label=document.createElement('label');label.textContent='File';
 const file=document.createElement('input');file.type='file';file.required=true;file.id='upload-file';label.append(file);
 const noteLabel=document.createElement('label');noteLabel.textContent='Note (optional)';
 const note=document.createElement('textarea');note.id='upload-note';note.maxLength=4000;note.rows=3;noteLabel.append(note);
 const submit=document.createElement('button');submit.type='submit';submit.textContent='Upload file';
 const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
 const list=document.createElement('div');list.id='upload-list';
 const refresh=document.createElement('button');refresh.type='button';refresh.textContent='Refresh uploads';
 form.append(label,noteLabel,submit);section.append(heading,hint,form,status,refresh,list);drawer.append(section);
 let busy=false;
 async function request(path:string,options?:RequestInit){
  if(options?.method && !['GET','HEAD'].includes(options.method)){
   const session=await fetch('/auth/session');if(!session.ok)throw Error('Please sign in again.');
   const headers=new Headers(options.headers);headers.set('X-CAD-CSRF',(await session.json()).csrf);options={...options,headers};
  }
  const r=await fetch(projectPath(path),options);
  if(!r.ok){let message=`Request failed (${r.status})`;try{const data=await r.json();if(typeof data.detail==='string')message=data.detail;}catch{/* retain status */}throw Error(message);}
  return r.status===204?null:r.json();
 }
 async function load(){
  try{
   const data=await request('/api/uploads');list.replaceChildren();
   if(!data.uploads.length){const p=document.createElement('p');p.textContent='No project uploads yet.';list.append(p);}
   for(const item of data.uploads as Upload[]){
    const card=document.createElement('article');card.className='upload-card';
    const link=document.createElement('a');link.href=projectPath(`/downloads/uploads/${item.id}/file`);link.textContent=item.filename;link.download=item.filename;
    const meta=document.createElement('small');meta.textContent=`${(item.size/1024).toFixed(1)} KiB · ${new Date(item.created*1000).toLocaleString()}`;
    const text=document.createElement('p');text.className='upload-note';text.textContent=item.note||'No note';
    const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Edit note';
    const edit=document.createElement('textarea');edit.value=item.note;edit.maxLength=4000;edit.rows=3;edit.setAttribute('aria-label',`Note for ${item.filename}`);
    const save=document.createElement('button');save.type='button';save.textContent='Save note';
    const feedback=document.createElement('p');feedback.setAttribute('role','status');
    save.onclick=async()=>{save.disabled=true;try{const updated=await request(`/api/uploads/${item.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:edit.value,version:item.version})});item.version=updated.version;item.note=updated.note;text.textContent=item.note||'No note';feedback.textContent='Note saved.';}catch(e){feedback.textContent=String(e);}finally{save.disabled=false;}};
    const remove=document.createElement('button');remove.type='button';remove.textContent='Delete upload';remove.onclick=async()=>{if(!confirm(`Delete uploaded file “${item.filename}”? This cannot be undone.`))return;remove.disabled=true;try{await request(`/api/uploads/${item.id}`,{method:'DELETE'});card.remove();status.textContent='Upload deleted.';}catch(e){feedback.textContent=String(e);remove.disabled=false;}};
    details.append(summary,edit,save);card.append(link,meta,text,details,remove,feedback);list.append(card);
   }
  }catch(e){status.textContent=String(e);}
 }
 form.onsubmit=async event=>{
  event.preventDefault();if(busy)return;const selected=file.files?.[0];if(!selected)return;
  if(selected.size>10*1024*1024){status.textContent='File exceeds 10 MiB.';return;}
  const body=new FormData();body.append('file',selected);body.append('note',note.value);
  busy=true;submit.disabled=true;file.disabled=true;note.disabled=true;status.textContent='Uploading…';
  try{await request('/api/uploads',{method:'POST',body});form.reset();status.textContent='File uploaded.';await load();}catch(e){status.textContent=String(e);}finally{busy=false;submit.disabled=false;file.disabled=false;note.disabled=false;}
 };
 refresh.onclick=()=>{void load();};
 // Reload on opening; never poll away unsaved note edits while the drawer is open.
 new MutationObserver(()=>{if(drawer.open)void load();}).observe(drawer,{attributes:true,attributeFilter:['open']});
}
