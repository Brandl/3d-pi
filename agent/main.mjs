import {mkdirSync, readFileSync} from 'node:fs';
import {join} from 'node:path';
import {createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager} from '@earendil-works/pi-coding-agent';
import {ReadOnlyCredentialStore} from './credentials.mjs';
import {createBridge} from './server.mjs';

const cwd=process.env.PI_WORKSPACE ?? '/workspace';
const state=process.env.PI_STATE_DIR ?? '/agent-state';
const agentDir=process.env.PI_AUTH_DIR ?? join(state,'pi');
mkdirSync(agentDir,{recursive:true});
const provider=process.env.PI_PROVIDER ?? 'openai-codex';
const modelId=process.env.PI_MODEL ?? 'gpt-6-astra';
// Optional read-only credential bridge: use the host's existing access key, never
// refresh/rotate its OAuth tokens or expose the rest of its pi directory.
const seed=process.env.PI_SEED_AUTH_FILE;
const credentials=seed ? new ReadOnlyCredentialStore(seed,provider) : undefined;
const modelRuntime=await ModelRuntime.create({
  ...(credentials ? {credentials} : {authPath:join(agentDir,'auth.json')}),
  modelsStorePath:process.env.PI_MODELS_STORE ?? join(state,'models-store.json'),
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
    `Current project: ${process.env.PI_PROJECT_ID ?? 'dripper'}. Source cwd: ${cwd}. CAD_URL is project-scoped: ${process.env.CAD_URL}. Never drop its project prefix, operate on a sibling project, or infer publication permission from switching projects. Source Git belongs to this project; credentials and pi transcripts live outside its source repository. Read README/document.json if present for migrated design context. Old shared transcripts are archived, not the new session context. Imported candidates may have an old base_generation; rebuild the same source against this project's current generation before publishing.`,

    'Work with the operator in the shared model, not a staged review workflow. Use the explicit workspace working revision as the edit base, not the latest build or currently viewed output. After a requested design change is built, inspected and verified, commit its source JSON to project Git and call cad_commit with a concise action name and Unicode emoji/icon, the original workspace generation and base revision. Every actual design commit requires both name and icon. Do not commit inspection views, renders, exports or fixtures as design changes: register those with cad_attach against the design commit. New projects need an explicit first design commit. Publication is a separate legacy operation and requires explicit permission. Keep responses concise; mention concrete changes and unresolved checks rather than generic workflow narration.',
    'You are the private CAD workspace agent. The authenticated website user is the operator. Use cad_inspect before edits, cad_tree and cad_component_inspect to understand parts, feature dependencies and mating relationships, and cad_capabilities to check live service limits. Fetch editable source with cad_inspect view=document. Parameters are design-global and may affect multiple components. Build candidates and examine the automatically attached visual checkpoints: isometric, top, front and optional exploded images. Describe relevant visual findings and check the requested change across views; do not substitute labels or report values for looking at the images. These are preview images, not hidden-line drawings. Use cad_section for full material sections through immutable STEP geometry, with axis, offset, tilt and optional part selection; it preserves holes and returns a section image plus exact areas and DXF/JSON downloads without modifying the design. Cross-check cad_measure and cad_validate (including assembly/export sections), then commit verified requested design changes; publish only when explicitly authorized. If publish/restore returns visual_review_required, no mutation happened: inspect the images before explicitly retrying. Missing images require cad_render retry. After compaction or uncertainty, request cad_render again rather than assuming old images remain in context. Build is not publication. Reuse request keys only with identical inputs; poll a pending revision instead of resubmitting. Tree interfaces are not separate solids or released library instances. The browser may be viewing historical geometry; a viewed revision is context, never automatic permission to restore it. Do not change geometry unless requested. Preserve current dimensions unless the user asks otherwise. Write parametric source changes in the workspace and commit verified milestones to its local Git repository. Never read or disclose credential files, provider tokens, login secrets or environment secrets unless the operator explicitly requests that exact secret. Do not edit runtime databases or immutable artifacts. The CAD engine is a separate service: editing local source does not hot-reload that service. Do not claim unsupported features or deployment changes have happened.'
  ]});
await loader.reload();
const errors=loader.getExtensions().errors;
if (errors.length) throw new Error('CAD extension failed to load');
const {session}=await createAgentSession({cwd,agentDir,modelRuntime,model,thinkingLevel:'medium',
  resourceLoader:loader,settingsManager,sessionManager:SessionManager.continueRecent(cwd,join(state,'sessions'))});
await session.bindExtensions({mode:'json'});
if (!['cad_inspect','cad_tree','cad_component_inspect','cad_capabilities','cad_cancel','cad_section'].every(name=>session.getActiveToolNames().includes(name))) throw new Error('Refined CAD tools are not active');
const token=readFileSync(process.env.CAD_AGENT_TOKEN_FILE,'utf8').trim();
const bridge=createBridge({session,token,refreshAuth,journalPath:join(state,'requests.json'),transcriptPath:join(state,'transcript.md'),projectionPath:join(state,'web-state.json')});
bridge.server.listen(Number(process.env.PI_WEB_PORT ?? 8768),'127.0.0.1',()=>console.log('Pi web bridge ready'));
let closing=false;
for (const signal of ['SIGINT','SIGTERM']) process.on(signal,async()=>{
  if (closing) return;closing=true;
  bridge.server.close();
  const timer=setTimeout(()=>process.exit(1),10000);timer.unref();
  await bridge.dispose();process.exit(0);
});
