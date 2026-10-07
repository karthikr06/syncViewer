import { useLiveQuery } from "dexie-react-hooks";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useDb } from "../auth/AuthProvider";
import { Badge, Empty, PageHeader, Stat, severityTone } from "../components/ui";
import { ago, duration, pct, uptimePercent } from "../lib/format";

export function Dashboard() {
  const db = useDb();
  const data = useLiveQuery(async () => {
    const [resources, alerts, incidents, rollups, recs, accounts] = await Promise.all([
      db.resources.toArray(),
      db.alerts.where("state").notEqual("resolved").toArray(),
      db.incidents.toArray(),
      db.uptime_rollups.toArray(),
      db.recommendations.where("status").equals("new").toArray(),
      db.cloud_accounts.toArray(),
    ]);
    return { resources, alerts, incidents, rollups, recs, accounts };
  }, [db]);

  if (!data) return <p className="text-slate-500">Loading…</p>;
  const { resources, alerts, incidents, rollups, recs, accounts } = data;
  if (accounts.length === 0)
    return (
      <>
        <PageHeader title="Dashboard" />
        <Empty>
          No cloud accounts yet. <Link className="text-sky-600 underline" to="/accounts">Add one</Link> to
          see your VMs here.
        </Empty>
      </>
    );

  const sevenDays = Date.now() - 7 * 86400_000;
  const recent = rollups.filter((r) => new Date(r.bucket_start).getTime() >= sevenDays);
  const byDay = new Map<string, { up: number; total: number }>();
  for (const r of recent) {
    const day = r.bucket_start.slice(0, 10);
    const e = byDay.get(day) ?? { up: 0, total: 0 };
    e.up += r.up_samples;
    e.total += r.total_samples;
    byDay.set(day, e);
  }
  const chart = [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, v]) => ({ day: day.slice(5), uptime: Number(((100 * v.up) / v.total).toFixed(2)) }));

  const names = new Map(resources.map((r) => [r.id, r.name]));
  const running = resources.filter((r) => r.power_state === "running").length;
  const openIncidents = incidents.filter((i) => !i.ended_at).length;
  // ongoing outages first (however old), then the most recent resolved ones
  const latest = [...incidents]
    .sort((a, b) => (a.ended_at ? 1 : 0) - (b.ended_at ? 1 : 0) || b.started_at.localeCompare(a.started_at))
    .slice(0, 6);
  const topRecs = [...recs]
    .sort((a, b) => ["critical", "warning", "info"].indexOf(a.severity) - ["critical", "warning", "info"].indexOf(b.severity))
    .slice(0, 5);

  return (
    <>
      <PageHeader title="Dashboard" subtitle={`${accounts.length} cloud account${accounts.length === 1 ? "" : "s"}`} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="VMs" value={resources.length} hint={`${running} running`} />
        <Stat label="Uptime (7d)" value={pct(uptimePercent(recent))} />
        <Stat label="Open alerts" value={alerts.length} />
        <Stat label="Open incidents" value={openIncidents} />
        <Stat label="New recommendations" value={recs.length} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-2 font-semibold">Fleet uptime by day (UTC)</h2>
          {chart.length === 0 ? (
            <Empty>No uptime data yet.</Empty>
          ) : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={chart}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="day" fontSize={12} />
                  <YAxis domain={[90, 100]} fontSize={12} unit="%" />
                  <Tooltip />
                  <Bar dataKey="uptime" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="card">
          <h2 className="mb-2 font-semibold">Recent incidents</h2>
          {latest.length === 0 ? (
            <Empty>No incidents. 🎉</Empty>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
              {latest.map((i) => (
                <li key={i.id} className="flex items-center justify-between py-2">
                  <Link className="text-sky-600 hover:underline" to={`/resources/${i.resource_id}`}>
                    {names.get(i.resource_id) ?? "VM"}
                  </Link>
                  <span className="text-slate-500">
                    {ago(i.started_at)} · {duration(i.started_at, i.ended_at)}
                  </span>
                  <Badge tone={i.ended_at ? "gray" : "red"}>{i.ended_at ? "resolved" : "ongoing"}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card lg:col-span-2">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-semibold">Top recommendations</h2>
            <Link className="text-sm text-sky-600 hover:underline" to="/recommendations">
              View all
            </Link>
          </div>
          {topRecs.length === 0 ? (
            <Empty>Nothing to improve right now.</Empty>
          ) : (
            <ul className="space-y-2 text-sm">
              {topRecs.map((r) => (
                <li key={r.id} className="flex items-center gap-2">
                  <Badge tone={severityTone(r.severity)}>{r.severity}</Badge>
                  <span className="text-slate-500">{r.category}</span>
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
