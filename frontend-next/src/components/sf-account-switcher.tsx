"use client";

import { useEffect, useSyncExternalStore } from "react";
import { getSfAccount, setSfAccount, subscribeSfAccount } from "@/lib/sf-account";

// Shown only when the user has more than one Snowflake account.
export default function SfAccountSwitcher({ accounts }: { accounts: { id: string; name: string }[] }) {
  const selected = useSyncExternalStore(subscribeSfAccount, getSfAccount, () => "");

  // Forget a selection that no longer exists (account removed).
  useEffect(() => {
    if (selected && accounts.length && !accounts.some((a) => a.id === selected)) setSfAccount("");
  }, [selected, accounts]);

  if (accounts.length < 2) return null;
  return (
    <div className="px-3 pb-1.5 pt-0.5">
      <label htmlFor="sf-account" className="sr-only">Snowflake account</label>
      <select
        id="sf-account"
        value={selected || accounts[0].id}
        onChange={(e) => setSfAccount(e.target.value)}
        className="w-full rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500"
      >
        {accounts.map((a) => (
          <option key={a.id} value={a.id} className="text-slate-900">
            {a.name}
          </option>
        ))}
      </select>
    </div>
  );
}
