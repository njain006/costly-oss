"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/providers/auth-provider";
import {
  DollarSign,
  Lightbulb,
  Bell,
  Settings,
  LogOut,
  Shield,
  ArrowRight,
  MessageSquare,
  Globe,
  Link2,
  Sparkles,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useApi } from "@/hooks/use-api";
import { PLATFORM_REGISTRY, getViewPath, isPathInPlatform, type PlatformRegistryEntry } from "@/lib/platform-registry";

interface SidebarSection {
  entry: PlatformRegistryEntry;
  connected: boolean;
}

export default function Sidebar() {
  const { user, isDemo, logout, exitDemo } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const { data: connections } = useApi<{ id: string; platform?: string }[]>(
    !isDemo && user ? "/platforms" : null
  );
  const { data: sfStatus } = useApi<{ has_connection: boolean }>(
    !isDemo && user ? "/connections/status" : null
  );
  const showOnboarding = !isDemo && user && (!connections || connections.length === 0) && !sfStatus?.has_connection;

  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(["snowflake"]));

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Build platform sections: only show connected platforms (+ all in demo mode)
  const sections: SidebarSection[] = useMemo(() => {
    const connectedPlatforms = new Set(
      (connections ?? []).map((c) => c.platform).filter(Boolean)
    );
    if (sfStatus?.has_connection) connectedPlatforms.add("snowflake");

    const result: SidebarSection[] = [];

    if (isDemo) {
      // Demo mode: show Snowflake + a few others to demonstrate the UI
      const demoPlatforms = ["snowflake", "aws", "openai", "dbt_cloud"];
      for (const key of demoPlatforms) {
        if (PLATFORM_REGISTRY[key]) {
          result.push({ entry: PLATFORM_REGISTRY[key], connected: true });
        }
      }
    } else {
      // Real users: only show platforms they've actually connected
      // Always show Snowflake if they have a Snowflake connection
      for (const [key, entry] of Object.entries(PLATFORM_REGISTRY)) {
        if (connectedPlatforms.has(key)) {
          result.push({ entry, connected: true });
        }
      }
    }

    return result;
  }, [connections, sfStatus, isDemo]);

  const handleLogout = () => {
    if (isDemo) {
      exitDemo();
      router.push("/");
    } else {
      logout();
      router.push("/");
    }
  };

  const navLink = (path: string, label: string, Icon: React.ElementType, indent = false) => (
    <Link
      key={path}
      href={path}
      className={cn(
        "flex items-center gap-2.5 py-1.5 rounded-md text-sm transition-colors",
        indent ? "px-3 pl-9" : "px-3",
        pathname === path
          ? "bg-sky-600/80 text-white font-semibold"
          : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
    </Link>
  );

  return (
    <aside className="fixed left-0 top-0 w-[220px] h-screen bg-gradient-to-b from-[#0B1929] to-[#0A1525] flex flex-col py-5 px-3 z-50 border-r border-white/5 overflow-y-auto">
      {/* Logo */}
      <div className="mb-5 px-1">
        <div className="flex items-center gap-2 text-white font-extrabold text-lg tracking-tight">
          <DollarSign className="h-5 w-5 text-sky-400" />
          costly
        </div>
        {isDemo ? (
          <div className="mt-3 p-2.5 bg-sky-500/10 border border-sky-500/20 rounded-lg">
            <div className="text-xs font-semibold text-sky-400 uppercase tracking-wider mb-1">
              Live Demo
            </div>
            <div className="text-[0.65rem] text-slate-400 leading-tight">
              Viewing sample data
            </div>
          </div>
        ) : user ? (
          <div className="mt-3 p-2.5 bg-white/5 rounded-lg">
            <div className="text-sm font-semibold text-slate-200 truncate">
              {user.name}
            </div>
            <div className="text-xs text-slate-500 truncate mt-0.5">
              {user.email}
            </div>
          </div>
        ) : null}
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5">
        {showOnboarding && (
          <>
            <Link
              href="/onboarding"
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors mb-1",
                pathname === "/onboarding"
                  ? "bg-sky-600/80 text-white font-semibold"
                  : "text-sky-400 hover:text-sky-300 hover:bg-sky-500/10 bg-sky-500/5 border border-sky-500/20"
              )}
            >
              <Sparkles className="h-4 w-4 shrink-0" />
              Get Started
            </Link>
            <Separator className="bg-white/5 my-2" />
          </>
        )}

        {/* Overview */}
        <div className="text-[0.65rem] font-bold text-slate-600 uppercase tracking-wider px-3 mb-2">
          Overview
        </div>
        {navLink("/overview", "All Platforms", Globe)}
        {navLink("/ai-costs", "AI Costs", Sparkles)}
        {navLink("/recommendations", "Recommendations", Lightbulb)}
        {navLink("/alerts", "Alerts", Bell)}

        <Separator className="bg-white/5 my-3" />

        {/* Platform Sections */}
        <div className="text-[0.65rem] font-bold text-slate-600 uppercase tracking-wider px-3 mb-2">
          Platforms
        </div>

        {sections.map(({ entry, connected }) => {
          const isActive = isPathInPlatform(pathname, entry);
          const isExpanded = expandedSections.has(entry.key) || isActive;
          const SectionIcon = entry.icon;

          if (!connected) return null;

          return (
            <div key={entry.key} className="mb-1">
              {/* Section header */}
              <button
                onClick={() => toggleSection(entry.key)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm transition-colors",
                  isActive
                    ? "text-sky-300"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
                )}
              >
                <SectionIcon className="h-4 w-4 shrink-0" />
                <span className="flex-1 text-left font-semibold">{entry.label}</span>
                {isExpanded
                  ? <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
                  : <ChevronRight className="h-3.5 w-3.5 text-slate-600" />}
              </button>

              {/* Section views */}
              {isExpanded && (
                <div className="mt-0.5 space-y-0.5">
                  {entry.views.map((view) => {
                    const path = getViewPath(entry, view.slug);
                    return navLink(path, view.label, view.icon, true);
                  })}
                </div>
              )}
            </div>
          );
        })}

        <Separator className="bg-white/5 my-3" />

        {/* Tools */}
        <div className="text-[0.65rem] font-bold text-slate-600 uppercase tracking-wider px-3 mb-2">
          Tools
        </div>
        {navLink("/chat", "Costly AI", MessageSquare)}
        {navLink("/platforms", "Connections", Link2)}
      </nav>

      {/* Bottom */}
      <Separator className="bg-white/5 my-3" />

      {isDemo ? (
        <>
          <Link
            href="/login"
            onClick={() => exitDemo()}
            className="flex items-center gap-2 px-3 py-2.5 bg-sky-600 rounded-lg text-white text-sm font-semibold hover:bg-sky-700 transition mb-2"
          >
            <ArrowRight className="h-4 w-4" />
            Sign Up Free
          </Link>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleLogout}
            className="justify-start gap-2.5 px-3 text-slate-500 hover:text-slate-300 hover:bg-transparent"
          >
            <LogOut className="h-4 w-4" />
            Exit Demo
          </Button>
        </>
      ) : (
        <>
          {user?.role === "admin" && (
            <Link
              href="/admin"
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors",
                pathname === "/admin"
                  ? "bg-sky-600/80 text-white font-semibold"
                  : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
              )}
            >
              <Shield className="h-4 w-4" />
              Admin
            </Link>
          )}
          <Link
            href="/settings"
            className={cn(
              "flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors",
              pathname === "/settings"
                ? "bg-sky-600/80 text-white font-semibold"
                : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
            )}
          >
            <Settings className="h-4 w-4" />
            Settings
          </Link>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleLogout}
            className="justify-start gap-2.5 px-3 text-slate-500 hover:text-red-400 hover:bg-transparent"
          >
            <LogOut className="h-4 w-4" />
            Logout
          </Button>
        </>
      )}
    </aside>
  );
}
