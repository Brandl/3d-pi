// Integration smoke test against the installed pi extension loader; no model/API key needed.
// Uses pi's internal loader only in this test, not in the application.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve, join, dirname } from "node:path";
import { existsSync, realpathSync, mkdtempSync, writeFileSync, readFileSync, statSync, rmSync } from "node:fs";
import {tmpdir} from 'node:os';
import { pathToFileURL } from "node:url";
function findPi() {
  if (process.env.PI_PACKAGE_DIR) return process.env.PI_PACKAGE_DIR;
  const global = join(
    execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim(),
    "@earendil-works/pi-coding-agent",
  );
  if (existsSync(join(global, "dist/core/extensions/loader.js"))) return global;
  let path = dirname(
    realpathSync(execFileSync("which", ["pi"], { encoding: "utf8" }).trim()),
  );
  while (dirname(path) !== path) {
    if (existsSync(join(path, "dist/core/extensions/loader.js"))) return path;
    path = dirname(path);
  }
  throw new Error(
    "Cannot locate pi; set PI_PACKAGE_DIR to the installed pi package directory.",
  );
}
const root = findPi();
const { loadExtensions } = await import(
  pathToFileURL(join(root, "dist/core/extensions/loader.js")).href
);
const loaded = await loadExtensions(
  [resolve(".pi/extensions/cad.ts")],
  process.cwd(),
);
assert.deepEqual(loaded.errors, []);
const tools = loaded.extensions[0].tools;
assert.equal(tools.size, 17);
let toolCwd=process.cwd();
async function raw(name, params) {
  return tools
    .get(name)
    .definition.execute(randomUUID(), params, undefined, undefined, {cwd:toolCwd});
}
async function call(name, params = {}) {
  return JSON.parse((await raw(name, params)).content[0].text);
}
const state = await call("cad_inspect");
const doc = await call("cad_example");
assert.equal(
  (await call("cad_capabilities")).casting_box_limits_mm.top_clearance.max,
  60,
);
assert.equal((await call("cad_schema")).properties.units.const, "mm");
assert.equal(
  (await call("cad_schema", { section: "casting_box" })).section,
  "casting_box",
);
const built = await raw("cad_build", {
  document_json: JSON.stringify(doc),
  expected_generation: state.generation,
});
const candidate = JSON.parse(built.content[0].text);
assert.equal(candidate.result.report.valid, true);
assert.equal(built.content.filter((item) => item.type === "image").length, 3);
assert.equal(built.details.visual_review.complete, true);
assert.equal(
  (await raw("cad_inspect", { revision: candidate.revision })).content.filter(
    (item) => item.type === "image",
  ).length,
  0,
);
assert.equal(
  (
    await call("cad_build", {
      document_json: JSON.stringify(doc),
      expected_generation: state.generation,
      request_key: candidate.request_key,
    })
  ).revision,
  candidate.revision,
);
for (const handler of loaded.extensions[0].handlers.get("session_compact") ??
  [])
  await handler({ type: "session_compact" }, {});
