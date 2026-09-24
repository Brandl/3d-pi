import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("live publication, camera controls, last-good model, restore, reconnect", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Legacy publication behaviour needs a project without a working-design head.
  // Never make this test depend on (or overwrite) the workspace fixtures.
  const project = await (await request.post('/api/projects', {data:{name:`Viewer regression ${randomUUID().slice(0,8)}`}})).json();
  const scoped = (path:string) => `/projects/${project.id}${path}`;
  const initial = await (await request.get(scoped("/api/state"))).json();
  const doc = await (await request.get("/api/example")).json();
  async function build(document: unknown, generation: number) {
    const response = await request.post(scoped("/api/builds"), {
      data: {
        document,
        expected_generation: generation,
        request_key: randomUUID(),
      },
    });
    expect(response.status()).toBe(202);
    const row = await response.json();
    let result: any;
    await expect
      .poll(
        async () => {
          result = await (await request.get(scoped(`/api/revisions/${row.id}`))).json();
          return ["queued", "building"].includes(result.status);
        },
        { timeout: 110000, intervals: [250, 500] },
      )
      .toBe(false);
    return result;
  }
  await page.goto(`/?project=${project.id}`);
  await expect(page.locator("#connection")).toContainText("Live");
  const first = await build(doc, initial.generation);
  expect(first.status).toBe("ready");
  expect(
    (
      await request.post(scoped(`/api/revisions/${first.id}/publish`), {
        data: { expected_generation: initial.generation },
      })
    ).status(),
  ).toBe(200);
  await expect(page.locator("#viewport")).toHaveAttribute(
    "data-revision",
    first.id,
  );
  await expect(page.locator("#parts .part")).toHaveCount(2);
  await expect(page.locator("#exports a")).toHaveCount(4);
  await expect(page.locator("#empty")).toBeHidden();
  await page.getByRole("button", { name: "Top" }).click();
  await page.keyboard.press("1");
  await page.getByRole("button", { name: "Fit" }).click();
  doc.parameters.wall = 3;
  doc.parameters.hole_offset = 10;
  const second = await build(doc, initial.generation + 1);
  expect(second.status).toBe("ready");
  await expect(page.locator("#viewport")).toHaveAttribute(
    "data-revision",
    first.id,
  );
  expect(
    (
      await request.post(scoped(`/api/revisions/${second.id}/publish`), {
        data: { expected_generation: initial.generation + 1 },
      })
    ).status(),
  ).toBe(200);
  await expect(page.locator("#viewport")).toHaveAttribute(
    "data-revision",
    second.id,
  );
  doc.parameters.wall = 100;
  const failure = await build(doc, initial.generation + 2);
  expect(failure.status).toBe("failed");
  await expect(page.locator("#notice")).toContainText("failed");
  await expect(page.locator("#viewport")).toHaveAttribute(
    "data-revision",
    second.id,
  );
  expect(
    (
      await request.post(scoped(`/api/revisions/${first.id}/restore`), {
        data: { expected_generation: initial.generation + 2 },
      })
    ).status(),
  ).toBe(200);
  await expect(page.locator("#viewport")).toHaveAttribute(
    "data-revision",
    first.id,
  );
  await page.reload();
  await expect(page.locator("#viewport")).toHaveAttribute(
    "data-revision",
    first.id,
  );
  await page.screenshot({ path: "test-results/viewer.png" });
  expect(errors).toEqual([]);
});
