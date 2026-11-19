"use client";

import { useSyncExternalStore } from "react";

// Filter Snowflake users into service accounts vs people. One choice shared
// by every page, remembered per browser.
export type UserTypeFilterValue = "all" | "service" | "human";

const KEY = "costly_user_type_filter";
const listeners = new Set<() => void>();
let current: UserTypeFilterValue | null = null;

function get(): UserTypeFilterValue {
  if (current) return current;
  try {
    const v = typeof window !== "undefined" ? window.localStorage.getItem(KEY) : null;
    current = v === "service" || v === "human" ? v : "all";
  } catch {
    current = "all";
  }
  return current;
}

function set(v: UserTypeFilterValue) {
  current = v;
  try {
    window.localStorage.setItem(KEY, v);
  } catch {
    /* private mode */
  }
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

export function useUserTypeFilter(): UserTypeFilterValue {
  return useSyncExternalStore(subscribe, get, () => "all");
}

/** Keep rows whose type matches the filter. Rows without a type count as people. */
export function filterByUserType<T>(rows: T[], filter: UserTypeFilterValue, typeOf: (r: T) => string | undefined): T[] {
  if (filter === "all") return rows;
  return rows.filter((r) => (typeOf(r) ?? "human") === filter);
}

const OPTIONS: { value: UserTypeFilterValue; label: string }[] = [
  { value: "all", label: "Everyone" },
  { value: "service", label: "Service accounts" },
  { value: "human", label: "People" },
];

export default function UserTypeFilter({ className = "" }: { className?: string }) {
  const value = useUserTypeFilter();
  return (
    <div role="radiogroup" aria-label="Show users" className={`inline-flex rounded-md border bg-white p-0.5 text-xs ${className}`}>
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => set(o.value)}
          className={`rounded px-2.5 py-1 transition-colors ${
            value === o.value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
