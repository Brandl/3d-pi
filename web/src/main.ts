import {projectPath} from './project-path';
import './projects';
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import "./style.css";
import './chat';
import './workspace';

type Preview = {
  parts: {
    name: string;
    color: string;
    vertices: number[][];
    triangles: number[][];
    edges: number[][];
    normals?: number[][];
    flat_normals?: { start: number; count: number; normal: number[] }[];
    material?: "standard" | "porcelain";
    opacity?: number;
    exploded_offset?: number[];
  }[];
};
type Publication = {
  generation: number;
  revision: string;
  operation: string;
  created?: number;
  name?: string | null;
};
type State = {
  revision: string | null;
  generation: number;
  history: { id: string; status: string }[];
  publications?: Publication[];
  candidates?: string[];
};
type Part = {
  x: number;
  y: number;
  z: number;
  volume: number;
  solid_count: number;
  color?: string;
  role?: string;
  export_triangles?: number;
};
type Revision = {
  id: string;
  document: { name: string; outputs: { name: string; color: string }[] };
  result: {
    report: {
      valid: boolean;
      parameters: Record<string, number>;
      parts: Record<string, Part>;
      mesh_validation?: { triangles: number };
      casting_box?: unknown;
    };
    exports: Record<string, string>;
  };
};
const $ = (id: string) => document.getElementById(id)!;
const exportType = $("export-type") as HTMLSelectElement;
function filterExports() {
  let count = 0;
  for (const link of Array.from($("exports").querySelectorAll<HTMLAnchorElement>("a"))) {
    link.hidden = Boolean(exportType.value && link.dataset.fileType !== exportType.value);
    if (!link.hidden) count++;
  }
  $("export-count").textContent = `${count} file${count === 1 ? "" : "s"}`;
}
exportType.addEventListener("change", filterExports);
const format = (n: number) =>
  n.toLocaleString(undefined, { maximumFractionDigits: 2 });
async function get<T>(url: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(projectPath(url), {
      signal: controller.signal,
      cache: "no-store",
    });
    if (response.status === 401) location.assign('/auth/login?next='+encodeURIComponent(location.pathname+location.search));
    if (!response.ok)
      throw new Error(`HTTP ${response.status}: ${await response.text()}`);
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}
const viewport = $("viewport");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 50000);
camera.up.set(0, 0, 1);
const renderer = (() => {
  try {
    return new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch (error) {
    console.warn("WebGL unavailable; using server-rendered views", error);
    return null;
  }
})();
const fallbackImage = document.createElement("img");
fallbackImage.alt = "Server-rendered CAD model preview";
fallbackImage.style.cssText =
  "position:absolute;inset:0;width:100%;height:100%;object-fit:contain;pointer-events:none";
if (renderer) {
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0, 0);
  viewport.prepend(renderer.domElement);
} else {
  fallbackImage.hidden = true;
  viewport.prepend(fallbackImage);
}
const controls = renderer
  ? new OrbitControls(camera, renderer.domElement)
  : null;
