/**
 * Mock Service Worker request handlers.
 *
 * Source of truth: `backend/app/routers/*.py`. These handlers cover the
 * `/api/*` endpoints that the components under test reach for. When you add
 * a new API call to a component, add a default handler here so the component
 * can render in isolation; per-test overrides via `server.use(...)` are
 * preferred over editing this file for one-off cases.
 *
 * The frontend axios client uses baseURL `/api`, but jsdom/happy-dom needs
 * absolute URLs, so handlers use the wildcard host pattern `*\/api/...`.
 */
import { http, HttpResponse } from "msw";

const API = "*/api";

export const defaultHandlers = [
  // ─── connections ─────────────────────────────────────────────────
  http.get(`${API}/connections/status`, () =>
    HttpResponse.json({ has_connection: false }),
  ),
  http.get(`${API}/connections`, () => HttpResponse.json([])),

  // ─── anomalies ───────────────────────────────────────────────────
  http.get(`${API}/anomalies`, () =>
    HttpResponse.json({ anomalies: [], count: 0, unacknowledged: 0 }),
  ),
  http.post(`${API}/anomalies/detect`, () =>
    HttpResponse.json({ ok: true, count: 0 }),
  ),
  http.post(`${API}/anomalies/:id/acknowledge`, () =>
    HttpResponse.json({ ok: true }),
  ),

  // ─── unified costs / platforms ───────────────────────────────────
  http.get(`${API}/platforms/costs`, () =>
    HttpResponse.json({
      total_cost: 0,
      daily_trend: [],
      by_platform: [],
      demo: false,
    }),
  ),
  http.get(`${API}/platforms`, () => HttpResponse.json([])),

  // ─── dashboard / costs ───────────────────────────────────────────
  http.get(`${API}/dashboard`, () =>
    HttpResponse.json({
      total_cost: 0,
      total_credits: 0,
      query_count: 0,
      avg_query_seconds: 0,
      daily_trend: [],
    }),
  ),
  http.get(`${API}/costs`, () =>
    HttpResponse.json({ total: 0, daily_trend: [] }),
  ),

  // ─── auth (used by axios refresh interceptor) ────────────────────
  http.post(`${API}/auth/refresh`, () =>
    HttpResponse.json({
      token: "fake-token",
      refresh_token: "fake-refresh",
      user_id: "u1",
      name: "Test User",
      email: "test@example.com",
      role: "user",
    }),
  ),

  // ─── catch-all for anything else under /api ──────────────────────
  // Returns 200 + {} so unmocked GETs don't blow up tests with surprise 500s.
  // Tests that depend on a specific shape MUST set their own handler.
  http.get(`${API}/*`, () => HttpResponse.json({})),
];
