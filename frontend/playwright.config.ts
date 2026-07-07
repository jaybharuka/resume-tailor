import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 20 * 60 * 1000,
  use: {
    baseURL: "http://localhost:3100",
  },
});
