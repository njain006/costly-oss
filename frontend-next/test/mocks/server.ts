/**
 * MSW Node server for unit tests.
 *
 * Lifecycle hooks live in `vitest.setup.ts`. Tests can call
 * `server.use(...)` inside an `it`/`beforeEach` block to override defaults
 * for a single suite without leaking handlers between tests
 * (the `resetHandlers` call in setup snaps everything back to defaults).
 */
import { setupServer } from "msw/node";
import { defaultHandlers } from "./handlers";

export const server = setupServer(...defaultHandlers);
