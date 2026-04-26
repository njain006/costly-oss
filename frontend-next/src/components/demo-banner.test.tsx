/**
 * Component tests for `<DemoBanner />`.
 *
 * The banner has three render paths:
 *   1. Demo mode active   → CTA "Sign Up Free" banner.
 *   2. Authed but no SF connection → amber "Demo Mode" alert.
 *   3. Authed + connection present → renders nothing.
 *
 * `<DemoBanner />` reads `isDemo` from auth context and calls
 * `/connections/status` for path #2/#3, so we drive both the AuthProvider
 * and an MSW override per test.
 */
import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "../../test/mocks/server";
import DemoBanner from "./demo-banner";
import { AuthProvider } from "@/providers/auth-provider";

function renderInDemoMode() {
  window.localStorage.setItem("costly_demo", "1");
  return render(
    <AuthProvider>
      <DemoBanner />
    </AuthProvider>,
  );
}

function renderAuthed() {
  return render(
    <AuthProvider>
      <DemoBanner />
    </AuthProvider>,
  );
}

describe("<DemoBanner />", () => {
  it("renders the public-demo CTA banner when in demo mode", () => {
    renderInDemoMode();
    expect(
      screen.getByText(/viewing a live demo with sample data/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign up free/i }),
    ).toBeInTheDocument();
  });

  it("renders the amber 'Demo Mode' alert when authed but no connection", async () => {
    server.use(
      http.get("*/api/connections/status", () =>
        HttpResponse.json({ has_connection: false }),
      ),
    );
    renderAuthed();
    await waitFor(() => {
      expect(screen.getByText(/Demo Mode/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/Connect your data platforms in Settings/i),
    ).toBeInTheDocument();
  });

  it("renders nothing when authed and a connection exists", async () => {
    server.use(
      http.get("*/api/connections/status", () =>
        HttpResponse.json({ has_connection: true }),
      ),
    );
    const { container } = renderAuthed();
    // Wait for any async render to settle, then assert nothing visible.
    await new Promise((r) => setTimeout(r, 30));
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/Demo Mode/);
  });
});
