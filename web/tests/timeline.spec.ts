import { test, expect } from "@playwright/test";

for (const fallback of [false, true]) {
  test(`browse and scrub history without publishing (${fallback ? "image" : "WebGL"})`, async ({page, request}) => {
    const original = await (await request.get("/api/state")).json();
    const publications = [...(original.publications ?? [])].sort((a,b) => a.generation-b.generation);
    test.skip(publications.length < 2, "Requires two published versions");
    const first = publications[0];
    const previous = publications[publications.length-2];
    const errors: string[] = [];
    const mutations: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("request", req => { if (!["GET","HEAD"].includes(req.method())) mutations.push(req.url()); });
    await page.addInitScript(({fallback}) => {
      // Deterministic polling lets this test simulate a later publication without changing real data.
      Object.defineProperty(window,"WebSocket",{value:class { constructor() { throw new Error("Polling test"); } }});
      if (fallback) {
        const original = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
          if (type.includes("webgl")) return null;
          return Reflect.apply(original, this, [type, ...args]);
        } as typeof original;
      }
    },{fallback});
    let state = original;
    await page.route("**/api/state", route => route.fulfill({json:state}));
    await page.goto("/");
    const viewport = page.locator("#viewport");
    await expect(viewport).toHaveAttribute("data-revision",original.revision);
    await page.getByRole("button",{name:"Previous",exact:true}).click();
    await expect(viewport).toHaveAttribute("data-revision",previous.revision);
    await expect(page.locator("#timeline-status")).toContainText("pinned");
    await expect(page).toHaveURL(new RegExp(`version=${previous.generation}`));
    await page.reload();
    await expect(viewport).toHaveAttribute("data-revision",previous.revision);
    await page.getByRole("button",{name:"Next",exact:true}).click();
    await expect(viewport).toHaveAttribute("data-revision",original.revision);
    const slider = page.getByLabel("Published version",{exact:true});
    await slider.focus();
    await slider.press("Home");
    await expect(viewport).toHaveAttribute("data-revision",first.revision);
    await expect(page.locator("#exports a").first()).toHaveAttribute("href",new RegExp(first.revision));
    if (fallback) {
      await expect(page.getByAltText("Server-rendered CAD model preview")).toHaveAttribute("src",new RegExp(first.revision));
    }
    state = {...original, generation:original.generation+1, revision:previous.revision,
      publications:[{...previous,generation:original.generation+1},...original.publications]};
    await expect(page.locator("#timeline-status")).toContainText(`latest is v${state.generation}`,{timeout:10000});
    await expect(viewport).toHaveAttribute("data-revision",first.revision);
    await page.getByRole("button",{name:"Latest",exact:true}).click();
    await expect(viewport).toHaveAttribute("data-revision",previous.revision);
    await expect(page).not.toHaveURL(/version=/);
    await page.getByText("Choose a version",{exact:true}).click();
    await page.locator(`#history li[data-version="${original.generation}"] button`).click();
    await expect(viewport).toHaveAttribute("data-revision",original.revision);
    await page.goto("/?version=999999");
    await expect(page.locator("#timeline-status")).toContainText("unavailable");
    await expect(viewport).toHaveAttribute("data-revision",previous.revision);
    expect((await (await request.get("/api/state")).json()).generation).toBe(original.generation);
    expect(mutations).toEqual([]);
    expect(errors).toEqual([]);
  });
}
