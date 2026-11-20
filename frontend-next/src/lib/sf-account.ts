// Which Snowflake account the Snowflake pages show. Shared by the sidebar
// switcher and useApi, kept per browser. Empty means "the backend's default"
// (the most recently synced account), which is right for single-account users.

const KEY = "costly_sf_connection";
const listeners = new Set<() => void>();
let current: string | null = null;

function read(): string {
  if (current !== null) return current;
  try {
    current = (typeof window !== "undefined" && window.localStorage.getItem(KEY)) || "";
  } catch {
    current = "";
  }
  return current;
}

export function getSfAccount(): string {
  return read();
}

export function setSfAccount(id: string): void {
  current = id;
  try {
    if (id) window.localStorage.setItem(KEY, id);
    else window.localStorage.removeItem(KEY);
  } catch {
    /* private mode: selection lasts for this tab only */
  }
  listeners.forEach((l) => l());
}

export function subscribeSfAccount(l: () => void): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}

// Endpoints that read one Snowflake account (see backend routers using
// get_data_source). Everything else is account-independent.
const SNOWFLAKE_PATHS = [
  "/dashboard", "/costs", "/cost-attribution", "/queries", "/storage", "/stale-tables",
  "/warehouses", "/spillage", "/query-patterns", "/workloads", "/recommendations",
  "/history", "/optimization", "/chat", "/sync",
];

export function withSfAccount(url: string, account: string): string {
  if (!account) return url;
  const path = url.split("?")[0];
  if (!SNOWFLAKE_PATHS.some((p) => path === p || path.startsWith(p + "/"))) return url;
  if (/[?&]connection_id=/.test(url)) return url;
  return url + (url.includes("?") ? "&" : "?") + `connection_id=${encodeURIComponent(account)}`;
}
