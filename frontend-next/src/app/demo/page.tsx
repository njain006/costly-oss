"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/auth-provider";

export default function DemoEntryPage() {
  const { enterDemo } = useAuth();
  const router = useRouter();

  useEffect(() => {
    enterDemo();
    router.replace("/overview");
  }, [enterDemo, router]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="text-center">
        <div className="animate-spin h-8 w-8 border-4 border-indigo-600 border-t-transparent rounded-full mx-auto mb-4" />
        <p className="text-slate-600 text-sm">Loading demo...</p>
      </div>
    </div>
  );
}
