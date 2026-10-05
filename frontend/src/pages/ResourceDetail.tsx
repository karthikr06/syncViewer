import { useLiveQuery } from "dexie-react-hooks";
import { Link, useParams } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useDb } from "../auth/AuthProvider";
import { Badge, Empty, PageHeader, Stat, healthTone, powerTone, severityTone } from "../components/ui";
import { duration, fmtDate, pct, uptimePercent } from "../lib/format";

const METRICS = [
  { key: "cpu_percent", label: "CPU %", color: "#0ea5e9" },
  { key: "memory_percent", label: "Memory %", color: "#a855f7" },
  { key: "disk_used_percent", label: "Disk used %", color: "#f59e0b" },
] as const;

function MetricChart({ points, color }: { points: { t: string; v: number }[]; color: string }) {
  if (points.length === 0) return <Empty>No data in the last 24 h.</Empty>;
  return (
    <div className="h-44">
      <ResponsiveContainer>
        <LineChart data={points}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis dataKey="t" fontSize={11} minTickGap={40} />
          <YAxis domain={[0, 100]} fontSize={11} width={32} />
          <Tooltip />
          <Line type="monotone" dataKey="v" stroke={color} dot={false} strokeWidth={2} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ResourceDetail() {
  const { id = "" } = useParams();
  const db = useDb();
  const data = useLiveQuery(async () => {
    const resource = await db.resources.get(id);
    if (!resource) return { resource: null as null };
    const [samples, incidents, rollups, alerts, rules, recs] = await Promise.all([
      db.samples.where("[resource_id+metric]").between([id, ""], [id, "￿"]).toArray(),
      db.incidents.where("resource_id").equals(id).toArray(),
      db.uptime_rollups.where("resource_id").equals(id).toArray(),
      db.alerts.where("resource_id").equals(id).toArray(),
      db.alert_rules.toArray(),
      db.recommendations.where("status").equals("new").toArray(),
    ]);
    return { resource, samples, incidents, rollups, alerts, rules, recs };
  }, [db, id]);

  if (!data) return <p className="text-slate-500">Loading…</p>;
  if (!data.resource)
    return (
      <Empty>
        VM not found in your cached data. <Link className="text-sky-600 underline" to="/resources">Back to resources</Link>
      </Empty>
    );
  const { resource, samples, incidents, rollups, alerts, rules, recs } = data;

  const series = (metric: string) =>
    samples
      .filter((s) => s.metric === metric)
      .sort((a, b) => a.ts.localeCompare(b.ts))
      .map((s) => ({
        t: new Date(s.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        v: Number(s.value.toFixed(2)),
      }));
  const last = (metric: string) => {
    const s = series(metric);
    return s.length ? s[s.length - 1].v : null;
  };
  const sevenDays = Date.now() - 7 * 86400_000;
  const up7 = uptimePercent(rollups.filter((r) => new Date(r.bucket_start).getTime() >= sevenDays));
  const ruleName = new Map(rules.map((r) => [r.id, r.name]));
  const myRecs = recs.filter((r) => r.resource_id === id);

  return (
    <>
      <PageHeader
        title={resource.name}
        subtitle={`${resource.region ?? "unknown region"} · ${resource.size_sku ?? "unknown size"} · ${resource.external_id}`}
        actions={
          <>
            <Badge tone={powerTone(resource.power_state)}>{resource.power_state}</Badge>
            <Badge tone={healthTone(resource.health_state)}>{resource.health_state}</Badge>
          </>
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Uptime (7d)" value={pct(up7)} hint="availability samples == 1" />
        <Stat label="CPU now" value={pct(last("cpu_percent"), 1)} />
        <Stat label="Memory now" value={pct(last("memory_percent"), 1)} />
        <Stat label="Disk now" value={pct(last("disk_used_percent"), 1)} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {METRICS.map((m) => (
          <div key={m.key} className="card">
            <h2 className="mb-2 font-semibold">{m.label}</h2>
            <MetricChart points={series(m.key)} color={m.color} />
          </div>
        ))}
        <div className="card">
          <h2 className="mb-2 font-semibold">Tags</h2>
          {Object.keys(resource.tags).length === 0 ? (
            <p className="text-sm text-slate-500">No tags.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {Object.entries(resource.tags).map(([k, v]) => (
                <Badge key={k}>{`${k}: ${v}`}</Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-2 font-semibold">Incidents</h2>
          {incidents.length === 0 ? (
            <Empty>No incidents recorded.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
              {[...incidents]
                .sort((a, b) => b.started_at.localeCompare(a.started_at))
                .slice(0, 15)
                .map((i) => (
                  <li key={i.id} className="flex items-center justify-between py-2">
                    <span>{fmtDate(i.started_at)}</span>
                    <span className="text-slate-500">{duration(i.started_at, i.ended_at)}</span>
                    <Badge tone={i.ended_at ? "gray" : "red"}>{i.ended_at ? i.kind : "ongoing"}</Badge>
                  </li>
                ))}
            </ul>
          )}
        </div>
        <div className="card">
          <h2 className="mb-2 font-semibold">Alerts & recommendations</h2>
          {alerts.length === 0 && myRecs.length === 0 ? (
            <Empty>Nothing to report.</Empty>
          ) : (
            <ul className="space-y-2 text-sm">
              {alerts.map((a) => (
                <li key={a.id} className="flex items-center gap-2">
                  <Badge tone={a.state === "resolved" ? "gray" : "red"}>{a.state}</Badge>
                  <span>{ruleName.get(a.rule_id) ?? "rule"}</span>
                  <span className="text-slate-500">{fmtDate(a.opened_at)}</span>
                </li>
              ))}
              {myRecs.map((r) => (
                <li key={r.id} className="flex items-center gap-2">
                  <Badge tone={severityTone(r.severity)}>{r.category}</Badge>
                  <span>{r.title}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}
