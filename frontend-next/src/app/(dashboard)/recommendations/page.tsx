"use client";

import LoadError from "@/components/load-error";

import { useState } from "react";
import { useApi } from "@/hooks/use-api";
import api from "@/lib/api";
import DemoBanner from "@/components/demo-banner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatCurrency } from "@/lib/format";
import { Lightbulb, DollarSign, Warehouse, Zap, HardDrive, Copy, Play } from "lucide-react";

interface Recommendation {
  id: string;
  title: string;
  description: string;
  category: string;
  potential_savings: number | null;
  effort: string;
  priority: string;
  ddl_command?: string;
  current_value?: number;
}

const categoryIcons: Record<string, typeof Warehouse> = {
  warehouse: Warehouse,
  query: Zap,
  storage: HardDrive,
  info: Lightbulb,
};

const priorityColors: Record<string, "destructive" | "default" | "secondary"> = {
  high: "destructive",
  medium: "default",
  low: "secondary",
};

export default function RecommendationsPage() {
  const { data, loading, error: loadError } = useApi<Recommendation[]>("/recommendations");
  const totalSavings = data?.reduce((sum, r) => sum + (r.potential_savings || 0), 0) || 0;
  // One script with every fix, biggest saving first, so the whole plan can
  // be reviewed and run in a single Snowsight worksheet.
  const planRecs = (data || [])
    .filter((r) => r.ddl_command)
    .sort((a, b) => (b.potential_savings || 0) - (a.potential_savings || 0));
  const planSql = planRecs.length
    ? [
        "-- Review each line, then run in Snowsight as the warehouse owner.",
        "-- To undo a line, run the commented revert next to it.",
        ...planRecs.map((r) => {
          const m = r.ddl_command!.match(/ALTER WAREHOUSE (\S+) SET AUTO_SUSPEND/i);
          const was = (r as Recommendation & { current_value?: number }).current_value;
          const save = r.potential_savings ? `  -- saves ~$${Math.round(r.potential_savings)}/mo` : "  -- test, then compare idle %";
          const revert = m && was ? `\n-- revert: ALTER WAREHOUSE ${m[1]} SET AUTO_SUSPEND = ${was};` : "";
          return `${r.ddl_command}${save}${revert}`;
        }),
      ].join("\n")
    : "";

  const [ddlDialog, setDdlDialog] = useState<{ open: boolean; ddl: string; recId: string }>({
    open: false, ddl: "", recId: "",
  });
  const [executing, setExecuting] = useState(false);
  const [execResult, setExecResult] = useState<{ success: boolean; message: string } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const copyDdl = async (ddl: string, recId: string) => {
    try {
      await navigator.clipboard.writeText(ddl);
      setCopied(recId);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      // fallback
    }
  };

  const executeDdl = async () => {
    setExecuting(true);
    setExecResult(null);
    try {
      // Parse the DDL to determine the type
      const ddl = ddlDialog.ddl;
      if (ddl.includes("WAREHOUSE_SIZE")) {
        const match = ddl.match(/ALTER WAREHOUSE (\S+) SET WAREHOUSE_SIZE = '([^']+)'/i);
        if (match) {
          const res = await api.post(`/warehouses/${match[1]}/resize`, { new_size: match[2] }) as { success: boolean; error?: string };
          setExecResult({ success: res.success, message: res.success ? "Executed successfully" : (res.error || "Failed") });
        }
      } else if (ddl.includes("AUTO_SUSPEND")) {
        const match = ddl.match(/ALTER WAREHOUSE (\S+) SET AUTO_SUSPEND = (\d+)/i);
        if (match) {
          const res = await api.post(`/warehouses/${match[1]}/autosuspend`, { seconds: parseInt(match[2]) }) as { success: boolean; error?: string };
          setExecResult({ success: res.success, message: res.success ? "Executed successfully" : (res.error || "Failed") });
        }
      } else {
        setExecResult({ success: false, message: "This DDL type cannot be executed from the UI" });
      }
    } catch (err) {
      setExecResult({ success: false, message: String(err) });
    }
    setExecuting(false);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Recommendations</h1>
      </div>
      <DemoBanner />

      <LoadError error={loadError} />
      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 rounded-lg" />
          ))}
        </div>
      ) : data ? (
        <>
          {totalSavings > 0 && (
            <Card className="mb-6 bg-emerald-50 border-emerald-200">
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-lg bg-emerald-100 flex items-center justify-center">
                  <DollarSign className="h-6 w-6 text-emerald-600" />
                </div>
                <div>
                  <div className="text-sm text-emerald-700">Potential Monthly Savings</div>
                  <div className="text-3xl font-bold text-emerald-800">{formatCurrency(totalSavings)}</div>
                </div>
              </CardContent>
            </Card>
          )}

          {planSql && (
            <Card className="mb-6 border-sky-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Action plan: {planRecs.length} changes{totalSavings > 0 ? `, ~${formatCurrency(totalSavings)}/month` : ""}</CardTitle>
                <p className="text-xs text-muted-foreground">Every change with a known current setting, biggest saving first, each with its revert line. Copy into a Snowsight worksheet, review, run.</p>
              </CardHeader>
              <CardContent>
                <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs font-mono overflow-x-auto mb-2 whitespace-pre">{planSql}</pre>
                <Button size="sm" variant="outline" onClick={() => copyDdl(planSql, "__plan")}>
                  <Copy className="h-3 w-3 mr-1" />
                  {copied === "__plan" ? "Copied!" : "Copy full script"}
                </Button>
              </CardContent>
            </Card>
          )}

          <div className="space-y-4">
            {data.map((rec) => {
              const Icon = categoryIcons[rec.category] || Lightbulb;
              return (
                <Card key={rec.id}>
                  <CardHeader className="pb-2">
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3">
                        <div className="h-9 w-9 rounded-lg bg-sky-50 flex items-center justify-center mt-0.5">
                          <Icon className="h-4 w-4 text-sky-600" />
                        </div>
                        <div>
                          <CardTitle className="text-base">{rec.title}</CardTitle>
                          <div className="flex items-center gap-2 mt-1">
                            <Badge variant={priorityColors[rec.priority] || "secondary"} className="text-xs">
                              {rec.priority}
                            </Badge>
                            <Badge variant="outline" className="text-xs">{rec.effort} effort</Badge>
                            {rec.potential_savings != null && rec.potential_savings > 0 && (
                              <Badge variant="outline" className="text-xs text-emerald-600 border-emerald-200">
                                Save {formatCurrency(rec.potential_savings)}/mo
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm text-muted-foreground leading-relaxed mb-3">{rec.description}</p>
                    {rec.ddl_command && (
                      <div className="mt-3">
                        <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs font-mono overflow-x-auto mb-2">
                          {rec.ddl_command}
                        </pre>
                        <div className="flex items-center gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => copyDdl(rec.ddl_command!, rec.id)}
                          >
                            <Copy className="h-3 w-3 mr-1" />
                            {copied === rec.id ? "Copied!" : "Copy SQL"}
                          </Button>
                          <span className="text-xs text-muted-foreground">Review, then run in Snowsight as the warehouse owner.</span>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </>
      ) : null}

      {/* DDL Execution Dialog */}
      <Dialog open={ddlDialog.open} onOpenChange={(open) => {
        if (!open) {
          setDdlDialog({ open: false, ddl: "", recId: "" });
          setExecResult(null);
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm DDL Execution</DialogTitle>
            <DialogDescription>
              The following SQL command will be executed on your connected warehouse:
            </DialogDescription>
          </DialogHeader>
          <pre className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-sm font-mono overflow-x-auto">
            {ddlDialog.ddl}
          </pre>
          {execResult && (
            <div className={`rounded-lg p-3 text-sm ${execResult.success ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"}`}>
              {execResult.message}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => {
              setDdlDialog({ open: false, ddl: "", recId: "" });
              setExecResult(null);
            }}>
              Cancel
            </Button>
            {!execResult?.success && (
              <Button onClick={executeDdl} disabled={executing}>
                {executing ? "Executing..." : "Execute"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
