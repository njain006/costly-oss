/**
 * Global test setup for Vitest.
 *
 * - Loads `@testing-library/jest-dom` matchers (`toBeInTheDocument`, etc.).
 * - Cleans up the DOM between tests.
 * - Boots an MSW server for network mocking; tests can override handlers per-suite.
 * - Mocks `next/navigation` and `next/link` so client components that import
 *   them work without a real Next.js runtime.
 * - Polyfills the things happy-dom doesn't ship by default (matchMedia,
 *   ResizeObserver) — Recharts and Radix both rely on these.
 */
import "@testing-library/jest-dom/vitest";
import * as React from "react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./test/mocks/server";

// ─── MSW lifecycle ──────────────────────────────────────────────────
beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  // Wipe storage so tests stay isolated.
  if (typeof window !== "undefined") {
    window.localStorage.clear();
    window.sessionStorage.clear();
  }
});
afterAll(() => server.close());

// ─── next/navigation mock ───────────────────────────────────────────
vi.mock("next/navigation", () => {
  const router = {
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  };
  return {
    useRouter: () => router,
    usePathname: () => "/",
    useSearchParams: () => new URLSearchParams(),
    redirect: vi.fn(),
    notFound: vi.fn(),
  };
});

// ─── next/link mock ─────────────────────────────────────────────────
// Minimal pass-through so <Link href="...">x</Link> renders an <a>. We use
// React.createElement to keep this file JSX-free. The factory closes over
// the top-level `React` import — Vitest hoists `vi.mock` registration but
// invokes the factory lazily at import time, by which point `React` is
// resolved.
vi.mock("next/link", async () => {
  const ReactMod = await import("react");
  return {
    default: ({
      href,
      children,
      ...rest
    }: {
      href: string;
      children: React.ReactNode;
    } & Record<string, unknown>) =>
      ReactMod.createElement("a", { href, ...rest }, children),
  };
});

// ─── happy-dom polyfills ────────────────────────────────────────────
if (typeof window !== "undefined") {
  // matchMedia — used by tailwind responsive helpers and some Radix primitives.
  if (!window.matchMedia) {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }

  // ResizeObserver — Recharts <ResponsiveContainer> needs this.
  if (!("ResizeObserver" in window)) {
    class MockResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).ResizeObserver = MockResizeObserver;
  }

  // IntersectionObserver — used by some Radix primitives.
  if (!("IntersectionObserver" in window)) {
    class MockIntersectionObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (window as any).IntersectionObserver = MockIntersectionObserver;
  }
}
