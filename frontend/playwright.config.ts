import { resolve } from "node:path"
import { defineConfig, devices } from "@playwright/test"

const port = process.env.E2E_PORT || "18940"
const baseURL = `http://localhost:${port}`
const python = resolve(import.meta.dirname, "..", ".venv", "bin", "python")

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: "list",
  use: {
    baseURL,
    actionTimeout: 15_000,
    screenshot: { mode: "only-on-failure", fullPage: true },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: {
    command: `"${python}" backend/tests/browser_server.py`,
    cwd: resolve(import.meta.dirname, ".."),
    env: { PYTHONPATH: "backend", E2E_PORT: port },
    url: `${baseURL}/api/health`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
