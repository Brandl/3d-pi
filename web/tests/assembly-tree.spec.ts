import { test, expect } from "@playwright/test";

test("browser uses revision-bound service tree and ignores stale component details", async ({
  page,
  request,
}) => {
  const state = await (await request.get("/api/state")).json();
  test.skip(!state.revision, "Requires a published design");
  const response = await request.get(`/api/revisions/${state.revision}/tree`);
  expect(response.ok()).toBeTruthy();
  const tree = await response.json();
  const parts = tree.root.children
    .find((n: any) => n.id === "parts")
    .children.filter((n: any) => n.children.length === 0);
  test.skip(parts.length < 2, "Requires two leaf output parts");
  const [first, second] = parts;
  await page.goto("/");
  await expect(page.locator("#assembly-tree")).toHaveAttribute(
    "data-revision",
    state.revision,
  );
  let release!: () => void;
  const delayed = new Promise<void>((resolve) => (release = resolve));
  await page.route(
    `**/components/${encodeURIComponent(first.id)}`,
    async (route) => {
      const result = await route.fetch();
      await delayed;
      await route.fulfill({ response: result });
    },
  );
  await page.locator(`[data-component="${first.id}"]`).click();
  await page.locator(`[data-component="${second.id}"]`).click();
  await expect(page.locator("#component-inspector h3")).toHaveText(second.name);
  release();
  await page.waitForTimeout(300);
  await expect(page.locator("#component-inspector h3")).toHaveText(second.name);
  await page.locator("#component-inspector summary").click();
  await expect(page.locator("#component-inspector pre")).toContainText(
    "measurements",
  );
  await expect(page.locator("#component-inspector")).toContainText(
    "design-global",
  );
  expect((await (await request.get("/api/state")).json()).generation).toBe(
    state.generation,
  );
});
