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
assert.equal(tools.size, 15);
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
assert.equal(
  (await call("cad_capabilities")).casting_box_limits_mm.top_clearance.max,
  60,
);
assert.equal((await call("cad_schema")).properties.units.const, "mm");
assert.equal(
  (await call("cad_schema", { section: "casting_box" })).section,
  "casting_box",
);
const candidate = await call("cad_build", {
  document_json: JSON.stringify(doc),
  expected_generation: state.generation,
});
assert.equal(candidate.result.report.valid, true);
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
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ data: "very long output ".repeat(10000) }), {
      headers: { "Content-Type": "application/json" },
    });
  const output = (await raw("cad_capabilities", {})).content[0].text;
  assert.equal(JSON.parse(output).truncated, true);
  assert.ok(Buffer.byteLength(output) <= 45000);
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
console.log(
  "Pi integration passed: 15 tools loaded; capabilities, tree, component inspection, idempotent build, measure, validate, render, publish, parameter edit, export discovery/four exports, history, cancel, restore.",
);
