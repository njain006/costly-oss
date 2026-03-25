"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/auth-provider";
import { useApi } from "@/hooks/use-api";
import api from "@/lib/api";
import { formatCurrency, formatDuration } from "@/lib/format";
import StatCard from "@/components/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead,
  TableHeader, TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Users, Link2, Database, UserPlus, MoreHorizontal,
  ShieldCheck, ShieldOff, Ban, CheckCircle, Trash2,
} from "lucide-react";

interface AdminStats {
  total_users: number;
  total_connections: number;
  total_queries: number;
  recent_signups: number;
}

interface AdminUser {
  user_id: string;
  name?: string;
  email?: string;
  auth_provider?: string;
  created_at?: string;
  connection_count: number;
  role?: string;
  is_disabled?: boolean;
}

interface ActivityEvent {
  type: string;
  user_name?: string;
  user_email?: string;
  user_id?: string;
  account?: string;
  auth_provider?: string;
  timestamp?: string;
}

interface QuerySummary {
  total_queries: number;
  total_cost_usd: number;
  latest_query_date?: string;
}

interface UserDetail {
  user_id: string;
  name?: string;
  email?: string;
  auth_provider?: string;
  created_at?: string;
  role?: string;
  is_disabled?: boolean;
  connections: Array<{
    account?: string;
    warehouse?: string;
    created_at?: string;
    is_active?: boolean;
  }>;
  alert_count: number;
  query_summary: QuerySummary;
}

interface QueryRecord {
  end_time?: string;
  warehouse_name?: string;
  query_type?: string;
  total_elapsed_time?: number;
  cost_usd?: number;
  execution_status?: string;
}

interface UserQueries {
  summary: {
    total_queries: number;
    total_cost_usd: number;
    avg_duration_ms: number;
  };
  queries: QueryRecord[];
}

interface Recommendation {
  id?: string;
  title?: string;
  category?: string;
  priority?: string;
  potential_savings?: number;
  description?: string;
}

