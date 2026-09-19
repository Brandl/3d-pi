import { createHash } from "node:crypto";
import { Type, type Static, type TSchema } from "typebox";
import { StringEnum } from "@earendil-works/pi-ai";
import {
  truncateHead,
  type ExtensionAPI,
} from "@earendil-works/pi-coding-agent";

const endpoint = (process.env.CAD_URL ?? "http://127.0.0.1:8765").replace(
  /\/$/,
  "",
);
const parsed = new URL(endpoint);
if (
  parsed.protocol !== "http:" ||
  !["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname)
)
  throw new Error(
    "CAD_URL must be loopback HTTP; never expose the modeling API publicly.",
  );
const revision = Type.String({
  pattern: "^[a-f0-9]{32}$",
  description: "Exact immutable revision ID, not a generation or part ID",
});
const generation = Type.Integer({
  minimum: 0,
  description:
    "Current published generation from cad_inspect; protects against stale edits",
});
const nodeId = Type.String({
  minLength: 1,
  maxLength: 160,
  description:
    "Exact node ID from cad_tree, such as part:wall_left or joint:slide_lock_front",
});
const requestKey = Type.Optional(
  Type.String({
    pattern: "^[A-Za-z0-9_-]{8,100}$",
    description:
      "Reuse the same key and identical input when retrying an uncertain submission",
  }),
);
class CadError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}
async function request(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<any> {
  const response = await fetch(endpoint + path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(30000)])
      : AbortSignal.timeout(30000),
  });
  if (!response.ok)
    throw new CadError(
      response.status,
      JSON.stringify({
        http_status: response.status,
        detail: (await response.text()).slice(0, 4000),
        next:
          response.status === 409
            ? "Inspect current state; do not blindly retry with a newer generation."
            : response.status === 422
              ? "Check cad_capabilities and cad_schema; fix the input before retrying."
              : "Inspect the service/revision before retrying.",
      }),
    );
  return response.json();
}
function text(data: unknown) {
  const value = JSON.stringify(data, null, 2);
  const trimmed = truncateHead(value, { maxBytes: 40000, maxLines: 1200 });
  let output = value;
  if (trimmed.truncated) {
    let preview = trimmed.content;
    do {
      output = JSON.stringify({
        truncated: true,
        preview,
        next: "Use a focused inspect view, history page, tree node, part or validation section.",
      });
      if (Buffer.byteLength(output) <= 45000) break;
      preview = preview.slice(0, Math.floor(preview.length * 0.8));
    } while (preview.length);
  }
  return { content: [{ type: "text" as const, text: output }], details: {} };
}
function brief(row: any) {
  const report = row.result?.report;
  return {
    revision: row.id,
    status: row.status,
    base_generation: row.base_generation,
    name: row.document?.name,
    valid: report?.valid,
    parts: Object.keys(report?.parts ?? {}),
    parameters: report?.parameters,
    exports: row.result?.exports,
    engine: row.result?.engine,
    error: row.result?.error,
  };
}
async function build(
  document: unknown,
  expected_generation: number,
  callId: string,
  signal?: AbortSignal,
  key?: string,
  wait = true,
) {
  const request_key = key ?? createHash("sha256").update(callId).digest("hex");
  let row: any;
  try {
    row = await request(
      "/api/builds",
      { document, expected_generation, request_key },
      signal,
    );
  } catch (error) {
    const rejected =
      error instanceof CadError && error.status >= 400 && error.status < 500;
    throw new Error(
      JSON.stringify({
        request_key,
        submission: rejected
          ? "Rejected by service"
          : "Not confirmed; it may have been accepted",
        error: String(error),
        next: rejected
          ? "Inspect the error, current generation and live limits before changing the request."
          : "Inspect history or retry identical input with this request_key. Do not change expected_generation blindly.",
      }),
    );
  }
  const deadline = Date.now() + 110000;
  try {
    while (
      wait &&
      ["queued", "building"].includes(row.status) &&
      Date.now() < deadline
    ) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      signal?.throwIfAborted();
      row = await request(`/api/revisions/${row.id}`, undefined, signal);
    }
  } catch (error) {
    if (signal?.aborted) {
      await request(
        `/api/revisions/${row.id}/cancel`,
        {},
        AbortSignal.timeout(5000),
      ).catch(() => {});
      throw error;
    }
    return {
      revision: row.id,
      request_key,
      status: "unknown",
      error: String(error),
      next: "Poll cad_inspect with this revision. Do not resubmit a new build.",
    };
  }
  return {
    ...brief(row),
    request_key,
    result: row.result?.report
      ? {
          report: {
            valid: row.result.report.valid,
            parameters: row.result.report.parameters,
          },
        }
      : row.result,
    next:
      row.status === "ready"
        ? "Inspect cad_tree, cad_measure, cad_validate and cad_render. Publication is separate."
        : ["failed", "cancelled"].includes(row.status)
          ? "Inspect diagnostics; fix the input before building again. Nothing was published."
          : "Build still running; poll cad_inspect with this revision, or use cad_cancel.",
  };
}
export default function (pi: ExtensionAPI) {
  function tool<T extends TSchema>(
    name: string,
    description: string,
    parameters: T,
    execute: (
      p: Static<T>,
      s: AbortSignal | undefined,
      id: string,
    ) => Promise<unknown>,
  ) {
    pi.registerTool({
      name,
      label: name,
      description:
        description +
        " Outputs are bounded JSON; use focused selectors if truncated.",
      parameters,
      async execute(id, params, signal) {
        return text(await execute(params, signal, id));
      },
    });
  }
  tool(
    "cad_capabilities",
    "Read live service limits, supported operations and modeling/deployment boundaries. Use before proposing a change; JSON schema alone does not contain every runtime constraint.",
    Type.Object({}),
    async (_p, s) => request("/api/capabilities", undefined, s),
  );
  tool(
    "cad_schema",
    "Read declarative document schema or one section. Code execution is not supported. Check cad_capabilities too.",
    Type.Object({
      section: Type.Optional(
        StringEnum(["document", "casting_box", "solid_master", "feature"]),
      ),
    }),
    async (p, s) => {
      const schema = await request("/api/schema", undefined, s);
      if (!p.section || p.section === "document") return schema;
      const names = {
        casting_box: "CastingBox",
        solid_master: "SolidMaster",
        feature: "Feature",
      };
      return {
        section: p.section,
        schema: schema.$defs[names[p.section]],
        definitions: schema.$defs,
      };
    },
  );
  tool(
    "cad_example",
    "Get a complete enclosure/lid example document. This is an example, not the current design; use cad_inspect view=document before editing existing work.",
    Type.Object({}),
    async (_p, s) => request("/api/example", undefined, s),
  );
  tool(
    "cad_inspect",
    "Inspect state or an immutable revision. Default summary is compact; view=document returns editable source, diagnostics returns failure details, history is paginated. Does not change selection or restore.",
    Type.Object({
      revision: Type.Optional(revision),
      view: Type.Optional(
        StringEnum(["summary", "document", "diagnostics", "history"]),
      ),
      history_kind: Type.Optional(StringEnum(["publications", "builds"])),
      offset: Type.Optional(Type.Integer({ minimum: 0 })),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
    }),
    async (p, s) => {
      const state = await request("/api/state", undefined, s);
      if (p.view === "history") {
        const kind = p.history_kind ?? "publications",
          items = kind === "publications" ? state.publications : state.history,
          offset = p.offset ?? 0,
          limit = p.limit ?? 20;
        return {
          revision: state.revision,
          generation: state.generation,
          kind,
          items: items.slice(offset, offset + limit),
          total_available: items.length,
          next_offset: offset + limit < items.length ? offset + limit : null,
          note:
            kind === "builds"
              ? "Service retains only the latest 100 builds in this listing; publications are complete."
              : undefined,
        };
      }
      const id = p.revision ?? state.revision;
      const row = id
        ? await request(`/api/revisions/${id}`, undefined, s)
        : null;
      return {
        revision: row?.id ?? null,
        published_revision: state.revision,
        generation: state.generation,
        current: row ? brief(row) : null,
        ...(p.view === "document" ? { document: row?.document } : {}),
        ...(p.view === "diagnostics" ? { diagnostics: row?.result } : {}),
        next: row
          ? "Use cad_tree for assembly context; inspect source before editing."
          : "Use cad_example or cad_schema to start a design.",
      };
    },
  );
  tool(
    "cad_tree",
    "Browse the revision-bound assembly, output parts, source feature dependencies and registered mating interfaces. Logical interfaces are not extra solids or installed library components.",
    Type.Object({
      revision,
      node: Type.Optional(nodeId),
      max_depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 6 })),
    }),
    async (p, s) => {
      const data = await request(
        `/api/revisions/${p.revision}/tree`,
        undefined,
        s,
      );
      let root = data.root;
      if (p.node)
        root = (
          await request(
            `/api/revisions/${p.revision}/components/${encodeURIComponent(p.node)}`,
            undefined,
            s,
          )
        ).node;
      function trim(node: any, depth: number): any {
        return {
          ...node,
          child_count: node.children.length,
          children:
            depth < (p.max_depth ?? 3)
              ? node.children.map((child: any) => trim(child, depth + 1))
              : [],
          ...(depth >= (p.max_depth ?? 3) && node.children.length
            ? { child_ids: node.children.map((child: any) => child.id) }
            : {}),
        };
      }
      return { ...data, root: trim(root, 0) };
    },
  );
  tool(
    "cad_component_inspect",
    "Inspect an exact tree node: shared parameter expressions/values, consumers, dependencies, mating relationships, instructions and available whole-part measurements. No guessed library versions.",
    Type.Object({ revision, component_id: nodeId }),
    async (p, s) =>
      request(
        `/api/revisions/${p.revision}/components/${encodeURIComponent(p.component_id)}`,
        undefined,
        s,
      ),
  );
  tool(
    "cad_build",
    "Build a candidate from a COMPLETE JSON document. Never publishes. expected_generation protects the current design; request_key supports safe retries. wait=false returns immediately for polling.",
    Type.Object({
      document_json: Type.String({ maxLength: 200000 }),
      expected_generation: generation,
      request_key: requestKey,
      wait: Type.Optional(Type.Boolean()),
    }),
    async (p, s, id) =>
      build(
        JSON.parse(p.document_json),
        p.expected_generation,
        id,
        s,
        p.request_key,
        p.wait ?? true,
      ),
  );
  tool(
    "cad_parameters",
    "Change existing design-global parameters on the published document and build a candidate. Inspect consumers with cad_component_inspect and limits with cad_capabilities first. Never publishes.",
    Type.Object({
      changes_json: Type.String({ maxLength: 16000 }),
      expected_generation: generation,
      request_key: requestKey,
      wait: Type.Optional(Type.Boolean()),
    }),
    async (p, s, id) => {
      const state = await request("/api/state", undefined, s);
      if (state.generation !== p.expected_generation || !state.revision)
        throw new Error(
          "No published model or stale generation; inspect first.",
        );
      const row = await request(
        `/api/revisions/${state.revision}`,
        undefined,
        s,
      );
      const changes = JSON.parse(p.changes_json);
      if (
        !changes ||
        Array.isArray(changes) ||
        typeof changes !== "object" ||
        !Object.keys(changes).length
      )
        throw new Error("changes_json must be a nonempty object");
      for (const [name, value] of Object.entries(changes)) {
        if (!Object.hasOwn(row.document.parameters, name))
          throw new Error(`Unknown parameter: ${name}`);
        if (
          !(
            (typeof value === "number" && Number.isFinite(value)) ||
            typeof value === "string"
          )
        )
          throw new Error(
            "Parameter values must be finite numbers or arithmetic strings",
          );
        row.document.parameters[name] = value;
      }
      return build(
        row.document,
        p.expected_generation,
        id,
        s,
        p.request_key,
        p.wait ?? true,
      );
    },
  );
  tool(
    "cad_cancel",
    "Cancel a queued/running candidate by revision ID. This does not undo completed publications or other file changes.",
    Type.Object({ revision }),
    async (p, s) => {
      const row = await request(`/api/revisions/${p.revision}`, undefined, s);
      return ["queued", "building"].includes(row.status)
        ? brief(await request(`/api/revisions/${p.revision}/cancel`, {}, s))
        : {
            ...brief(row),
            cancelled_now: false,
            note: "Already finished; nothing changed.",
          };
    },
  );
  tool(
    "cad_measure",
    "Read whole-part dimensions/volume/area and measurement basis. Analytic masters are measured from validated meshes, not exact B-reps. Select a part to keep results focused.",
    Type.Object({
      revision,
      part: Type.Optional(Type.String({ maxLength: 48 })),
    }),
    async (p, s) => {
      const r = await request(
        `/api/revisions/${p.revision}/report`,
        undefined,
        s,
      );
      if (p.part && !Object.hasOwn(r.parts, p.part))
        throw new Error("Unknown output part; use cad_tree");
      return {
        revision: p.revision,
        units: r.units,
        parts: p.part ? { [p.part]: r.parts[p.part] } : r.parts,
        dimensions: r.analytic_surface?.dimensions,
        casting_box_dimensions: r.casting_box?.dimensions,
        note: "Volumes describe solid parts, not automatically the available plaster cavity. No physical strength certification.",
      };
    },
  );
  tool(
    "cad_validate",
    "Inspect explicit geometry, exported-mesh and assembly checks. Passing checks do not certify strength, leak-tightness or manufacturability. section=summary is concise; inspect other sections before publication.",
    Type.Object({
      revision,
      section: Type.Optional(
        StringEnum(["summary", "checks", "mesh", "exports", "assembly", "all"]),
      ),
    }),
    async (p, s) => {
      const r = await request(
          `/api/revisions/${p.revision}/report`,
          undefined,
          s,
        ),
        section = p.section ?? "summary";
      if (section === "all") return r;
      const sections = {
        checks: r.checks,
        mesh: r.mesh_validation,
        exports: {
          master: r.export_validation,
          tooling: r.casting_box?.part_validation,
        },
        assembly: r.casting_box?.assembly_checks,
      };
      return {
        revision: p.revision,
        valid: r.valid,
        section,
        ...(section === "summary"
          ? {
              checks: r.checks,
              mesh: r.mesh_validation,
              available_sections: Object.entries(sections)
                .filter(([, v]) => v !== undefined)
                .map(([key]) => key),
              limitations: r.limitations,
              note: "Passing modeled checks is not physical testing. Inspect assembly and export sections for tooling.",
            }
          : { results: sections[section] ?? null }),
      };
    },
  );
  for (const operation of ["publish", "restore"] as const)
    tool(
      `cad_${operation}`,
      operation === "publish"
        ? "Publish a validated ready candidate after inspecting measurements, assembly/export checks and renders. This changes the active design. Use current expected_generation; stale edits are rejected."
        : "Explicitly restore a previously published revision, creating a new publication event. Browsing history is NOT permission to restore. Does not delete history.",
      Type.Object({ revision, expected_generation: generation }),
      async (p, s) =>
        request(
          `/api/revisions/${p.revision}/${operation}`,
          { expected_generation: p.expected_generation },
          s,
        ),
    );
  tool(
    "cad_export",
    "List available exports or resolve one revision-bound download. Does not send files. Returned service URL is container/host-local, not a public share URL; website downloads require login.",
    Type.Object({
      revision,
      format: Type.Optional(StringEnum(["step", "stl", "3mf", "dxf", "zip"])),
      section: Type.Optional(Type.String({ maxLength: 48 })),
      part: Type.Optional(Type.String({ maxLength: 48 })),
    }),
    async (p, s) => {
      if (!p.format) {
        const row = await request(`/api/revisions/${p.revision}`, undefined, s);
        return {
          revision: p.revision,
          status: row.status,
          exports: row.result?.exports ?? {},
        };
      }
      const data = await request(
        `/api/revisions/${p.revision}/export/${p.format}?${new URLSearchParams({ ...(p.section ? { section: p.section } : {}), ...(p.part ? { part: p.part } : {}) })}`,
        undefined,
        s,
      );
      return {
        ...data,
        url: endpoint + data.url,
        manifest_url: endpoint + data.manifest_url,
        website_path: `/downloads/${p.revision}/${data.filename}`,
        note: "Website-relative path requires authentication; do not give users the internal loopback URL as a public download.",
      };
    },
  );
  pi.registerTool({
    name: "cad_render",
    label: "CAD render",
    description:
      "Inspect a revision-bound image, including unpublished candidates. Default is isometric; exploded views show assembly relationships. Viewing does not publish.",
    parameters: Type.Object({
      revision,
      view: Type.Optional(StringEnum(["iso", "top", "front", "exploded"])),
    }),
    async execute(_id, p, signal) {
      const view = p.view ?? "iso";
      const response = await fetch(
        `${endpoint}/api/revisions/${p.revision}/artifacts/render-${view}.png`,
        {
          signal: signal
            ? AbortSignal.any([signal, AbortSignal.timeout(15000)])
            : AbortSignal.timeout(15000),
        },
      );
      if (!response.ok)
        throw new Error(
          `Render unavailable (${response.status}); inspect candidate status and available views.`,
        );
      return {
        content: [
          {
            type: "text",
            text: `Revision ${p.revision}, ${view}; mm. Viewing only.`,
          },
          {
            type: "image",
            mimeType: "image/png",
            data: Buffer.from(await response.arrayBuffer()).toString("base64"),
          },
        ],
        details: { revision: p.revision, view },
      };
    },
  });
}
