import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "../auth/AuthProvider";
import { Badge, Empty, ErrorNote, Pager, PageHeader } from "../components/ui";
import { api, friendlyError } from "../lib/api";
import { ago, fmtDate } from "../lib/format";
import type { AdminUser, CollectorRun, Invite, MemberRole, Members, PageOf, Role } from "../lib/types";

export const ROLE_INFO: Record<Role, { label: string; tone: "blue" | "green" | "gray"; can: string }> = {
  admin: { label: "Admin", tone: "blue", can: "Everything, including managing the team" },
  developer: { label: "Developer", tone: "green", can: "Everything except managing the team: accounts, rules, VM actions" },
  viewer: { label: "Viewer", tone: "gray", can: "Read-only, plus the AI assistant" },
};

export function RoleBadge({ role }: { role: Role }) {
  return <Badge tone={ROLE_INFO[role].tone}>{ROLE_INFO[role].label}</Badge>;
}

function InviteForm({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MemberRole>("viewer");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const invite = useMutation({
    mutationFn: () =>
      api<Invite>("/workspace/invites", { method: "POST", body: JSON.stringify({ email, role }) }),
    onSuccess: (inv) => {
      setSent(inv.email);
      setEmail("");
      setError(null);
      onDone();
    },
    onError: (e) => setError(friendlyError(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSent(null);
    invite.mutate();
  };
  return (
    <form className="card space-y-3" onSubmit={submit}>
      <div>
        <h2 className="font-semibold">Add a team member</h2>
        <p className="text-sm text-muted">
          They get access when they sign up with this email. Nothing is emailed automatically, so
          send them the link to this app.
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-[14rem] flex-1 text-sm">
          <span className="mb-1 block font-medium">Email</span>
          <input className="input" type="email" required value={email} placeholder="name@company.com"
            onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Role</span>
          <select className="input" value={role} onChange={(e) => setRole(e.target.value as MemberRole)}>
            <option value="viewer">Viewer</option>
            <option value="developer">Developer</option>
          </select>
        </label>
        <button className="btn-primary" disabled={invite.isPending || !email}>
          {invite.isPending ? "Adding…" : "Add member"}
        </button>
      </div>
      <p className="text-xs text-muted">{ROLE_INFO[role].label}: {ROLE_INFO[role].can}.</p>
      <ErrorNote message={error} />
      {sent && (
        <p className="text-sm text-emerald-700 dark:text-emerald-400">
          {sent} can now sign up and will join this workspace.
        </p>
      )}
    </form>
  );
}

function MembersSection() {
  const { me, role } = useAuth();
  const isAdmin = role === "admin";
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["members"], queryFn: () => api<Members>("/workspace/members") });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["members"] });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: MemberRole; is_active?: boolean } }) =>
      api<AdminUser>(`/workspace/members/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: refresh,
    onError: (e) => setError(friendlyError(e)),
  });
  const revoke = useMutation({
    mutationFn: (id: number) => api(`/workspace/invites/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: (e) => setError(friendlyError(e)),
  });
  const data = query.data;

  return (
    <div className="space-y-4">
      {isAdmin && <InviteForm onDone={refresh} />}
      <ErrorNote message={error ?? (query.error ? friendlyError(query.error) : null)} />
      <section className="card overflow-x-auto p-0">
        <div className="border-b border-line px-4 py-3">
          <h2 className="font-semibold">Members</h2>
        </div>
        <table className="w-full">
          <thead>
            <tr><th className="th">Email</th><th className="th">Role</th><th className="th">Last active</th>{isAdmin && <th className="th text-right">Access</th>}</tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data?.members.map((u) => {
              const self = u.id === me?.id;
              const editable = isAdmin && !self && u.role !== "admin";
              return (
                <tr key={u.id} className={u.is_active ? "" : "opacity-60"}>
                  <td className="td">
                    {u.email}
                    {self && <span className="ml-2 text-xs text-muted">(you)</span>}
                    {!u.is_active && <span className="ml-2"><Badge tone="red">removed</Badge></span>}
                  </td>
                  <td className="td">
                    {editable ? (
                      <select className="input max-w-[9rem] py-1" value={u.role} aria-label={`Role of ${u.email}`}
                        onChange={(e) => update.mutate({ id: u.id, body: { role: e.target.value as MemberRole } })}>
                        <option value="developer">Developer</option>
                        <option value="viewer">Viewer</option>
                      </select>
                    ) : (
                      <RoleBadge role={u.role} />
                    )}
                  </td>
                  <td className="td text-muted">{u.last_login_at ? ago(u.last_login_at) : "never signed in"}</td>
                  {isAdmin && (
                    <td className="td text-right">
                      {editable && (
                        <button className="btn-ghost btn-sm"
                          onClick={() => update.mutate({ id: u.id, body: { is_active: !u.is_active } })}>
                          {u.is_active ? "Remove access" : "Restore access"}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      {isAdmin && data && data.invites.length > 0 && (
        <section className="card overflow-x-auto p-0">
          <div className="border-b border-line px-4 py-3">
            <h2 className="font-semibold">Waiting to sign up</h2>
          </div>
          <table className="w-full">
            <tbody className="divide-y divide-line">
              {data.invites.map((i) => (
                <tr key={i.id}>
                  <td className="td">{i.email}</td>
                  <td className="td"><RoleBadge role={i.role} /></td>
                  <td className="td text-muted">added {ago(i.created_at)}</td>
                  <td className="td text-right">
                    <button className="btn-ghost btn-sm" onClick={() => revoke.mutate(i.id)}>Cancel</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function CollectorRuns() {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["collector-runs", page],
    queryFn: () => api<PageOf<CollectorRun>>(`/admin/collector-runs?page=${page}&page_size=10`),
    refetchInterval: 30_000,
  });
  const pages = query.data ? Math.max(1, Math.ceil(query.data.total / query.data.page_size)) : 1;
  return (
    <section>
      <h2 className="mb-1 font-semibold">Collector health</h2>
      <p className="mb-2 text-sm text-muted">Platform operators only: every collection cycle, across all workspaces.</p>
      <ErrorNote message={query.error ? friendlyError(query.error) : null} />
      {query.data && query.data.items.length === 0 ? (
        <Empty>The collector has not run yet.</Empty>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full">
            <thead className="border-b border-line">
              <tr><th className="th">Started</th><th className="th">Accounts</th><th className="th">Samples</th><th className="th">Errors</th><th className="th">Status</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
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

export function Team() {
  const { me } = useAuth();
  return (
    <>
      <PageHeader title="Team" subtitle={me ? `Members of ${me.workspace.name}` : undefined} />
      <div className="space-y-8">
        <MembersSection />
        <section className="card">
          <h2 className="mb-2 font-semibold">What each role can do</h2>
          <ul className="space-y-1.5 text-sm">
            {(Object.keys(ROLE_INFO) as Role[]).map((r) => (
              <li key={r} className="flex items-start gap-2">
                <RoleBadge role={r} /> <span className="text-muted">{ROLE_INFO[r].can}</span>
              </li>
            ))}
          </ul>
        </section>
        {me?.is_operator && <CollectorRuns />}
      </div>
    </>
  );
}
