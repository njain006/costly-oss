/**
 * Shared types for e2e fixtures and helpers.
 *
 * Kept tiny on purpose — the goal is to avoid coupling the e2e suite to
 * production app types. If a backend response shape changes, only the
 * narrow type used by the fixture needs to follow.
 */

export interface DemoUser {
  user_id: string;
  name: string;
  email: string;
}

export interface SeededAnthropicConn {
  platform: "anthropic";
  /** Whether the demo data already includes Anthropic spend in /api/demo/ai-costs. */
  hasDemoCostsRendered: boolean;
}

export interface UniqueRegisteredUser {
  email: string;
  password: string;
  name: string;
}

/**
 * The deployed environment is read-only — anything that mutates server
 * state (register, login, real platform connect) must skip when this is
 * `true`.
 */
export const IS_PUBLIC_ONLY: boolean =
  process.env.PUBLIC_ONLY === "1" ||
  /costly\.cdatainsights\.com/.test(process.env.BASE_URL || "");
