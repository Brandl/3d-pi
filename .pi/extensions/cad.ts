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
type View = "iso" | "top" | "front" | "exploded";
type VisualContent =
  | { type: "text"; text: string }
  | { type: "image"; mimeType: "image/png"; data: string };
async function reviewImages(
  id: string,
  views: View[],
  signal?: AbortSignal,
  style: "inspection" | "standard" = "inspection",
) {
  const frames = await Promise.all(
    views.map(async (view) => {
      try {
        let prefix = style === "inspection" ? "review" : "render";
        const get = () =>
          fetch(
            `${endpoint}/api/revisions/${id}/artifacts/${prefix}-${view}.png`,
            {
              signal: signal
                ? AbortSignal.any([signal, AbortSignal.timeout(15000)])
                : AbortSignal.timeout(15000),
            },
          );
        let response = await get();
        if (response.status === 404 && prefix === "review") {
          await response.body?.cancel();
          prefix = "render";
          response = await get();
        }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        if (!response.headers.get("content-type")?.startsWith("image/png")) {
          await response.body?.cancel();
          throw new Error("Expected PNG");
        }
        const reader = response.body!.getReader(),
          chunks: Uint8Array[] = [];
        let size = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.length;
          if (size > 4 * 1024 * 1024) {
            await reader.cancel();
            throw new Error("Image exceeds 4 MiB review limit");
          }
          chunks.push(value);
        }
        const image = Buffer.concat(chunks);
        if (
          image.length < 24 ||
          !image
            .subarray(0, 8)
            .equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
        )
          throw new Error("Invalid PNG");
        const width = image.readUInt32BE(16),
          height = image.readUInt32BE(20);
        if (!width || !height || width > 4096 || height > 4096)
          throw new Error("Image dimensions exceed review limit");
        return { view, prefix, image };
      } catch (error) {
        signal?.throwIfAborted();
        return { view, error: String(error) };
      }
    }),
  );
  const content: VisualContent[] = [];
  for (const frame of frames) {
    if (frame.image) {
      content.push(
        {
          type: "text",
          text: `Visual checkpoint · revision ${id} · ${frame.view.toUpperCase()} · mm. ${frame.prefix === "review" ? "Distinct named part colours and legend." : "Standard render fallback: this revision has no inspection-colour image."} Preview geometry; transparent parts may be shown. This is NOT a hidden-line drawing. Inspect shape, proportions, mating alignment, clearances and requested changes; do not infer dimensions from pixels.`,
        },
        {
          type: "image",
          mimeType: "image/png",
          data: frame.image.toString("base64"),
        },
      );
    } else
      content.push({
        type: "text",
        text: `Revision ${id}: ${frame.view} image unavailable (${frame.error}). ${frame.view === "exploded" ? "Exploded view is optional and may not exist." : "Visual review is incomplete; retry cad_render before publication."}`,
      });
  }
  return {
    content,
    details: {
      revision: id,
      views: frames.filter((f) => f.image).map((f) => f.view),
      missing_views: frames.filter((f) => !f.image).map((f) => f.view),
      complete:
        frames.some((f) => Boolean(f.image)) &&
        frames
          .filter((f) => f.view !== "exploded")
          .every((f) => Boolean(f.image)),
      meaning:
        "Complete means requested mandatory images were attached, not that the design was approved.",
      hidden_line_rendering: false,
    },
  };
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
        ? "Inspect the attached visual checkpoint, cad_tree, cad_measure and cad_validate. Use cad_render to retry missing views or inspect again. Publication is separate."
        : ["failed", "cancelled"].includes(row.status)
          ? "Inspect diagnostics; fix the input before building again. Nothing was published."
          : "Build still running; poll cad_inspect with this revision, or use cad_cancel.",
  };
}
export default function (pi: ExtensionAPI) {
  const visualCheckpoints = new Set<string>();
  pi.on("session_compact", async () => {
    visualCheckpoints.clear();
  });
  function rememberCheckpoint(id: string) {
    visualCheckpoints.add(id);
    if (visualCheckpoints.size > 32)
      visualCheckpoints.delete(visualCheckpoints.values().next().value!);
  }
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
        " Primary text is bounded JSON; use focused selectors if truncated. Ready builds and first summary inspections attach a multi-view visual checkpoint when available.",
      parameters,
      async execute(id, params, signal) {
        const input = params as any;
        if (
          ["cad_publish", "cad_restore"].includes(name) &&
          !visualCheckpoints.has(input.revision)
        ) {
          const row = await request(
            `/api/revisions/${input.revision}`,
            undefined,
            signal,
          );
          if (row.status === "ready") {
            const review = await reviewImages(
              input.revision,
              ["iso", "top", "front", "exploded"],
              signal,
            );
            if (review.details.complete) rememberCheckpoint(input.revision);
            const checkpoint = text({
              revision: input.revision,
              status: "visual_review_required",
              published: false,
              next: `No publication performed. Inspect the attached images and validation results, then explicitly call ${name} again with the original expected_generation. If images are missing, retry cad_render first.`,
            });
            return {
              ...checkpoint,
              content: [...checkpoint.content, ...review.content],
              details: { visual_review: review.details },
            };
          }
        }
        const data: any = await execute(params, signal, id);
        const output = text(data);
        const candidate = ["cad_build", "cad_parameters"].includes(name)
          ? data
          : name === "cad_inspect" &&
              (!(params as any).view || (params as any).view === "summary")
            ? data.current
            : null;
        if (
          candidate?.status === "ready" &&
          !visualCheckpoints.has(candidate.revision)
        ) {
          const review = await reviewImages(
            candidate.revision,
            ["iso", "top", "front", "exploded"],
            signal,
          );
          if (review.details.complete) {
            rememberCheckpoint(candidate.revision);
          }
          return {
            ...output,
            content: [...output.content, ...review.content],
            details: { visual_review: review.details },
          };
        }
        return output;
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
        ? "Publish a validated ready candidate after inspecting measurements, checks and images. If this session has not received its visual checkpoint, the first call returns images WITHOUT publishing; inspect them and explicitly retry. Use the candidate base generation while still current."
        : "Explicitly restore a previously published revision. Browsing is NOT permission to restore. If its visual checkpoint has not been delivered this session, first return images WITHOUT restoring; inspect and explicitly retry. History is retained.",
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
        url: new URL(data.url, parsed.origin).href,
        manifest_url: new URL(data.manifest_url, parsed.origin).href,
        website_path: `${parsed.pathname.replace(/\/$/, '')}/downloads/${p.revision}/${data.filename}`,
        note: "Website-relative path requires authentication; do not give users the internal loopback URL as a public download.",
      };
    },
  );
  pi.registerTool({
    name: "cad_render",
    label: "CAD render",
    description:
      "Send actual images to the model for visual inspection. Default review includes iso/top/front and optional exploded views; choose a single view if needed. Inspection style uses named part colours where available, standard style uses original colours. No hidden-line rendering or automatic publication.",
    parameters: Type.Object({
      revision,
      view: Type.Optional(
        StringEnum(["review", "iso", "top", "front", "exploded"]),
      ),
      style: Type.Optional(StringEnum(["inspection", "standard"])),
    }),
    async execute(_id, p, signal) {
      const views: View[] =
        !p.view || p.view === "review"
          ? ["iso", "top", "front", "exploded"]
          : [p.view];
      const review = await reviewImages(
        p.revision,
        views,
        signal,
        p.style ?? "inspection",
      );
      if (
        review.details.complete &&
        ["iso", "top", "front"].every((view) => views.includes(view as View))
      )
        rememberCheckpoint(p.revision);
      return review;
    },
  });
}
