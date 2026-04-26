/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";

/**
 * Vitest config for the Next.js frontend.
 *
 * - happy-dom: lighter than jsdom and sufficient for the components we test.
 * - tsconfigPaths: resolves the `@/*` alias from `tsconfig.json`.
 * - react plugin: handles JSX + Fast Refresh in test files.
 *
 * Coverage uses the v8 provider (no babel instrumentation) and writes both
 * an HTML report and an lcov file for CI artifact upload.
 */
export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    include: [
      "src/**/*.{test,spec}.{ts,tsx}",
      "test/**/*.{test,spec}.{ts,tsx}",
    ],
    exclude: ["node_modules", ".next", "e2e", "playwright-report"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov", "json-summary"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        "src/**/*.test.{ts,tsx}",
        "src/**/*.spec.{ts,tsx}",
        "src/app/**/layout.tsx",
        "src/app/**/loading.tsx",
        "src/app/**/error.tsx",
        "src/app/**/not-found.tsx",
        "src/components/ui/**",
      ],
      thresholds: {
        // Initial floor — ratchet up over time.
        lines: 30,
        functions: 30,
        statements: 30,
        branches: 50,
      },
    },
  },
});
