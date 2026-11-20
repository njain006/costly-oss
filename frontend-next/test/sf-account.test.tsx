// Every request goes to the Snowflake account picked in the sidebar, and the
// switcher always shows the account the pages are using.
import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { render } from "@testing-library/react";
import api from "@/lib/api";
import { getSfAccount, setSfAccount } from "@/lib/sf-account";
import SfAccountSwitcher from "@/components/sf-account-switcher";

const seen: string[] = [];
const realAdapter = api.defaults.adapter;
api.defaults.adapter = async (config) => {
  seen.push(config.url || "");
  return { data: {}, status: 200, statusText: "OK", headers: {}, config };
};
afterAll(() => {
  api.defaults.adapter = realAdapter;
});

describe("requests carry the selected Snowflake account", () => {
  beforeEach(() => {
    seen.length = 0;
    localStorage.clear();
    setSfAccount("");
  });

  it("adds connection_id to Snowflake writes as well as reads", async () => {
    setSfAccount("B");
    await api.post("/warehouses/WH/resize", { new_size: "SMALL" });
    await api.post("/warehouses/WH/autosuspend", { seconds: 60 });
    await api.post("/optimization/warehouses/WH/suspend");
    await api.post("/sync/queries?days=7");
    await api.post("/chat", { messages: [] });
    await api.get("/dashboard?days=30");
    expect(seen).toEqual([
      "/warehouses/WH/resize?connection_id=B",
      "/warehouses/WH/autosuspend?connection_id=B",
      "/optimization/warehouses/WH/suspend?connection_id=B",
      "/sync/queries?days=7&connection_id=B",
      "/chat?connection_id=B",
      "/dashboard?days=30&connection_id=B",
    ]);
  });

  it("leaves other paths, explicit ids and no selection alone", async () => {
    setSfAccount("B");
    await api.put("/platforms/X/user-types", {});
    await api.post("/auth/login", {});
    await api.get("/dashboard?connection_id=A");
    setSfAccount("");
    await api.post("/warehouses/WH/resize", {});
    expect(seen).toEqual([
      "/platforms/X/user-types",
      "/auth/login",
      "/dashboard?connection_id=A",
      "/warehouses/WH/resize",
    ]);
  });

  it("demo mode still goes to /demo", async () => {
    setSfAccount("B");
    localStorage.setItem("costly_demo", "1");
    await api.get("/dashboard");
    expect(seen).toEqual(["/demo/dashboard"]);
  });
});

describe("account switcher", () => {
  beforeEach(() => setSfAccount(""));
  const two = [{ id: "A", name: "a" }, { id: "B", name: "b" }];

  it("pins the shown account when nothing is saved", () => {
    render(<SfAccountSwitcher accounts={two} />);
    expect(getSfAccount()).toBe("A");
  });

  it("keeps a valid saved choice", () => {
    setSfAccount("B");
    render(<SfAccountSwitcher accounts={two} />);
    expect(getSfAccount()).toBe("B");
  });

  it("replaces a removed account", () => {
    setSfAccount("GONE");
    render(<SfAccountSwitcher accounts={two} />);
    expect(getSfAccount()).toBe("A");
  });

  it("goes back to the backend default when one account is left", () => {
    setSfAccount("GONE");
    render(<SfAccountSwitcher accounts={[{ id: "A", name: "a" }]} />);
    expect(getSfAccount()).toBe("");
  });

  it("does nothing while accounts are loading", () => {
    setSfAccount("B");
    render(<SfAccountSwitcher accounts={[]} />);
    expect(getSfAccount()).toBe("B");
  });
});
