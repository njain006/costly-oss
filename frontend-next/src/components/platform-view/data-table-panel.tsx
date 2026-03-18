"use client";

import { TableConfig } from "@/lib/platform-registry";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber, formatBytes, formatDuration } from "@/lib/format";

function formatCell(value: unknown, format?: string): string {
  if (value == null) return "—";
  const n = Number(value);
  switch (format) {
    case "currency": return formatCurrency(n);
    case "number": return formatNumber(n);
    case "bytes": return formatBytes(n);
    case "duration": return formatDuration(n);
    case "percent": return `${n.toFixed(1)}%`;
    case "text": {
      const s = String(value);
      return s.length > 80 ? s.slice(0, 80) + "…" : s;
    }
    default: return String(value);
  }
}

export function DataTablePanel({
  config,
  data,
  loading,
}: {
  config: TableConfig;
  data: unknown[] | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">{config.title}</CardTitle></CardHeader>
        <CardContent><Skeleton className="h-48" /></CardContent>
      </Card>
    );
  }

  if (!data || !Array.isArray(data) || data.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">{config.title}</CardTitle></CardHeader>
        <CardContent>
          <div className="h-24 flex items-center justify-center text-sm text-slate-400">No data available</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">{config.title}</CardTitle></CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              {config.columns.map((col) => (
                <TableHead key={col.key} className={col.align === "right" ? "text-right" : ""}>
                  {col.label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data as Record<string, unknown>[]).slice(0, 50).map((row, i) => (
              <TableRow key={i}>
                {config.columns.map((col) => (
                  <TableCell key={col.key} className={`${col.align === "right" ? "text-right" : ""} ${col.format === "text" ? "max-w-[300px] truncate font-mono text-xs" : ""}`}>
                    {formatCell(row[col.key], col.format)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
