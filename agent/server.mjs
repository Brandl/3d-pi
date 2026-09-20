import http from 'node:http';
import {createHash, timingSafeEqual} from 'node:crypto';
import {existsSync, readFileSync, writeFileSync, renameSync, appendFileSync} from 'node:fs';

export function visibleMessage(message) {
  if (!['user','assistant','toolResult'].includes(message.role)) return null;
  const content = typeof message.content === 'string' ? [{type:'text',text:message.content}] : message.content ?? [];
  const text = content.filter(c=>c.type==='text').map(c=>c.text).join('\n').slice(0,24000);
  const tools = content.filter(c=>c.type==='toolCall').map(c=>c.name);
  return {role:message.role,text,tools,tool:message.toolName,error:Boolean(message.isError),timestamp:message.timestamp};
}

export function createBridge({session, token, journalPath, transcriptPath, projectionPath, refreshAuth=async()=>{}}) {
  if (!token || token.length<32) throw new Error('Internal agent token is required');
  const digest = x=>createHash('sha256').update(x).digest();
  const secretDigest=digest('Bearer '+token);
  let jobs=existsSync(journalPath) ? JSON.parse(readFileSync(journalPath,'utf8')) : [];
  let busy=false, partial=null, error='', sequence=0, abortRequested=false;
  const activeTools=new Map();
  function persist() {
    jobs=jobs.slice(-200);
    writeFileSync(journalPath+'.tmp',JSON.stringify(jobs),{mode:0o600});
    renameSync(journalPath+'.tmp',journalPath);
    if(projectionPath){
      writeFileSync(projectionPath+'.tmp',JSON.stringify({...snapshot(),busy:false,partial:null,activeTools:[]}),{mode:0o600});
      renameSync(projectionPath+'.tmp',projectionPath);
    }
  }
  for (const job of jobs) if (job.status==='running') {
    job.status='interrupted';job.error='Agent restarted; inspect the model before resubmitting.';
  }
  persist();
  const unsubscribe=session.subscribe(event=>{
    sequence++;
    if (event.type==='message_update') partial=visibleMessage(event.message);
    if (event.type==='message_end') {
      partial=null;
      if(transcriptPath && visibleMessage(event.message)) {
        const message=event.message;
        const content=typeof message.content==='string'?[{type:'text',text:message.content}]:message.content??[];
        const text=content.filter(c=>c.type==='text').map(c=>c.text).join('\n');
        const tools=content.filter(c=>c.type==='toolCall').map(c=>c.name).join(', ');
        try {appendFileSync(transcriptPath,`\n\n## ${message.role}${message.toolName?' · '+message.toolName:''}\n\n${text}${tools?'\nTools: '+tools:''}\n`,{mode:0o600});}
        catch {error='Readable transcript could not be saved; inspect raw pi sessions.';}
      }
    }
    if (event.type==='tool_execution_start') activeTools.set(event.toolCallId,event.toolName);
    if (event.type==='tool_execution_end') activeTools.delete(event.toolCallId);
  });
  const reply=(res,code,data)=>{
    res.writeHead(code,{'Content-Type':'application/json','Cache-Control':'no-store'});
    res.end(JSON.stringify(data));
  };
  function snapshot() {
    const messages=session.messages.map(visibleMessage).filter(Boolean).slice(-100);
    let budget=240000;const recent=[];
    for(const message of messages.reverse()){
      if(budget<=0)break;
      message.text=message.text.slice(0,budget);budget-=message.text.length;recent.unshift(message);
    }
    return {sessionId:session.sessionId,model:session.model?`${session.model.provider}/${session.model.id}`:null,
      busy,sequence,messages:recent,partial,activeTools:[...activeTools.values()],error,job:jobs.at(-1)??null};
  }
  const server=http.createServer(async(req,res)=>{
    if (!timingSafeEqual(digest(req.headers.authorization ?? ''),secretDigest)) return reply(res,401,{detail:'Unauthorized'});
    try {
      if (req.method==='GET' && req.url==='/state') {
        return reply(res,200,snapshot());
      }
      if (req.method==='POST' && req.url==='/abort') {
        if (busy) {abortRequested=true;await session.abort();}
        return reply(res,200,{ok:true});
      }
      if (req.method!=='POST' || req.url!=='/prompt') return reply(res,404,{detail:'Not found'});
      let bytes=0;const chunks=[];
      for await (const chunk of req) {
        bytes+=chunk.length;
        if (bytes>32768) return reply(res,413,{detail:'Prompt too large'});
        chunks.push(chunk);
      }
      let input;
      try {input=JSON.parse(Buffer.concat(chunks).toString('utf8'));} catch {return reply(res,400,{detail:'Invalid JSON'});}
      if (typeof input?.text!=='string' || !input.text.trim() || input.text.length>16000 ||
          typeof input.request_key!=='string' || !/^[a-zA-Z0-9_-]{8,100}$/.test(input.request_key))
        return reply(res,422,{detail:'Expected text (1–16000 characters) and request_key'});
      const hash=digest(input.text).toString('hex');
      const previous=jobs.find(j=>j.id===input.request_key);
      if (previous) return reply(res,previous.hash===hash ? 200 : 409,
        previous.hash===hash ? {job:previous} : {detail:'Request key already used for another prompt'});
      if (busy) return reply(res,409,{detail:'Pi is working. Stop it or wait before sending another message.'});
      busy=true;error='';abortRequested=false;
      try {await refreshAuth();} catch {
        busy=false;return reply(res,503,{detail:'Provider login unavailable or expired. Renew the server-side pi login.'});
      }
      if(abortRequested){busy=false;return reply(res,409,{detail:'Prompt cancelled before starting'});}
      const job={id:input.request_key,hash,status:'running',created:Date.now()};
      jobs.push(job);
      try {persist();} catch {jobs.pop();busy=false;return reply(res,503,{detail:'Cannot persist the request; nothing was started'});}
      const deadline=setTimeout(()=>{abortRequested=true;void session.abort().catch(()=>{});},15*60*1000);
      deadline.unref();
      const initialCount=session.messages.length;
      void session.prompt(input.text,{expandPromptTemplates:false}).then(()=>{
        const last=session.messages.slice(initialCount).filter(m=>m.role==='assistant').at(-1);
        job.status=abortRequested || last?.stopReason==='aborted' ? 'aborted' : last?.stopReason==='error' ? 'failed' : 'complete';
        if (last?.errorMessage) error=String(last.errorMessage).slice(0,1000);
      }).catch(cause=>{
        console.error('Agent turn failed:',String(cause).replace(/Bearer\s+\S+|eyJ[A-Za-z0-9_.-]+/g,'[redacted]').slice(0,1000));
        job.status=abortRequested?'aborted':'failed';error=abortRequested?'Turn stopped. Inspect any changes already made.':'Agent turn failed. Inspect the model and retry if appropriate.';
      }).finally(()=>{
        clearTimeout(deadline);
        job.finished=Date.now();job.error=error;busy=false;partial=null;activeTools.clear();sequence++;
        try {persist();} catch {error='The turn ended, but its status could not be saved. Inspect the workspace.';}
      });
      return reply(res,202,{job});
    } catch {
      return reply(res,500,{detail:'Agent request failed'});
    }
  });
  server.requestTimeout=15000;
  server.headersTimeout=10000;
  return {server, dispose:async()=>{await session.abort();unsubscribe();session.dispose();}};
}
