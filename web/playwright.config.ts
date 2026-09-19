import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 120000,
  use: {
    baseURL: process.env.CAD_URL ?? "http://127.0.0.1:8765",
    viewport: { width: 1440, height: 960 },
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
  },
});
