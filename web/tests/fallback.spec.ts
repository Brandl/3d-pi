import { test, expect } from "@playwright/test";

test("loads an image preview when WebGL and WebSocket are unavailable", async ({ page, request }) => {
  const state = await (await request.get("/api/state")).json();
  const revision=state.workspace?.revision??state.revision;
  test.skip(!revision, "Requires a working or published model");
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
      if (type.includes("webgl")) return null;
      return Reflect.apply(getContext, this, [type, ...args]);
    } as typeof getContext;
    Object.defineProperty(window, "WebSocket", {
      value: class { constructor() { throw new Error("WebSocket blocked for test"); } },
    });
  });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.locator("#viewport")).toHaveAttribute("data-revision", revision);
  await expect(page.locator("#connection")).toContainText("polling");
  await expect(page.locator("#geometry-status")).toContainText("WebGL unavailable");
  const image = page.getByAltText("Server-rendered CAD model preview");
  await expect(image).toBeVisible();
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Top" }).click();
  await expect(image).toHaveAttribute("src", /render-top\.png$/);
  expect(errors).toEqual([]);
});
