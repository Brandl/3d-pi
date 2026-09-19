import {mkdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager} from '@earendil-works/pi-coding-agent';
import {ReadOnlyCredentialStore} from './credentials.mjs';
import {createBridge} from './server.mjs';

const cwd=process.env.PI_WORKSPACE ?? '/workspace';
const state=process.env.PI_STATE_DIR ?? '/agent-state';
const agentDir=join(state,'pi');
mkdirSync(agentDir,{recursive:true});
const provider=process.env.PI_PROVIDER ?? 'openai-codex';
const modelId=process.env.PI_MODEL ?? 'gpt-6-astra';
// Optional read-only credential bridge: use the host's existing access key, never
// refresh/rotate its OAuth tokens or expose the rest of its pi directory.
const seed=process.env.PI_SEED_AUTH_FILE;
const credentials=seed ? new ReadOnlyCredentialStore(seed,provider) : undefined;
const modelRuntime=await ModelRuntime.create({
  ...(credentials ? {credentials} : {authPath:join(agentDir,'auth.json')}),
  modelsStorePath:join(state,'models-store.json'),
});
async function refreshAuth() {
  if (!seed) return;
  if (!await credentials.read(provider)) throw new Error('Provider login is unavailable or expired');
}
await refreshAuth();
const model=modelRuntime.getModel(provider,modelId);
if (!model) throw new Error(`Configured model is not in the catalog: ${provider}/${modelId}`);
const settingsManager=SettingsManager.inMemory({defaultProjectTrust:'never',enableInstallTelemetry:false,
  compaction:{enabled:true},retry:{enabled:true,maxRetries:2}});
const loader=new DefaultResourceLoader({cwd,agentDir,settingsManager,
  noExtensions:true,noSkills:true,noPromptTemplates:true,noThemes:true,
  additionalExtensionPaths:[process.env.CAD_EXTENSION_PATH ?? '/opt/agent/cad.ts'],
  appendSystemPrompt:[
    'You are the private CAD workspace agent. The authenticated website user is the operator. Use cad_inspect before edits, cad_tree and cad_component_inspect to understand parts, feature dependencies and mating relationships, and cad_capabilities to check live service limits. Fetch editable source with cad_inspect view=document. Parameters are design-global and may affect multiple components. Build candidates, inspect cad_measure, cad_validate (including assembly/export sections) and rendered geometry, then publish only when verified. Build is not publication. Reuse request keys only with identical inputs; poll a pending revision instead of resubmitting. Tree interfaces are not separate solids or released library instances. The browser may be viewing historical geometry; a viewed revision is context, never automatic permission to restore it. Do not change geometry unless requested. Preserve current dimensions unless the user asks otherwise. Write parametric source changes in the workspace and commit verified milestones to its local Git repository. Never read or disclose credential files, provider tokens, login secrets or environment secrets unless the operator explicitly requests that exact secret. Do not edit runtime databases or immutable artifacts. The CAD engine is a separate service: editing local source does not hot-reload that service. Do not claim unsupported features or deployment changes have happened.'
  ]});
await loader.reload();
const errors=loader.getExtensions().errors;
if (errors.length) throw new Error('CAD extension failed to load');
const {session}=await createAgentSession({cwd,agentDir,modelRuntime,model,thinkingLevel:'medium',
  resourceLoader:loader,settingsManager,sessionManager:SessionManager.continueRecent(cwd,join(state,'sessions'))});
await session.bindExtensions({mode:'json'});
if (!['cad_inspect','cad_tree','cad_component_inspect','cad_capabilities','cad_cancel'].every(name=>session.getActiveToolNames().includes(name))) throw new Error('Refined CAD tools are not active');
const token=readFileSync(process.env.CAD_AGENT_TOKEN_FILE,'utf8').trim();
const bridge=createBridge({session,token,refreshAuth,journalPath:join(state,'requests.json')});
bridge.server.listen(Number(process.env.PI_WEB_PORT ?? 8768),'127.0.0.1',()=>console.log('Pi web bridge ready'));
let closing=false;
for (const signal of ['SIGINT','SIGTERM']) process.on(signal,async()=>{
  if (closing) return;closing=true;
  bridge.server.close();
  const timer=setTimeout(()=>process.exit(1),10000);timer.unref();
  await bridge.dispose();process.exit(0);
});
