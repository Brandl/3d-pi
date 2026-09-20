import {projectId, projectPath} from './project-path';
const select=document.getElementById('project-select') as HTMLSelectElement;
const status=document.getElementById('project-status')!;
function navigate(id:string) {
  const draft=(document.getElementById('chat-input') as HTMLTextAreaElement).value.trim();
  const working=!(document.getElementById('chat-stop') as HTMLButtonElement).disabled;
  if(working){status.textContent='Wait for pi to finish before switching.';select.value=projectId??'dripper';return;}
  if(draft&&!confirm('Switch projects and discard the unsent chat draft?')){select.value=projectId??'dripper';return;}
  location.assign('/?project='+encodeURIComponent(id));
}
select.addEventListener('change',()=>navigate(select.value));
(document.getElementById('project-transcript') as HTMLAnchorElement).href=projectPath('/api/agent/transcript');
const createButton=document.getElementById('project-new') as HTMLButtonElement;
createButton.addEventListener('click',async()=>{
  if(!(document.getElementById('chat-stop') as HTMLButtonElement).disabled){status.textContent='Wait for pi to finish before creating a project.';return;}
  const name=prompt('New project name (up to 80 characters)')?.trim();if(!name)return;
  createButton.disabled=true;
  try{
    const auth=await fetch('/auth/session');if(!auth.ok)throw new Error('Please sign in');
    const response=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json','X-CAD-CSRF':(await auth.json()).csrf},body:JSON.stringify({name})});
    if(!response.ok)throw new Error(`Project creation failed (${response.status})`);
    navigate((await response.json()).id);
  }catch(error){status.textContent=String(error);}finally{createButton.disabled=false;}
});
async function init(){
 const response=await fetch('/api/projects');if(!response.ok)return;
 const data=await response.json();select.replaceChildren();
 for(const project of data.projects){const option=document.createElement('option');option.value=project.id;option.textContent=project.name;select.append(option);}
 select.value=projectId??'dripper';select.disabled=false;
 if(!select.value)status.textContent='Unknown project';
}
void init().catch(error=>{status.textContent=String(error);});
