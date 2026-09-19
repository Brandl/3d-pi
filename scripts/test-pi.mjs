// Integration smoke test against the installed pi extension loader; no model/API key needed.
// Uses pi's internal loader only in this test, not in the application.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { resolve, join, dirname } from "node:path";
import { existsSync, realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
function findPi() {
  if (process.env.PI_PACKAGE_DIR) return process.env.PI_PACKAGE_DIR;
  const global = join(execFileSync("npm", ["root", "-g"], {encoding:"utf8"}).trim(), "@earendil-works/pi-coding-agent");
  if (existsSync(join(global, "dist/core/extensions/loader.js"))) return global;
  let path = dirname(realpathSync(execFileSync("which", ["pi"], {encoding:"utf8"}).trim()));
  while (dirname(path) !== path) {
    if (existsSync(join(path, "dist/core/extensions/loader.js"))) return path;
    path = dirname(path);
  }
  throw new Error("Cannot locate pi; set PI_PACKAGE_DIR to the installed pi package directory.");
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
assert.equal(tools.size, 11);
async function raw(name, params) {
  return tools
    .get(name)
    .definition.execute(randomUUID(), params, undefined, undefined, {});
}
async function call(name, params = {}) {
  return JSON.parse((await raw(name, params)).content[0].text);
}
const state = await call("cad_inspect");
const doc = await call("cad_example");
assert.equal((await call("cad_schema")).properties.units.const, "mm");
const candidate = await call("cad_build", {
  document_json: JSON.stringify(doc),
  expected_generation: state.generation,
});
assert.equal(candidate.result.report.valid, true);
assert.equal(
  (await call("cad_measure", { revision: candidate.revision })).parts.enclosure
    .x,
  80,
);
assert.equal(
  (await call("cad_validate", { revision: candidate.revision })).valid,
  true,
);
const image = await raw("cad_render", {
  revision: candidate.revision,
  view: "iso",
});
assert.equal(image.content[1].mimeType, "image/png");
assert.ok(image.content[1].data.length > 1000);
const published = await call("cad_publish", {
  revision: candidate.revision,
  expected_generation: state.generation,
});
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
await call("cad_restore", {
  revision: state.revision ?? candidate.revision,
  expected_generation: second.generation,
});
console.log(
  "Pi integration passed: 11 tools loaded; build, measure, validate, render, publish, parameter edit, four exports, restore.",
);
