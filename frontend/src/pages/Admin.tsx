import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import { Badge, Empty, ErrorNote, Pager, PageHeader } from "../components/ui";
import { api, friendlyError } from "../lib/api";
import { ago, fmtDate } from "../lib/format";
import type { AdminUser, CollectorRun, PageOf, Role } from "../lib/types";

function Users() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["admin-users", q, page],
    queryFn: () => api<PageOf<AdminUser>>(`/admin/users?q=${encodeURIComponent(q)}&page=${page}&page_size=10`),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: Role; is_active?: boolean } }) =>
      api<AdminUser>(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin-users"] }),
    onError: (e) => setError(friendlyError(e)),
  });
  const pages = query.data ? Math.max(1, Math.ceil(query.data.total / query.data.page_size)) : 1;

  return (
    <section>
      <h2 className="mb-2 font-semibold">Users</h2>
      <input className="input mb-3 max-w-xs" placeholder="Search email" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      <ErrorNote message={error ?? (query.error ? friendlyError(query.error) : null)} />
      {query.data && query.data.items.length === 0 ? (
        <Empty>No users found.</Empty>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full">
            <thead className="border-b border-slate-200 dark:border-slate-800">
              <tr><th className="th">Email</th><th className="th">Role</th><th className="th">Active</th><th className="th">Last login</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {query.data?.items.map((u) => {
                const self = u.id === me?.id;
                return (
                  <tr key={u.id}>
                    <td className="td">{u.email}{self && <span className="ml-2 text-xs text-slate-500">(you)</span>}</td>
                    <td className="td">
                      <select className="input max-w-[8rem]" value={u.role} disabled={self}
                        onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value as Role } })}>
                        <option>admin</option><option>user</option><option>viewer</option>
                      </select>
                    </td>
                    <td className="td">
                      <input type="checkbox" checked={u.is_active} disabled={self}
                        onChange={(e) => update.mutate({ id: u.id, body: { is_active: e.target.checked } })} />
                    </td>
                    <td className="td text-slate-500">{u.last_login_at ? ago(u.last_login_at) : "never"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {query.data && <Pager page={page} pages={pages} total={query.data.total} onPage={setPage} />}
    </section>
  );
}

function Runs() {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["collector-runs", page],
    queryFn: () => api<PageOf<CollectorRun>>(`/admin/collector-runs?page=${page}&page_size=10`),
    refetchInterval: 30_000,
  });
  const pages = query.data ? Math.max(1, Math.ceil(query.data.total / query.data.page_size)) : 1;
  return (
    <section>
      <h2 className="mb-2 font-semibold">Collector runs</h2>
      <ErrorNote message={query.error ? friendlyError(query.error) : null} />
      {query.data && query.data.items.length === 0 ? (
        <Empty>The collector has not run yet.</Empty>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full">
            <thead className="border-b border-slate-200 dark:border-slate-800">
              <tr><th className="th">Started</th><th className="th">Accounts</th><th className="th">Samples</th><th className="th">Errors</th><th className="th">Status</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {query.data?.items.map((r) => (
                <tr key={r.id}>
                  <td className="td">{fmtDate(r.started_at)}</td>
                  <td className="td">{r.accounts_processed}</td>
                  <td className="td">{r.samples_inserted}</td>
                  <td className="td" title={r.error_details?.map((e) => e.error).join("\n")}>{r.errors}</td>
                  <td className="td">
                    <Badge tone={!r.finished_at ? "amber" : r.errors ? "red" : "green"}>
                      {!r.finished_at ? "running" : r.errors ? "errors" : "ok"}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.data && <Pager page={page} pages={pages} total={query.data.total} onPage={setPage} />}
    </section>
  );
}

export function Admin() {
  return (
    <>
      <PageHeader title="Admin" subtitle="Users, roles and collector health" />
      <div className="space-y-8">
        <Users />
        <Runs />
      </div>
    </>
  );
}
