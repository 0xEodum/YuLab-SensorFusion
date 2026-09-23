import { defineConfig } from "@playwright/test";

const backendPort = process.env.YULAB_TEST_BACKEND_PORT ?? "8765";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 90_000,
  globalTimeout: 600_000,
  workers: 1,
  reporter: [
    ["list"],
    ["json", { outputFile: "artifacts/browser/results.json" }],
  ],
  use: {
    channel: process.env.PLAYWRIGHT_CHANNEL,
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: {
      args:
        process.env.PLAYWRIGHT_GPU === "1"
          ? []
          : ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
  webServer: [
    {
      command:
        `node tools/uv.mjs run --project backend --locked uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port ${backendPort}`,
      url: `http://127.0.0.1:${backendPort}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command:
        process.env.PLAYWRIGHT_TEST_BUILT === "1"
          ? "npm run preview -- --port 4173 --strictPort"
          : "npm run dev -- --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
      timeout: 30_000,
      env: { YULAB_BACKEND_PORT: backendPort },
    },
  ],
});
