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
) {
  throw new Error(
    "CAD_URL must be a loopback HTTP URL. This MVP is local-only.",
  );
}
const revision = Type.String({
  pattern: "^[a-f0-9]{32}$",
  description: "Exact immutable revision ID",
});
const generation = Type.Integer({
  minimum: 0,
  description:
    "Generation returned by cad_inspect; protects against stale edits",
});

async function request(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<any> {
  const response = await fetch(`${endpoint}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(120000)])
      : AbortSignal.timeout(120000),
  });
  if (!response.ok)
    throw new Error(
      `CAD ${response.status}: ${(await response.text()).slice(0, 4000)}`,
    );
  return response.json();
}
function text(data: unknown) {
  const truncated = truncateHead(JSON.stringify(data, null, 2), {
    maxBytes: 45000,
    maxLines: 1500,
  });
  return {
    content: [
      {
        type: "text" as const,
        text:
          truncated.content +
          (truncated.truncated
            ? "\n[Truncated; fetch the specific revision or /api/schema directly for the full data.]"
            : ""),
      },
    ],
    details: {},
  };
}
async function build(
  document: unknown,
  expected_generation: number,
  callId: string,
  signal?: AbortSignal,
) {
  const request_key = createHash("sha256").update(callId).digest("hex");
  const row = await request(
    "/api/builds",
    { document, expected_generation, request_key },
    signal,
  );
  try {
    const deadline = Date.now() + 115000;
    while (Date.now() < deadline) {
      signal?.throwIfAborted();
      const status = await request(
        `/api/revisions/${row.id}`,
        undefined,
        signal,
      );
      if (status.status === "ready")
        return {
          revision: row.id,
          status: status.status,
          result: status.result,
          next: "Inspect report and renders; publish explicitly using the original expected_generation.",
        };
      if (["failed", "cancelled"].includes(status.status))
        throw new Error(JSON.stringify({ revision: row.id, ...status.result }));
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new Error(`Timed out waiting for revision ${row.id}`);
  } catch (error) {
    await request(
      `/api/revisions/${row.id}/cancel`,
      {},
      AbortSignal.timeout(5000),
    ).catch(() => {});
    throw error;
  }
}
export default function (pi: ExtensionAPI) {
  function tool<T extends TSchema>(
    name: string,
    description: string,
    parameters: T,
    execute: (
      params: Static<T>,
      signal: AbortSignal | undefined,
      id: string,
    ) => Promise<unknown>,
  ) {
    pi.registerTool({
      name,
      label: name,
      description: description + " Text output limited to 45 KB / 1500 lines.",
      parameters,
      async execute(id, params, signal) {
        return text(await execute(params, signal, id));
      },
    });
  }
  tool(
    "cad_schema",
    "Get the supported declarative document schema. No arbitrary Python execution.",
    Type.Object({}),
    async (_p, s) => request("/api/schema", undefined, s),
  );
  tool(
    "cad_example",
    "Get a complete parametric enclosure/lid document to build or adapt.",
    Type.Object({}),
    async (_p, s) => request("/api/example", undefined, s),
  );
  tool(
    "cad_inspect",
    "Get project state/history and current document, or one specific revision including diagnostics.",
    Type.Object({ revision: Type.Optional(revision) }),
    async (p, s) => {
      if (p.revision)
        return request(`/api/revisions/${p.revision}`, undefined, s);
      const state = await request("/api/state", undefined, s);
      return {
        ...state,
        current: state.revision
          ? await request(`/api/revisions/${state.revision}`, undefined, s)
          : null,
      };
    },
  );
  tool(
    "cad_build",
    "Build a candidate from a full JSON document string. Does not publish. Use cad_schema/cad_example first.",
    Type.Object({
      document_json: Type.String({ maxLength: 200000 }),
      expected_generation: generation,
    }),
    async (p, s, id) =>
      build(JSON.parse(p.document_json), p.expected_generation, id, s),
  );
  tool(
    "cad_parameters",
    "Change existing parameters on the published document and build a candidate. Changes are a JSON object of numbers or arithmetic strings; unknown parameters are rejected. Does not publish.",
    Type.Object({
      changes_json: Type.String({ maxLength: 16000 }),
      expected_generation: generation,
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
      if (!changes || Array.isArray(changes) || typeof changes !== "object")
        throw new Error("Changes must be an object");
      for (const [name, value] of Object.entries(changes)) {
        if (!Object.hasOwn(row.document.parameters, name))
          throw new Error(`Unknown parameter: ${name}`);
        row.document.parameters[name] = value;
      }
      return build(row.document, p.expected_generation, id, s);
    },
  );
  for (const name of ["cad_measure", "cad_validate"]) {
    tool(
      name,
      "Return exact part bounding dimensions, area, volume, solid counts, parameters, and explicit check results. This is not comprehensive manufacturability validation.",
      Type.Object({ revision }),
      async (p, s) =>
        request(`/api/revisions/${p.revision}/report`, undefined, s),
    );
  }
  for (const operation of ["publish", "restore"]) {
    tool(
      `cad_${operation}`,
      operation === "publish"
        ? "Publish a ready candidate with passing checks. Inspect measurements/renders first. Stale candidates are rejected."
        : "Restore a previously published revision without deleting history.",
      Type.Object({ revision, expected_generation: generation }),
      async (p, s) =>
        request(
          `/api/revisions/${p.revision}/${operation}`,
          { expected_generation: p.expected_generation },
          s,
        ),
    );
  }
  tool(
    "cad_export",
    "Return a local download URL and provenance manifest for a validated revision. DXF requires a named XY section. Does not send files externally.",
    Type.Object({
      revision,
      format: StringEnum(["step", "stl", "3mf", "dxf", "zip"]),
      section: Type.Optional(Type.String()),
      part: Type.Optional(
        Type.String({
          description:
            "Named tooling component, e.g. wall_left, wall_right, lock_front, lock_back, or casting_box (STEP assembly). Omit for the reference dripper.",
        }),
      ),
    }),
    async (p, s) => {
      const data = await request(
        `/api/revisions/${p.revision}/export/${p.format}?${new URLSearchParams({ ...(p.section ? { section: p.section } : {}), ...(p.part ? { part: p.part } : {}) })}`,
        undefined,
        s,
      );
      return {
        ...data,
        url: endpoint + data.url,
        manifest_url: endpoint + data.manifest_url,
      };
    },
  );
  pi.registerTool({
    name: "cad_render",
    label: "CAD render",
    description:
      "Inspect a revision-bound PNG image from a standard camera. Geometry must be ready.",
    parameters: Type.Object({
      revision,
      view: StringEnum(["iso", "top", "front", "exploded"]),
    }),
    async execute(_id, p, signal) {
      const response = await fetch(
        `${endpoint}/api/revisions/${p.revision}/artifacts/render-${p.view}.png`,
        {
          signal: signal
            ? AbortSignal.any([signal, AbortSignal.timeout(15000)])
            : AbortSignal.timeout(15000),
        },
      );
      if (!response.ok)
        throw new Error(`Render unavailable: ${response.status}`);
      return {
        content: [
          {
            type: "text",
            text: `Revision ${p.revision}, ${p.view} view, millimeters.`,
          },
          {
            type: "image",
            mimeType: "image/png",
            data: Buffer.from(await response.arrayBuffer()).toString("base64"),
          },
        ],
        details: { revision: p.revision },
      };
    },
  });
}
