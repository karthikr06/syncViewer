import { zodResolver } from "@hookform/resolvers/zod";
import { useLiveQuery } from "dexie-react-hooks";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { canWrite, useAuth, useDb } from "../auth/AuthProvider";
import { Badge, Empty, ErrorNote, Field, Pager, PageHeader, severityTone } from "../components/ui";
import { friendlyError } from "../lib/api";
import { fmtDate, paginate } from "../lib/format";
import { acknowledgeAlert, ruleApi } from "../lib/mutations";

const METRICS = ["availability", "cpu_percent", "memory_percent", "disk_used_percent", "network_in_bytes", "network_out_bytes"];

const ruleSchema = z.object({
  name: z.string().min(1, "Required").max(120),
  metric: z.string().min(1),
  operator: z.enum([">", ">=", "<", "<="]),
  threshold: z.coerce.number({ invalid_type_error: "Enter a number" }),
  duration_minutes: z.coerce.number().int().min(0).max(1440),
  severity: z.enum(["info", "warning", "critical"]),
  scope: z.string(), // "" = all, "a:<id>" account, "r:<id>" resource
});
type RuleForm = z.infer<typeof ruleSchema>;

function RuleEditor({ onDone }: { onDone: () => void }) {
  const db = useDb();
  const [error, setError] = useState<string | null>(null);
  const targets = useLiveQuery(
    async () => ({
      accounts: await db.cloud_accounts.toArray(),
      resources: (await db.resources.toArray()).sort((a, b) => a.name.localeCompare(b.name)),
    }),
    [db],
  );
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RuleForm>({
    resolver: zodResolver(ruleSchema),
    defaultValues: { metric: "cpu_percent", operator: ">", threshold: 90, duration_minutes: 10, severity: "warning", scope: "" },
  });

  async function submit(v: RuleForm) {
    setError(null);
    try {
      await ruleApi.create(db, {
        name: v.name,
        metric: v.metric,
        operator: v.operator,
        threshold: v.threshold,
        duration_minutes: v.duration_minutes,
        severity: v.severity,
        account_id: v.scope.startsWith("a:") ? v.scope.slice(2) : null,
        resource_id: v.scope.startsWith("r:") ? v.scope.slice(2) : null,
      });
      onDone();
    } catch (e) {
      setError(friendlyError(e));
    }
  }

  return (
    <form className="card mb-4 grid gap-3 md:grid-cols-4" onSubmit={handleSubmit(submit)} noValidate>
      <div className="md:col-span-2">
        <Field label="Name" error={errors.name?.message}>
          <input className="input" {...register("name")} />
        </Field>
      </div>
      <Field label="Applies to">
        <select className="input" {...register("scope")}>
          <option value="">All my VMs</option>
          {targets?.accounts.map((a) => (
            <option key={a.id} value={`a:${a.id}`}>Account: {a.name}</option>
          ))}
          {targets?.resources.map((r) => (
            <option key={r.id} value={`r:${r.id}`}>VM: {r.name}</option>
          ))}
        </select>
      </Field>
      <Field label="Severity">
        <select className="input" {...register("severity")}>
          <option>info</option>
          <option>warning</option>
          <option>critical</option>
        </select>
      </Field>
      <Field label="Metric">
        <select className="input" {...register("metric")}>
          {METRICS.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
      </Field>
      <Field label="Condition">
        <select className="input" {...register("operator")}>
          {[">", ">=", "<", "<="].map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      </Field>
      <Field label="Threshold" error={errors.threshold?.message}>
        <input className="input" type="number" step="any" {...register("threshold")} />
      </Field>
      <Field label="For (minutes)" error={errors.duration_minutes?.message}>
        <input className="input" type="number" {...register("duration_minutes")} />
      </Field>
      <div className="md:col-span-4">
        <ErrorNote message={error} />
        <div className="mt-2 flex gap-2">
          <button className="btn-primary" disabled={isSubmitting}>Create rule</button>
          <button type="button" className="btn-ghost" onClick={onDone}>Cancel</button>
        </div>
      </div>
    </form>
  );
}

export function Alerts() {
  const db = useDb();
  const { role } = useAuth();
  const writer = canWrite(role);
  const [tab, setTab] = useState<"alerts" | "rules">("alerts");
  const [state, setState] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const data = useLiveQuery(
    async () => ({
      alerts: await db.alerts.toArray(),
      rules: await db.alert_rules.toArray(),
      resources: await db.resources.toArray(),
    }),
    [db],
  );
  if (!data) return <p className="text-muted">Loading…</p>;

  const ruleOf = new Map(data.rules.map((r) => [r.id, r]));
  const resName = new Map(data.resources.map((r) => [r.id, r.name]));
  const alerts = data.alerts
    .filter((a) => !state || a.state === state)
    .sort((a, b) => b.opened_at.localeCompare(a.opened_at));
  const view = paginate(alerts, page, 10);
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(friendlyError(e));
    }
  };

  return (
    <>
      <PageHeader
        title="Alerts"
        actions={
          writer && tab === "rules" && !creating ? (
            <button className="btn-primary" onClick={() => setCreating(true)}>New rule</button>
          ) : undefined
        }
      />
      <div className="mb-3 flex gap-2">
        {(["alerts", "rules"] as const).map((t) => (
          <button key={t} className={tab === t ? "btn-primary" : "btn-ghost"} onClick={() => setTab(t)}>
            {t === "alerts" ? `Alerts (${data.alerts.filter((a) => a.state !== "resolved").length} open)` : `Rules (${data.rules.length})`}
          </button>
        ))}
      </div>
      <ErrorNote message={error} />

      {tab === "alerts" ? (
        <>
          <select className="input mb-3 max-w-xs" value={state} onChange={(e) => { setState(e.target.value); setPage(1); }}>
            <option value="">All states</option>
            <option value="open">open</option>
            <option value="acknowledged">acknowledged</option>
            <option value="resolved">resolved</option>
          </select>
          {view.total === 0 ? (
            <Empty>No alerts.</Empty>
          ) : (
            <div className="card overflow-x-auto p-0">
              <table className="w-full">
                <thead className="border-b border-line">
                  <tr>
                    <th className="th">Rule</th><th className="th">VM</th><th className="th">Opened</th>
                    <th className="th">Value</th><th className="th">State</th><th className="th" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {view.rows.map((a) => {
                    const rule = ruleOf.get(a.rule_id);
                    return (
                      <tr key={a.id}>
                        <td className="td">{rule?.name ?? "rule"} {rule && <Badge tone={severityTone(rule.severity)}>{rule.severity}</Badge>}</td>
                        <td className="td"><Link className="text-link hover:underline" to={`/resources/${a.resource_id}`}>{resName.get(a.resource_id) ?? "VM"}</Link></td>
                        <td className="td">{fmtDate(a.opened_at)}</td>
                        <td className="td">{a.value_at_open?.toFixed(1) ?? "-"}</td>
                        <td className="td"><Badge tone={a.state === "open" ? "red" : a.state === "acknowledged" ? "amber" : "gray"}>{a.state}</Badge></td>
                        <td className="td text-right">
                          {writer && a.state === "open" && (
                            <button className="btn-ghost" onClick={() => void act(() => acknowledgeAlert(db, a.id))}>Acknowledge</button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <Pager page={view.page} pages={view.pages} total={view.total} onPage={setPage} />
        </>
      ) : (
        <>
          {creating && writer && <RuleEditor onDone={() => setCreating(false)} />}
          {data.rules.length === 0 ? (
            <Empty>No alert rules yet. Without rules you won't be notified of CPU, memory, disk or availability problems.</Empty>
          ) : (
            <div className="card overflow-x-auto p-0">
              <table className="w-full">
                <thead className="border-b border-line">
                  <tr><th className="th">Name</th><th className="th">Condition</th><th className="th">For</th><th className="th">Severity</th><th className="th">Enabled</th><th className="th" /></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {data.rules.map((r) => (
                    <tr key={r.id}>
                      <td className="td font-medium">{r.name}</td>
                      <td className="td">{r.metric} {r.operator} {r.threshold}</td>
                      <td className="td">{r.duration_minutes} min</td>
                      <td className="td"><Badge tone={severityTone(r.severity)}>{r.severity}</Badge></td>
                      <td className="td">
                        <input type="checkbox" checked={r.is_enabled} disabled={!writer}
                          onChange={(e) => void act(() => ruleApi.update(db, r.id, { is_enabled: e.target.checked }))} />
                      </td>
                      <td className="td text-right">
                        {writer && (
                          <button className="btn-ghost" onClick={() => { if (confirm(`Delete rule "${r.name}"?`)) void act(() => ruleApi.remove(db, r.id)); }}>Delete</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}
