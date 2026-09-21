import {projectPath} from './project-path';

type TreeNode = {
  id: string;
  name: string;
  kind: string;
  children: TreeNode[];
  members?: string[];
  depends_on?: string[];
};
const viewport = document.getElementById("viewport")!;
const section = document.createElement("section");
section.setAttribute("aria-label", "Assembly tree");
const heading = document.createElement("h2");
heading.textContent = "Assembly tree";
const content = document.createElement("div");
content.id = "assembly-tree";
const inspector = document.createElement("div");
inspector.id = "component-inspector";
inspector.setAttribute("aria-live", "polite");
section.append(heading, content, inspector);
document.querySelector("aside .revision")!.after(section);
let current = "",
  epoch = 0,
  selection = 0;
async function inspect(node: TreeNode) {
  viewport.dataset.component=node.id;viewport.dataset.part=node.name;
  document.querySelectorAll<HTMLButtonElement>('[data-component]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.component===node.id)));
  window.dispatchEvent(new CustomEvent('cad:selection',{detail:{part:node.id.startsWith('part:')?node.id.slice(5):null}}));
  const revision = current,
    version = epoch,
    chosen = ++selection;
  inspector.textContent = "Loading " + node.name + "…";
  try {
    const response = await fetch(
      projectPath(`/api/revisions/${revision}/components/${encodeURIComponent(node.id)}`),
    );
    if (!response.ok) throw new Error("Component details unavailable");
    const data = await response.json();
    if (version !== epoch || chosen !== selection) return;
    inspector.replaceChildren();
    const title = document.createElement("h3");
    title.textContent = node.name;
    const id = document.createElement("p");
    id.className = "hint";
    id.textContent = node.id + " · " + node.kind.replaceAll("_", " ");
    inspector.append(title, id);
    for (const instruction of data.node.instructions ?? []) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = instruction;
      inspector.append(p);
    }
    const relations = [
      ...(data.node.members ?? []),
      ...(data.node.depends_on ?? []),
    ];
    if (relations.length) {
      const p = document.createElement("p");
      p.className = "hint";
      p.textContent = "Linked nodes: " + relations.join(", ");
      inspector.append(p);
    }
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Parameters & references";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(
      {
        parameters: data.parameters,
        relationships: data.relationships.map((r: TreeNode) => r.id),
        measurements: data.measurements,
      },
      null,
      2,
    );
    details.append(summary, pre);
    inspector.append(details);
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = data.note;
    inspector.append(note);
  } catch {
    if (version === epoch && chosen === selection)
      inspector.textContent =
        "Component details unavailable. Retry by selecting the node.";
  }
}
function render(node: TreeNode): HTMLElement {
  const wrapper = document.createElement("div");
  wrapper.className = "assembly-node";
  const button = document.createElement("button");
  button.textContent = node.name;
  button.dataset.component = node.id;
  button.title = node.kind.replaceAll("_", " ") + " · " + node.id;
  button.onclick = () => void inspect(node);
  if (node.children.length) {
    const details = document.createElement("details");
    details.open = ["assembly", "parts"].includes(node.id);
    const summary = document.createElement("summary");
    summary.textContent = node.name;
    summary.title = node.kind;
    details.append(summary);
    const inspectButton = document.createElement("button");
    inspectButton.textContent = "Inspect " + node.name;
    inspectButton.dataset.component = node.id;
    inspectButton.onclick = () => void inspect(node);
    details.append(inspectButton);
    for (const child of node.children) details.append(render(child));
    wrapper.append(details);
  } else wrapper.append(button);
  return wrapper;
}
async function update() {
  const revision = viewport.dataset.revision ?? "";
  if (revision === current) return;
  current = revision;
  const version = ++epoch;
  selection++;
  inspector.replaceChildren();
  content.textContent = revision
    ? "Loading hierarchy…"
    : "No revision selected.";
  if (!revision) return;
  try {
    const response = await fetch(projectPath(`/api/revisions/${revision}/tree`));
    if (!response.ok) throw new Error("Tree unavailable");
    const data = await response.json();
    if (version !== epoch) return;
    content.replaceChildren(render({...data.root,name:'Assembly'}));
    content.dataset.revision = revision;
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = '';
  } catch {
    if (version === epoch) {
      content.textContent = "Hierarchy unavailable for this revision.";
      delete content.dataset.revision;
    }
  }
}
new MutationObserver(() => void update()).observe(viewport, {
  attributes: true,
  attributeFilter: ["data-revision"],
});
window.addEventListener('cad:pick',event=>{const name=(event as CustomEvent).detail.part;const button=Array.from(content.querySelectorAll<HTMLButtonElement>('[data-component]')).find(b=>b.dataset.component==='part:'+name);button?.click();});
void update();