if (controls) controls.enableDamping = true;
function updateFallbackImage(revision: string) {
  fallbackImage.src = projectPath(`/api/revisions/${revision}/artifacts/render-${exploded ? "exploded" : currentView}.png`);
  fallbackImage.hidden = false;
}
scene.add(new THREE.HemisphereLight(0xd7efff, 0x536270, 2.5));
const light = new THREE.DirectionalLight(0xffffff, 3.0);
light.position.set(100, -150, 250);
scene.add(light);
const fill = new THREE.DirectionalLight(0x9bcfff, 1.5);
fill.position.set(-150, 100, 80);
scene.add(fill);
const grid = new THREE.GridHelper(500, 50, 0x355269, 0x263b4e);
grid.rotation.x = Math.PI / 2;
grid.position.z = -0.1;
scene.add(grid);
scene.add(new THREE.AxesHelper(20));
let model = new THREE.Group();
scene.add(model);
let radius = 100;
let center = new THREE.Vector3(0, 0, 0);
let currentView = "iso";
let exploded = false;
function layoutModel() {
  for (const part of model.children) {
    const offset = exploded
      ? (part.userData.explodedOffset ?? [0, 0, 0])
      : [0, 0, 0];
    part.position.set(offset[0], offset[1], offset[2]);
    part.traverse((object) => {
      if (object instanceof THREE.Mesh) {
        const materials = Array.isArray(object.material)
          ? object.material
          : [object.material];
        for (const material of materials) {
          material.opacity = exploded
            ? 1
            : (part.userData.assembledOpacity ?? 1);
          material.transparent = material.opacity < 1;
          material.depthWrite = !material.transparent;
          material.needsUpdate = true;
        }
      }
    });
  }
  const bounds = new THREE.Box3().setFromObject(model);
  grid.position.z = bounds.min.z - 0.5;
  const sphere = bounds.getBoundingSphere(new THREE.Sphere());
  radius = Math.max(sphere.radius, 1);
  center = sphere.center;
}
$("explode").onclick = () => {
  exploded = !exploded;
  $("explode").textContent = exploded ? "Assemble" : "Explode";
  layoutModel();
  view(currentView);
};
function view(name: string) {
  currentView = name;
  if (!renderer && viewport.dataset.revision)
    updateFallbackImage(viewport.dataset.revision);
  const direction =
    name === "top"
      ? new THREE.Vector3(0, -0.001, 1)
      : name === "front"
        ? new THREE.Vector3(0, -1, 0)
        : new THREE.Vector3(1, -1.3, 1);
  const limitingFov = Math.min(
    camera.fov,
    THREE.MathUtils.radToDeg(
      2 *
        Math.atan(
          Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect,
        ),
    ),
  );
  const distance =
    (radius / Math.sin(THREE.MathUtils.degToRad(limitingFov / 2))) * 1.15;
  controls?.target.copy(center);
  camera.position
    .copy(center)
    .add(direction.normalize().multiplyScalar(distance));
  camera.near = Math.max(0.01, radius / 1000);
  camera.far = Math.max(50000, distance * 10);
  camera.updateProjectionMatrix();
  controls?.update();
}
new ResizeObserver(() => {
  camera.aspect = viewport.clientWidth / viewport.clientHeight;
  camera.updateProjectionMatrix();
  renderer?.setSize(viewport.clientWidth, viewport.clientHeight);
}).observe(viewport);
view("iso");
document
  .querySelectorAll<HTMLButtonElement>("[data-view]")
  .forEach((button) => (button.onclick = () => view(button.dataset.view!)));