assert.equal(
  (await raw("cad_inspect", { revision: candidate.revision })).content.filter(
    (item) => item.type === "image",
  ).length,
  3,
);
const tree = await call("cad_tree", { revision: candidate.revision });
assert.equal(tree.root.id, "assembly");
const part = await call("cad_component_inspect", {
  revision: candidate.revision,
  component_id: "part:enclosure",
});
assert.ok(part.parameters.wall);
assert.equal(
  (await call("cad_cancel", { revision: candidate.revision })).cancelled_now,
  false,
);
assert.ok(
  (await call("cad_export", { revision: candidate.revision })).exports.stl,
);
assert.equal(
  (
    await call("cad_inspect", {
      revision: candidate.revision,
      view: "document",
    })
  ).document.name,
  doc.name,
);
assert.equal(
  (await call("cad_measure", { revision: candidate.revision })).parts.enclosure
    .x,
  80,
);
assert.equal(
  (await call("cad_validate", { revision: candidate.revision })).valid,
  true,
);
assert.equal(
  (
    await call("cad_validate", {
      revision: candidate.revision,
      section: "assembly",
    })
  ).results,
  null,
);
await assert.rejects(
  () =>
    call("cad_measure", { revision: candidate.revision, part: "not_a_part" }),
  /Unknown output part/,
);
const image = await raw("cad_render", {
  revision: candidate.revision,
  view: "iso",
});
assert.equal(image.content[1].mimeType, "image/png");
assert.ok(image.content[1].data.length > 1000);
const fresh = await loadExtensions(
  [resolve(".pi/extensions/cad.ts")],
  process.cwd(),
);
assert.deepEqual(fresh.errors, []);
const publishTool = fresh.extensions[0].tools.get("cad_publish").definition;
const checkpoint = await publishTool.execute(
  randomUUID(),
  { revision: candidate.revision, expected_generation: state.generation },
  undefined,
  undefined,
  {},
);
assert.equal(
  JSON.parse(checkpoint.content[0].text).status,
  "visual_review_required",
);
assert.equal(
  checkpoint.content.filter((item) => item.type === "image").length,
  3,
);
assert.equal((await call("cad_inspect")).generation, state.generation);
const published = await call("cad_publish", {
  revision: candidate.revision,
  expected_generation: state.generation,
});
const confirmed = await publishTool.execute(
  randomUUID(),
  { revision: candidate.revision, expected_generation: state.generation },
  undefined,
  undefined,
  {},
);
assert.equal(
  JSON.parse(confirmed.content[0].text).generation,
  published.generation,
);
const changed = await call("cad_parameters", {
  changes_json: '{"wall":3,"hole_offset":10}',
  expected_generation: published.generation,
});
assert.equal(changed.result.report.parameters.wall, 3);
const second = await call("cad_publish", {
  revision: changed.revision,
  expected_generation: published.generation,
});
for (const format of ["step", "stl", "3mf", "dxf"]) {
  const artifact = await call("cad_export", {
    revision: changed.revision,
    format,
    ...(format === "dxf" ? { section: "lid_profile" } : {}),
  });
  assert.equal((await fetch(artifact.url)).status, 200);
}
const pending = await call("cad_build", {
  document_json: JSON.stringify(doc),
  expected_generation: second.generation,
  wait: false,
});
assert.equal(
  (await call("cad_cancel", { revision: pending.revision })).status,
  "cancelled",
);
const history = await call("cad_inspect", { view: "history", limit: 1 });
assert.equal(history.items.length, 1);
assert.equal(history.next_offset, 1);
await call("cad_restore", {
  revision: state.revision ?? candidate.revision,
  expected_generation: second.generation,
});
const originalFetch = globalThis.fetch;
try {
  const hugeWorkspace = {revision: candidate.revision, generation:19, commit_id:'c19',
    commits: Array.from({length:19}, (_,i)=>({id:`c${i+1}`,name:`S${i+1}`})),
    assets:Array.from({length:150}, (_,i)=>({id:i.toString(16).padStart(32,'0'),commit_id:'c19',name:`Asset ${i}`,role:'print',note:'Instructions '.repeat(1000)}))};
  globalThis.fetch = async (url, options) => String(url).endsWith('/api/state')
    ? new Response(JSON.stringify({...state, workspace:hugeWorkspace}), {headers:{'Content-Type':'application/json'}})
    : originalFetch(url, options);
  const compact = await call('cad_inspect');
  assert.equal(compact.truncated,undefined);
  assert.equal(compact.current.revision,candidate.revision);
  assert.equal(compact.workspace.asset_count,150);
  assert.equal((await call('cad_inspect',{view:'document'})).document.name,doc.name);
  const assets=await call('cad_inspect',{view:'history',history_kind:'assets',limit:5});
  assert.equal(assets.items.length,5);assert.equal(assets.items[0].note,undefined);
  const attachment=await call('cad_inspect',{view:'asset',asset_id:assets.items[0].id});
  assert.equal(attachment.asset.note,'Instructions '.repeat(1000));
  await assert.rejects(()=>call('cad_inspect',{view:'asset'}),/requires asset_id/);
  globalThis.fetch=originalFetch;
  const unchecked=await call('cad_validate',{revision:candidate.revision,section:'exports'});
  assert.equal(unchecked.status,'not_checked');assert.equal(unchecked.valid,null);
  assert.equal(unchecked.geometry_valid,true);
  globalThis.fetch = async (url, options) =>
    String(url).includes("/artifacts/review-")
      ? new Response("missing", { status: 404 })
      : originalFetch(url, options);
  const legacyReview = await raw("cad_render", {
    revision: candidate.revision,
  });
  assert.equal(
    legacyReview.content.filter((item) => item.type === "image").length,
    3,
  );
  assert.ok(
    legacyReview.content.some(
      (item) =>
        item.type === "text" && item.text.includes("Standard render fallback"),
    ),
  );
  globalThis.fetch = async () => new Response("unavailable", { status: 503 });
  const missing = await raw("cad_render", { revision: candidate.revision });
  assert.equal(missing.details.complete, false);
  assert.equal(
    missing.content.filter((item) => item.type === "image").length,
    0,
  );
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ data: "very long output ".repeat(10000) }), {
      headers: { "Content-Type": "application/json" },
    });
  const output = (await raw("cad_capabilities", {})).content[0].text;
  assert.equal(JSON.parse(output).truncated, true);
  assert.ok(Buffer.byteLength(output) <= 45000);
  const fullOutput = JSON.parse(output).full_output_path;
  assert.equal(statSync(fullOutput).mode & 0o777, 0o600);
  assert.equal(JSON.parse(readFileSync(fullOutput, 'utf8')).data.length, 'very long output '.repeat(10000).length);
  rmSync(dirname(fullOutput), {recursive:true, force:true});
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: "Runtime constraint rejected" }), {
      status: 422,
    });
  await assert.rejects(
    () =>
      raw("cad_build", {
        document_json: JSON.stringify(doc),
        expected_generation: 0,
      }),
    (error) => JSON.parse(error.message).submission === "Rejected by service",
  );
} finally {
  globalThis.fetch = originalFetch;
}
const originalCwd=process.cwd();
const gitRepo=mkdtempSync(join(tmpdir(),'cad-commit-test-'));
try {
  process.chdir(gitRepo);
  execFileSync('git',['init','-q']);
  execFileSync('git',['config','user.email','test@example.invalid']);execFileSync('git',['config','user.name','Test']);
  writeFileSync('document.json',JSON.stringify(doc));execFileSync('git',['add','document.json']);execFileSync('git',['commit','-qm','Source snapshot']);
  toolCwd=gitRepo;
  process.chdir(originalCwd); // SDK session cwd must work independently of process cwd.
  const before=await call('cad_inspect');
  const input={revision:candidate.revision,base_revision:before.revision,expected_generation:before.workspace.generation,name:'Create enclosure',icon:'📦',source_file:'document.json',request_key:randomUUID()};
  const committed=await call('cad_commit',input);
  assert.equal(committed.name,'Create enclosure');assert.equal(committed.icon,'📦');
  assert.equal((await call('cad_commit',input)).id,committed.id);
  const asset=await call('cad_attach',{commit:committed.id,revision:changed.revision,role:'test',name:'Test variant',request_key:randomUUID()});
  assert.equal(asset.role,'test');
  const after=await call('cad_inspect');assert.equal(after.workspace.revision,candidate.revision);assert.equal(after.generation,before.generation);assert.equal(after.workspace.commit_count,1);
  assert.equal(after.workspace.current_commit.id,committed.id);
  writeFileSync(join(gitRepo,'document.json'),JSON.stringify({...doc,name:'Dirty source'}));
  await assert.rejects(()=>call('cad_commit',{...input,request_key:randomUUID()}),/Commit tracked source/);
} finally {toolCwd=originalCwd;process.chdir(originalCwd);rmSync(gitRepo,{recursive:true,force:true});}
console.log(
  "Pi integration passed: 17 tools loaded; design commits with Git/source verification, named emoji metadata, output attachments and dirty-source rejection; capabilities, tree, component inspection, idempotent build, measure, validate, render, publish, parameter edit, export discovery/four exports, history, cancel, restore; automatic image checkpoints, compaction reset, pre-publication review, legacy fallback and missing-image handling.",
);
