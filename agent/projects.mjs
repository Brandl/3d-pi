import http from 'node:http';
import {spawn, execFileSync} from 'node:child_process';
import {once} from 'node:events';
import {pipeline} from 'node:stream/promises';
import {createHash, timingSafeEqual} from 'node:crypto';
import {mkdirSync, existsSync, readFileSync, writeFileSync, createReadStream, lstatSync, symlinkSync, renameSync} from 'node:fs';
import {join} from 'node:path';

const root=process.env.PI_PROJECTS_DIR ?? '/projects';
const origin=process.env.CAD_URL ?? 'http://127.0.0.1:8765';
const workerPort=Number(process.env.PI_WORKER_PORT??8769);
const workerOrigin=`http://127.0.0.1:${workerPort}`;
const token=readFileSync(process.env.CAD_AGENT_TOKEN_FILE,'utf8').trim();
if(token.length<32)throw new Error('Internal agent token is required');
const hash=s=>createHash('sha256').update(s).digest();
const secret=hash('Bearer '+token);
let worker=null, selected=null, tail=Promise.resolve(), closing=false;
const dead=child=>child.exitCode!==null || child.signalCode!==null;
const headers={Authorization:'Bearer '+token,'Content-Type':'application/json'};
const reply=(res,code,data)=>{res.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(data));};
async function catalog() {
 const r=await fetch(origin+'/api/projects',{signal:AbortSignal.timeout(10000)});
 if(!r.ok)throw new Error('Catalog unavailable');return (await r.json()).projects;
}
function folder(project) {
 if(typeof project.id!=='string'||!/^[a-z0-9][a-z0-9-]{0,63}$/.test(project.id))throw new Error('Invalid project ID');
 const path=join(root,project.id);
 mkdirSync(join(path,'source'),{recursive:true,mode:0o700});
 mkdirSync(join(path,'pi','sessions'),{recursive:true,mode:0o700});
 const metadataPath=join(path,'project.json');
 const previous=existsSync(metadataPath)?readFileSync(metadataPath,'utf8'):'';
 const metadata=JSON.stringify({...(previous?JSON.parse(previous):{}),schema_version:1,...project},null,2);
 if(metadata!==previous){writeFileSync(metadataPath+'.tmp',metadata,{mode:0o600});renameSync(metadataPath+'.tmp',metadataPath);}
 if(!lstatSync(join(path,'cad'),{throwIfNoEntry:false}))symlinkSync(project.legacy_root?'../../cad':`../../cad/projects/${project.id}/cad`,join(path,'cad'),'dir');
 const cwd=join(path,'source');
 if(!existsSync(join(cwd,'.git'))){
  execFileSync('git',['init','-b','main'],{cwd,stdio:'ignore'});
  execFileSync('git',['config','user.name','Pi CAD'],{cwd});
  execFileSync('git',['config','user.email','pi@localhost'],{cwd});
 }
 if(!existsSync(join(path,'pi','transcript.md')))writeFileSync(join(path,'pi','transcript.md'),'# Pi transcript\n\nProject-scoped messages from project creation onward. Raw session trees and image blocks are in `sessions/`.\n',{mode:0o600});
 return path;
}
async function childState() {
 const r=await fetch(workerOrigin+'/state',{headers,signal:AbortSignal.timeout(3000)});
 if(!r.ok)throw new Error('Worker unavailable');return r.json();
}
async function stop() {
 if(!worker)return;
 const old=worker;worker=null;selected=null;
 if(dead(old))return;
 const exited=once(old,'exit');old.kill('SIGTERM');
 const timer=setTimeout(()=>old.kill('SIGKILL'),11000);
 try{await exited;}finally{clearTimeout(timer);}
}
async function ensure(project) {
 if(worker && dead(worker)){worker=null;selected=null;}
 if(selected===project.id)return true;
 if(worker && (await childState()).busy)return false;
 await stop();
 const path=folder(project);
 worker=spawn(process.execPath,[process.env.PI_WORKER_PATH??'/opt/agent/main.mjs'],{stdio:'inherit',env:{...process.env,
  PI_WORKSPACE:join(path,'source'), PI_STATE_DIR:join(path,'pi'), PI_AUTH_DIR:'/agent-state/pi',
  PI_MODELS_STORE:'/agent-state/models-store.json', PI_WEB_PORT:String(workerPort), PI_PROJECT_ID:project.id,
  CAD_URL:origin+'/projects/'+project.id}});
 selected=project.id;
 for(let i=0;i<100;i++){
  if(dead(worker))throw new Error('Project worker failed to start');
  try{await childState();return true;}catch{await new Promise(r=>setTimeout(r,100));}
 }
 await stop();throw new Error('Project worker startup timed out');
}
const server=http.createServer(async(req,res)=>{
 if(!timingSafeEqual(hash(req.headers.authorization??''),secret))return reply(res,401,{detail:'Unauthorized'});
 let body;
 try{
  if(req.method==='POST'){
   const chunks=[];let size=0;
   for await(const chunk of req){size+=chunk.length;if(size>32768)return reply(res,413,{detail:'Request too large'});chunks.push(chunk);}
   body=Buffer.concat(chunks);
  }
  const route=new URL(req.url,'http://localhost').pathname;
  if(req.method==='GET'&&route==='/health')return reply(res,200,{ok:!closing});
  const run=async()=>{
   if(closing)return reply(res,503,{detail:'Agent shutting down'});
   if(route==='/projects' && ['GET','POST'].includes(req.method)){
    if(req.method==='POST'){
     const r=await fetch(origin+'/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body,signal:AbortSignal.timeout(10000)});
     const data=await r.json();if(r.ok)folder(data);return reply(res,r.status,data);
    }
    const projects=await catalog();projects.forEach(folder);return reply(res,200,{projects});
   }
   const match=route.match(/^\/projects\/([a-z0-9][a-z0-9-]{0,63})\/(state|prompt|abort|transcript)$/);
   const operation=match?.[2] ?? route.slice(1);
   const id=match?.[1] ?? 'dripper';
   if(!['state','prompt','abort','transcript'].includes(operation) || !match && !['/state','/prompt','/abort','/transcript'].includes(route))return reply(res,404,{detail:'Not found'});
   if(!((req.method==='GET'&&['state','transcript'].includes(operation))||(req.method==='POST'&&['prompt','abort'].includes(operation))))return reply(res,405,{detail:'Method not allowed'});
   const project=(await catalog()).find(p=>p.id===id);if(!project)return reply(res,404,{detail:'Unknown project'});
   const path=folder(project);
   if(operation==='transcript'){
    res.setTimeout(30000,()=>res.destroy());
    res.writeHead(200,{'Content-Type':'text/plain; charset=utf-8','Content-Disposition':'attachment; filename="pi-transcript.md"','Cache-Control':'no-store'});
    for(const file of [join(path,'pi','legacy-shared','transcript.md'),join(path,'pi','transcript.md')]){
     if(!existsSync(file))continue;
     await pipeline(createReadStream(file),res,{end:false});
    }
    res.end();return;
   }
   if(operation==='state' && (!worker || dead(worker) || selected!==id)){
    const cached=join(path,'pi','web-state.json');
    const state=existsSync(cached)?JSON.parse(readFileSync(cached,'utf8')):{sessionId:null,model:`${process.env.PI_PROVIDER??'openai-codex'}/${process.env.PI_MODEL??'gpt-6-astra'}`,busy:false,sequence:0,messages:[],partial:null,activeTools:[],error:'',job:null};
    if(state.job?.status==='running'){state.job.status='interrupted';state.error='Previous turn interrupted; inspect the design before retrying.';}
    return reply(res,200,state);
   }
   if(operation==='abort' && selected!==id)return reply(res,409,{detail:'No active turn in this project'});
   if(!await ensure(project))return reply(res,409,{detail:`Pi is working in project ${selected}. Return there to stop it, or wait.`});
   const r=await fetch(workerOrigin+'/'+operation,{method:req.method,headers,body,signal:AbortSignal.timeout(12000)});
   reply(res,r.status,await r.json());
  };
  const pending=tail.then(run);tail=pending.catch(()=>{});await pending;
 }catch{if(!res.headersSent)reply(res,503,{detail:'Project agent unavailable; inspect service status before retrying'});else res.destroy();}
});
server.requestTimeout=15000;server.headersTimeout=10000;
server.listen(Number(process.env.PI_ROUTER_PORT??8768),'127.0.0.1',()=>console.log('Project agent router ready'));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,async()=>{if(closing)return;closing=true;server.close();await tail;await stop();process.exit(0);});