$("fit").onclick = () => view(currentView);
window.addEventListener("keydown", (event) => {
  if (document.querySelector('dialog[open]') || event.ctrlKey || event.metaKey || event.altKey ||
      (event.target instanceof HTMLElement && (event.target.matches('input, textarea, select') || event.target.isContentEditable))) return;
  const views: Record<string, string> = {
    "1": "iso",
    "2": "top",
    "3": "front",
    f: currentView,
  };
  if (views[event.key.toLowerCase()]) view(views[event.key.toLowerCase()]);
});
renderer?.setAnimationLoop(() => {
  controls?.update();
  renderer.render(scene, camera);
});
function dispose(group: THREE.Group) {
  group.traverse((object) => {
    const mesh = object as THREE.Mesh;
    mesh.geometry?.dispose();
    const materials = mesh.material
      ? Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material]
      : [];
    materials.forEach((material) => material.dispose());
  });
}
function createModel(preview: Preview) {
  const group = new THREE.Group();
  for (const part of preview.parts) {
    const partGroup = new THREE.Group();
    partGroup.name = part.name;
    partGroup.userData.explodedOffset = part.exploded_offset;
    partGroup.userData.assembledOpacity = part.opacity ?? 1;
    group.add(partGroup);
    const indexed = new THREE.BufferGeometry();
    indexed.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(part.vertices.flat(), 3),
    );
    indexed.setIndex(part.triangles.flat());
    if (part.normals) {
      indexed.setAttribute(
        "normal",
        new THREE.Float32BufferAttribute(part.normals.flat(), 3),
      );
    }
    const geometry = indexed.toNonIndexed();
    indexed.dispose();
    if (!part.normals) geometry.computeVertexNormals();
    const normals = geometry.getAttribute("normal");
    for (const range of part.flat_normals ?? []) {
      for (let i = range.start * 3; i < (range.start + range.count) * 3; i++) {
        normals.setXYZ(i, range.normal[0], range.normal[1], range.normal[2]);
      }
    }
    const material =
      part.material === "porcelain"
        ? new THREE.MeshPhysicalMaterial({
            color: part.color,
            roughness: 0.4,
            metalness: 0,
            clearcoat: 0.15,
            clearcoatRoughness: 0.4,
          })
        : new THREE.MeshStandardMaterial({
            color: part.color,
            roughness: 0.65,
            metalness: 0.12,
          });
    material.opacity = part.opacity ?? 1;
    material.transparent = material.opacity < 1;
    material.depthWrite = !material.transparent;
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = part.name;
    partGroup.add(mesh);
    const edges = new THREE.BufferGeometry();
    edges.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(part.edges.flat(), 3),
    );
    partGroup.add(
      new THREE.LineSegments(
        edges,
        new THREE.LineBasicMaterial({
          color: part.material === "porcelain" ? 0x9c8d76 : 0x152936,
          transparent: true,
          opacity: part.material === "porcelain" ? 0.4 : 0.7,
        }),
      ),
    );
  }
  return group;
}
function details(row: Revision) {
  $("title").textContent = row.document.name;
  $("revision").textContent = `Revision ${row.id.slice(0, 8)}`;
  $("part-count").textContent = String(
    Object.keys(row.result.report.parts).length,
  );
  $("parts").replaceChildren();
  for (const [name, part] of Object.entries(row.result.report.parts)) {
    const item = document.createElement("div");
    item.className = "part";
    const title = document.createElement("strong");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background =
      row.document.outputs.find((o) => o.name === name)?.color ??
      part.color ??
      "#71b7d5";
    title.append(swatch, document.createTextNode(name));
    const size = document.createElement("small");
    size.textContent = `${format(part.x)} × ${format(part.y)} × ${format(part.z)} mm`;
    const volume = document.createElement("small");
    volume.textContent = `${format(part.volume / 1000)} cm³ · ${part.solid_count} solid${part.solid_count === 1 ? "" : "s"}`;
    item.append(title, size, volume);
    const triangles =
      part.export_triangles ??
      (name === row.document.outputs[0]?.name
        ? row.result.report.mesh_validation?.triangles
        : undefined);
    if (triangles) {
      const count = document.createElement("small");
      count.textContent = `${format(triangles)} export triangles · validated`;
      item.append(count);
    }
    if (part.role) {
      const role = document.createElement("small");
      role.textContent = part.role;
      item.append(role);
    }
    $("parts").append(item);
  }
  $("parameters").replaceChildren();
  for (const [key, value] of Object.entries(row.result.report.parameters)) {
    const term = document.createElement("dt");
    term.textContent = key;
    const val = document.createElement("dd");
    val.textContent = format(value);
    $("parameters").append(term, val);
  }
  const previousType = exportType.value;
  const types = [...new Set(Object.keys(row.result.exports).map(key => key.split(":")[0]))].sort();
  exportType.replaceChildren(new Option("All file types", ""),
    ...types.map(type => new Option(type.toUpperCase(), type)));
  exportType.value = types.includes(previousType) ? previousType : "";
  exportType.disabled = types.length === 0;
  $("exports").replaceChildren();
  for (const [format, filename] of Object.entries(row.result.exports)) {
    const link = document.createElement("a");
    link.href = projectPath(`/downloads/${row.id}/${encodeURIComponent(filename)}`);
    const [kind, part] = format.split(":");
    link.dataset.fileType = kind;
    link.textContent = part
      ? `${kind.toUpperCase()} · ${part.replaceAll("_", " ")}`
      : `${kind.toUpperCase()}${row.result.report.casting_box ? " · dripper" : ""}`;
    link.download = filename;
    $("exports").append(link);
  }
  filterExports();
}
let desired: string | null = null;
let loaded: string | null = null;
let loading: string | null = null;
let generation = -1;
let latest: State;
let loadError = "";
function versionFromUrl(): number | null {
  const value = Number(new URL(location.href).searchParams.get("version"));
  return Number.isSafeInteger(value) && value > 0 ? value : null;
}
let selectedVersion = versionFromUrl();
let candidate = new URL(location.href).searchParams.get('candidate');
const draftSelect = $('draft-select') as HTMLSelectElement;
draftSelect.addEventListener('change',()=>{
  const url=new URL(location.href);url.searchParams.delete('version');
  if(draftSelect.value)url.searchParams.set('candidate',draftSelect.value);else url.searchParams.delete('candidate');
  location.assign(url);
});
let timeline: Publication[] = [];
let timelineKey = "";
let selectionWarning = "";
const timelinePosition = $("timeline-position") as HTMLInputElement;
function chooseVersion(version: number | null) {
  selectedVersion = version;
  candidate = null;
  selectionWarning = "";
  loadError = "";
  const url = new URL(location.href);
  url.searchParams.delete('candidate');
  if (version === null) url.searchParams.delete("version");
  else url.searchParams.set("version", String(version));
  history.replaceState(null, "", url);
  if (latest) void update(latest);
}
function timelineIndex() {
  return selectedVersion === null ? timeline.length - 1 : timeline.findIndex(p => p.generation === selectedVersion);
}
$("timeline-previous").addEventListener("click", () => {
  const entry = timeline[timelineIndex() - 1];
  if (entry) chooseVersion(entry.generation);
});
$("timeline-next").addEventListener("click", () => {
  const entry = timeline[timelineIndex() + 1];
  if (entry) chooseVersion(entry.generation);
});
$("timeline-latest").addEventListener("click", () => chooseVersion(null));
timelinePosition.addEventListener("input", () => {
  const entry = timeline[Number(timelinePosition.value)];
  if (entry) chooseVersion(entry.generation);
});
window.addEventListener("popstate", () => {
  selectedVersion = versionFromUrl();
  selectionWarning = "";
  if (latest) void update(latest);
});
function renderTimeline(state: State) {
  timeline = [...(state.publications ?? (state.revision ? [{
    generation: state.generation, revision: state.revision, operation: "publish",
  }] : []))].sort((a,b) => a.generation-b.generation);
  if (selectedVersion !== null && !timeline.some(p => p.generation === selectedVersion)) {
    selectionWarning = `Version ${selectedVersion} is unavailable; showing latest. `;
    selectedVersion = null;
  }
  const index = timelineIndex();
  const entry = timeline[index];
  const candidates = state.candidates ?? [];
  if(candidate && !candidates.includes(candidate))candidate=null;
  if(!state.revision && !candidate)candidate=candidates[0]??null;
  desired = candidate ?? entry?.revision ?? state.revision;
  draftSelect.replaceChildren(new Option('Published model',''));
  for(const id of candidates)draftSelect.add(new Option('Unpublished · '+id.slice(0,8),id));
  draftSelect.value=candidate??'';
  const key = JSON.stringify(timeline);
  if (key !== timelineKey) {
    timelineKey = key;
    $("history").replaceChildren();
    for (const publication of [...timeline].reverse()) {
      const item = document.createElement("li");
      item.dataset.version = String(publication.generation);
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `v${publication.generation} · ${publication.name || publication.revision.slice(0,8)}`;
      const meta = document.createElement("small");
      meta.textContent = `${publication.operation === "restore" ? "Restored · " : ""}${publication.revision.slice(0,8)}${publication.created ? " · " + new Date(publication.created * 1000).toLocaleString() : ""}`;
      button.append(meta);
      button.addEventListener("click", () => chooseVersion(publication.generation));
      item.append(button);
      $("history").append(item);
    }
  }
  for (const item of Array.from($("history").querySelectorAll<HTMLLIElement>("li"))) {
    const selected = Number(item.dataset.version) === entry?.generation;
    item.classList.toggle("current", selected);
    item.querySelector("button")!.setAttribute("aria-pressed", String(selected));
  }
  timelinePosition.max = String(Math.max(0, timeline.length-1));
  timelinePosition.value = String(Math.max(0, index));
  timelinePosition.disabled = timeline.length < 2;
  timelinePosition.setAttribute("aria-valuetext", entry ? `Version ${entry.generation}: ${entry.name || entry.revision.slice(0,8)}` : "No published versions");
  ($("timeline-previous") as HTMLButtonElement).disabled = index <= 0;
  ($("timeline-next") as HTMLButtonElement).disabled = index < 0 || index >= timeline.length-1;
  ($("timeline-latest") as HTMLButtonElement).disabled = selectedVersion === null;
  const status = candidate ? 'UNPUBLISHED CANDIDATE · '+candidate.slice(0,8)+' · browsing does not publish' : selectionWarning + (entry
    ? selectedVersion === null ? `Following latest · v${entry.generation}` : `Viewing v${entry.generation} · pinned · latest is v${state.generation}`
    : "No published versions.");
  if ($("timeline-status").textContent !== status) $("timeline-status").textContent = status;
}
async function update(state: State) {
  if (state.generation < generation) return;
  latest = state;
  generation = state.generation;
  renderTimeline(state);
  const building = state.history.filter((row) =>
    ["queued", "building"].includes(row.status),
  );
  const failed = state.history[0]?.status === "failed";
  $("notice").textContent =
    loadError ||
    (building.length
      ? `${building.length} build(s) in progress · showing last published revision`
      : failed
        ? "Latest build failed. Published geometry is unchanged; ask pi for diagnostics."
        : "");
  if (!desired || desired === loaded || desired === loading) return;
  const id = desired;
  loading = id;
  try {
    const [row, preview] = await Promise.all([
      get<Revision>(`/api/revisions/${id}`),
      get<Preview>(`/api/revisions/${id}/artifacts/preview.json`),
    ]);
    if (desired !== id) return;
    const next = createModel(preview);
    const first = !loaded;
    scene.remove(model);
    dispose(model);
    model = next;
    scene.add(model);
    const hasTooling = preview.parts.some((p) => p.exploded_offset);
    $("explode").hidden = !hasTooling;
    if (!hasTooling) exploded = false;
    $("explode").textContent = exploded ? "Assemble" : "Explode";
    layoutModel();
    if (first) view("iso");
    loaded = id;
    loadError = "";
    details(row);
    $("empty").hidden = true;
    const triangles = preview.parts.reduce(
      (sum, p) => sum + p.triangles.length,
      0,
    );
    $("geometry-status").textContent = renderer
      ? `${format(triangles)} preview triangles · checks passed`
      : "WebGL unavailable · image preview · use the camera buttons";
    viewport.dataset.revision = id;
    if (!renderer) updateFallbackImage(id);
  } catch (error) {
    if (desired === id) loadError = `Unable to load preview; keeping last good model. ${String(error)}`;
  } finally {
    if (loading === id) loading = null;
    $("notice").textContent =
      loadError ||
      (latest.history.some((r) => ["queued", "building"].includes(r.status))
        ? "Build in progress · showing last published revision"
        : "");
  }
}
let retry = 500;
let socketLive = false;
let lastSuccess = 0;
function connectionStatus() {
  $("connection").textContent = socketLive
    ? "● Live"
    : Date.now() - lastSuccess < 20000
      ? "● Connected · polling"
      : "○ Connection unavailable · retrying";
}
async function poll() {
  try {
    const state = await get<State>("/api/state");
    lastSuccess = Date.now();
    connectionStatus();
    await update(state);
  } catch (error) {
    connectionStatus();
    $("notice").textContent = `Connection failed; retrying. ${String(error)}`;
  } finally {
    setTimeout(poll, 4000);
  }
}
function connect() {
  try {
    const socket = new WebSocket(
      `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${projectPath('/api/events')}`,
    );
    const deadline = setTimeout(() => socket.close(), 8000);
    socket.onopen = () => {
      clearTimeout(deadline);
      retry = 500;
      socketLive = true;
      lastSuccess = Date.now();
      connectionStatus();
    };
    socket.onmessage = (event) => {
      lastSuccess = Date.now();
      void update(JSON.parse(event.data));
    };
    socket.onclose = () => {
      clearTimeout(deadline);
      socketLive = false;
      connectionStatus();
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 10000);
    };
    socket.onerror = () => socket.close();
  } catch {
    socketLive = false;
    connectionStatus();
    setTimeout(connect, 10000);
  }
}
void poll();
connect();