function formatDate(iso?: string) {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatRelative(iso?: string) {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(iso);
}

export default function AdminPage() {
  const { user } = useAuth();
  const router = useRouter();

  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (user && user.role !== "admin") {
      router.push("/overview");
    }
  }, [user, router]);

  const { data: stats, loading: statsLoading } = useApi<AdminStats>(
    user?.role === "admin" ? "/admin/stats" : null,
    [refreshKey]
  );
  const { data: users, loading: usersLoading, refetch: refetchUsers } = useApi<AdminUser[]>(
    user?.role === "admin" ? "/admin/users" : null,
    [refreshKey]
  );
  const { data: activity, loading: activityLoading } = useApi<ActivityEvent[]>(
    user?.role === "admin" ? "/admin/activity" : null,
    [refreshKey]
  );

  // Detail data for selected user
  const { data: userDetail, loading: detailLoading } = useApi<UserDetail>(
    selectedUserId ? `/admin/users/${selectedUserId}` : null,
    [selectedUserId, refreshKey]
  );
  const { data: userQueries, loading: queriesLoading } = useApi<UserQueries>(
    selectedUserId ? `/admin/users/${selectedUserId}/queries?limit=10` : null,
    [selectedUserId, refreshKey]
  );
  const { data: userRecs, loading: recsLoading } = useApi<Recommendation[]>(
    selectedUserId ? `/admin/users/${selectedUserId}/recommendations` : null,
    [selectedUserId]
  );

  const refresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  const handleToggleRole = async (u: AdminUser) => {
    setActionLoading(u.user_id);
    try {
      await api.patch(`/admin/users/${u.user_id}/role`);
      refresh();
    } catch { /* ignore */ }
    setActionLoading(null);
  };

  const handleToggleDisable = async (u: AdminUser) => {
    setActionLoading(u.user_id);
    try {
      await api.patch(`/admin/users/${u.user_id}/toggle-disable`);
      refresh();
    } catch { /* ignore */ }
    setActionLoading(null);
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.delete(`/admin/users/${deleteTarget.user_id}`);
      if (selectedUserId === deleteTarget.user_id) setSelectedUserId(null);
      refresh();
    } catch { /* ignore */ }
    setDeleting(false);
    setDeleteTarget(null);
  };

  if (!user || user.role !== "admin") return null;

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-900 mb-6">Admin Dashboard</h1>

      {/* Stats Row */}
      {statsLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-[100px] rounded-xl" />
          ))}
        </div>
      ) : stats ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatCard title="Total Users" value={stats.total_users} icon={Users} />
          <StatCard title="Active Connections" value={stats.total_connections} icon={Link2} />
          <StatCard title="Queries Synced" value={stats.total_queries.toLocaleString()} icon={Database} />
          <StatCard title="Signups (7d)" value={stats.recent_signups} icon={UserPlus} />
        </div>
      ) : null}

      {/* Users Table */}
      <Card className="mb-8">
        <CardHeader>
          <CardTitle>All Users</CardTitle>
        </CardHeader>
        <CardContent>
          {usersLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : users && users.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Auth</TableHead>
                  <TableHead>Signed Up</TableHead>
                  <TableHead>Connections</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead className="w-[60px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow
                    key={u.user_id}
                    className={`cursor-pointer ${u.is_disabled ? "opacity-50" : ""} ${selectedUserId === u.user_id ? "bg-muted" : ""}`}
                    onClick={() => setSelectedUserId(selectedUserId === u.user_id ? null : u.user_id)}
                  >
                    <TableCell className="font-medium">
                      {u.name || "\u2014"}
                      {u.is_disabled && (
                        <Badge variant="outline" className="ml-2 text-red-600 border-red-300">Disabled</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{u.email}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">
                        {u.auth_provider || "email"}
                      </Badge>
                    </TableCell>
                    <TableCell>{formatDate(u.created_at)}</TableCell>
                    <TableCell>{u.connection_count}</TableCell>
                    <TableCell>
                      {u.role === "admin" ? (
                        <Badge variant="default">admin</Badge>
                      ) : (
                        <span className="text-muted-foreground">user</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                          <Button variant="ghost" size="icon" className="h-8 w-8" disabled={actionLoading === u.user_id}>
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                          <DropdownMenuItem onClick={() => handleToggleRole(u)}>
                            {u.role === "admin" ? (
                              <><ShieldOff className="mr-2 h-4 w-4" /> Remove Admin</>
                            ) : (
                              <><ShieldCheck className="mr-2 h-4 w-4" /> Set as Admin</>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => handleToggleDisable(u)}>
                            {u.is_disabled ? (
                              <><CheckCircle className="mr-2 h-4 w-4" /> Enable</>
                            ) : (
                              <><Ban className="mr-2 h-4 w-4" /> Disable</>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            variant="destructive"
                            onClick={() => setDeleteTarget(u)}
                          >
                            <Trash2 className="mr-2 h-4 w-4" /> Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-muted-foreground text-sm">No users found.</p>
          )}
        </CardContent>
      </Card>

      {/* User Detail Panel */}
      {selectedUserId && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>User Details</CardTitle>
          </CardHeader>
          <CardContent>
            {detailLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-6 w-full" />
                ))}
              </div>
            ) : userDetail ? (
              <div className="space-y-6">
                {/* User Info */}
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                  <div>
                    <span className="text-muted-foreground">Name</span>
                    <p className="font-medium">{userDetail.name || "\u2014"}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Email</span>
                    <p className="font-medium">{userDetail.email}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Auth Provider</span>
                    <p className="font-medium">{userDetail.auth_provider || "email"}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Signed Up</span>
                    <p className="font-medium">{formatDate(userDetail.created_at)}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Role</span>
                    <p className="font-medium">{userDetail.role || "user"}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Status</span>
                    <p className="font-medium">{userDetail.is_disabled ? "Disabled" : "Active"}</p>
                  </div>
                </div>

                {/* Connections */}
                <div>
                  <h3 className="text-sm font-semibold mb-2">Connections ({userDetail.connections.length})</h3>
                  {userDetail.connections.length > 0 ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Account</TableHead>
                          <TableHead>Warehouse</TableHead>
                          <TableHead>Created</TableHead>
                          <TableHead>Active</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {userDetail.connections.map((c, i) => (
                          <TableRow key={i}>
                            <TableCell>{c.account || "\u2014"}</TableCell>
                            <TableCell>{c.warehouse || "\u2014"}</TableCell>
                            <TableCell>{formatDate(c.created_at)}</TableCell>
                            <TableCell>
                              {c.is_active ? (
                                <Badge variant="default">Active</Badge>
                              ) : (
                                <span className="text-muted-foreground">No</span>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <p className="text-muted-foreground text-sm">No connections.</p>
                  )}
                </div>

                {/* Query Summary */}
                <div>
                  <h3 className="text-sm font-semibold mb-2">Query History Summary</h3>
                  <div className="grid grid-cols-3 gap-4 text-sm">
                    <div>
                      <span className="text-muted-foreground">Total Queries</span>
                      <p className="font-medium">{userDetail.query_summary.total_queries.toLocaleString()}</p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Total Cost</span>
                      <p className="font-medium">{formatCurrency(userDetail.query_summary.total_cost_usd)}</p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Latest Query</span>
                      <p className="font-medium">{formatDate(userDetail.query_summary.latest_query_date)}</p>
                    </div>
                  </div>
                </div>

                {/* Recent Queries Table */}
                <div>
                  <h3 className="text-sm font-semibold mb-2">Recent Queries</h3>
                  {queriesLoading ? (
                    <Skeleton className="h-20 w-full" />
                  ) : userQueries && userQueries.queries.length > 0 ? (
                    <>
                      <div className="grid grid-cols-3 gap-4 text-sm mb-3">
                        <div>
                          <span className="text-muted-foreground">Avg Duration</span>
                          <p className="font-medium">{formatDuration(userQueries.summary.avg_duration_ms)}</p>
                        </div>
                      </div>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>Time</TableHead>
                            <TableHead>Warehouse</TableHead>
                            <TableHead>Type</TableHead>
                            <TableHead>Duration</TableHead>
                            <TableHead>Cost</TableHead>
                            <TableHead>Status</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {userQueries.queries.map((q, i) => (
                            <TableRow key={i}>
                              <TableCell className="text-xs">{formatRelative(q.end_time)}</TableCell>
                              <TableCell>{q.warehouse_name || "\u2014"}</TableCell>
                              <TableCell>
                                <Badge variant="secondary" className="text-xs">{q.query_type || "\u2014"}</Badge>
                              </TableCell>
                              <TableCell>{q.total_elapsed_time ? formatDuration(q.total_elapsed_time) : "\u2014"}</TableCell>
                              <TableCell>{q.cost_usd != null ? formatCurrency(q.cost_usd) : "\u2014"}</TableCell>
                              <TableCell>
                                <Badge variant={q.execution_status === "SUCCESS" ? "default" : "secondary"} className="text-xs">
                                  {q.execution_status || "\u2014"}
                                </Badge>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </>
                  ) : (
                    <p className="text-muted-foreground text-sm">No queries synced.</p>
                  )}
                </div>

                {/* Recommendations */}
                <div>
                  <h3 className="text-sm font-semibold mb-2">Recommendations</h3>
                  {recsLoading ? (
                    <Skeleton className="h-20 w-full" />
                  ) : userRecs && userRecs.length > 0 ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Title</TableHead>
                          <TableHead>Category</TableHead>
                          <TableHead>Priority</TableHead>
                          <TableHead>Savings</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {userRecs.map((r, i) => (
                          <TableRow key={i}>
                            <TableCell className="font-medium text-sm">{r.title}</TableCell>
                            <TableCell>
                              <Badge variant="secondary">{r.category}</Badge>
                            </TableCell>
                            <TableCell>
                              <Badge variant={r.priority === "high" ? "default" : "secondary"}>
                                {r.priority}
                              </Badge>
                            </TableCell>
                            <TableCell>{r.potential_savings != null ? formatCurrency(r.potential_savings) : "\u2014"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <p className="text-muted-foreground text-sm">No recommendations available.</p>
                  )}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      )}

      {/* Activity Feed */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Activity</CardTitle>
        </CardHeader>
        <CardContent>
          {activityLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : activity && activity.length > 0 ? (
            <div className="space-y-3">
              {activity.map((event, i) => (
                <div key={i} className="flex items-center justify-between text-sm border-b last:border-0 pb-2 last:pb-0">
                  <div>
                    {event.type === "signup" ? (
                      <span>
                        <span className="font-medium">{event.user_name}</span>
                        {" signed up via "}
                        <Badge variant="secondary" className="text-xs">{event.auth_provider || "email"}</Badge>
                      </span>
                    ) : (
                      <span>
                        <span className="font-medium">{event.user_id}</span>
                        {" connected "}
                        <span className="text-muted-foreground">{event.account}</span>
                      </span>
                    )}
                  </div>
                  <span className="text-muted-foreground text-xs whitespace-nowrap ml-4">
                    {formatRelative(event.timestamp)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">No recent activity.</p>
          )}
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete User</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete <strong>{deleteTarget?.name || deleteTarget?.email}</strong>?
              This will permanently remove the user and all their connections, alerts, and query history.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
