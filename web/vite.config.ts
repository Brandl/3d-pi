import { defineConfig } from "vite";
const origin = process.env.CAD_DEV_ORIGIN ?? "http://127.0.0.1:8765";
export default defineConfig({
  server: {
    proxy: {
      "/api": { target: origin, ws: true },
      "/downloads": { target: origin },
      "/auth": { target: origin },
    },
  },
});
