"use client";

import { useState, useEffect, useCallback, useSyncExternalStore } from "react";
import api from "@/lib/api";
import { getSfAccount, subscribeSfAccount, withSfAccount } from "@/lib/sf-account";

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

// Pages pass `refresh=<click count>`. Each click recomputes each endpoint
// once; after that the endpoint reads the cache again. (A sticky
// refresh=true made every later visit skip the cache and recompute live.)
const consumedRefresh = new Map<string, number>();

export function resolveRefresh(url: string): string {
  const m = url.match(/[?&]refresh=(\d+)/);
  if (!m) return url;
  const clicks = Number(m[1]);
  const key = url.replace(/[?&]refresh=\d+/, "");
  const fresh = clicks > 0 && consumedRefresh.get(key) !== clicks;
  if (fresh) consumedRefresh.set(key, clicks);
  return url.replace(/([?&])refresh=\d+/, `$1refresh=${fresh}`);
}

export function useApi<T>(
  url: string | null,
  deps: unknown[] = []
): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [trigger, setTrigger] = useState(0);

  const refetch = useCallback(() => setTrigger((t) => t + 1), []);
  // Snowflake pages follow the account picked in the sidebar.
  const account = useSyncExternalStore(subscribeSfAccount, getSfAccount, () => "");
  const fullUrl = url ? withSfAccount(url, account) : null;

  useEffect(() => {
    if (!url) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    api
      .get(resolveRefresh(fullUrl ?? url))
      .then((res: unknown) => {
        if (!cancelled) {
          setData(res as T);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(typeof err === "string" ? err : "Failed to load data");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullUrl, trigger, ...deps]);

  return { data, loading, error, refetch };
}
