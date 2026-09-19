import { test, expect } from "@playwright/test";

for (const fallback of [false, true]) {
  test(`casting box explodes without changing geometry (${fallback ? "image" : "WebGL"})`, async ({ page, request }) => {
    const state = await (await request.get("/api/state")).json();
    test.skip(!state.revision, "Requires a published casting box");
    const row = await (await request.get(`/api/revisions/${state.revision}`)).json();
    test.skip(!row.result?.report?.casting_box, "Current model is not a casting box");
    if (fallback) {
      await page.addInitScript(() => {
        const original = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
          if (type.includes("webgl")) return null;
          return Reflect.apply(original, this, [type, ...args]);
        } as typeof original;
      });
    }
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/");
    await expect(page.locator("#viewport")).toHaveAttribute("data-revision", state.revision);
    await expect(page.locator("#parts .part")).toHaveCount(Object.keys(row.result.report.parts).length);
    await page.getByRole("button", {name:"Explode",exact:true}).click();
    await expect(page.locator("#explode")).toHaveText("Assemble");
    if (fallback) {
      const image = page.getByAltText("Server-rendered CAD model preview");
      await expect(image).toHaveAttribute("src", /render-exploded\.png$/);
      await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    }
    const fileType = page.getByLabel("File type", {exact:true});
    const exportKeys = Object.keys(row.result.exports);
    const formats = [...new Set(exportKeys.map(key => key.split(":")[0]))].sort();
    await expect(fileType.locator("option")).toHaveCount(formats.length + 1);
    for (const format of formats) {
      await fileType.selectOption(format);
      const matching = exportKeys.filter(key => key.split(":")[0] === format).length;
      await expect(page.locator("#exports a:visible")).toHaveCount(matching);
      await expect(page.locator(`#exports a:visible:not([data-file-type="${format}"])`)).toHaveCount(0);
      await expect(page.locator("#export-count")).toHaveText(`${matching} file${matching === 1 ? "" : "s"}`);
    }
    await fileType.selectOption("");
    await expect(page.locator("#exports a:visible")).toHaveCount(exportKeys.length);
    await fileType.selectOption("zip");
    const download = page.getByRole("link", {name:"ZIP · casting box",exact:true});
    const response = await request.get((await download.getAttribute("href"))!);
    expect(response.ok()).toBe(true);
    expect((await response.body()).subarray(0,2).toString()).toBe("PK");
    const waiting = page.waitForEvent("download");
    await download.click();
    const saved = await waiting;
    expect(saved.suggestedFilename()).toBe("casting-box.zip");
    expect(await saved.failure()).toBeNull();
    const stream = await saved.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
    expect(Buffer.concat(chunks).equals(await response.body())).toBe(true);
    await page.getByRole("button", {name:"Assemble",exact:true}).click();
    expect((await (await request.get("/api/state")).json()).generation).toBe(state.generation);
    expect(errors).toEqual([]);
  });
}
