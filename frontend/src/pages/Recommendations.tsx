import { useLiveQuery } from "dexie-react-hooks";
import { useState } from "react";
import { Link } from "react-router-dom";
import { canWrite, useAuth, useDb } from "../auth/AuthProvider";
import { Badge, Empty, ErrorNote, PageHeader, severityTone } from "../components/ui";
import { friendlyError } from "../lib/api";
import { setRecommendationStatus } from "../lib/mutations";
import type { Recommendation } from "../lib/types";

export function RecommendationCard({
  rec,
  resourceName,
  writer,
  onError,
}: {
  rec: Recommendation;
  resourceName?: string;
  writer: boolean;
  onError: (m: string | null) => void;
}) {
  const db = useDb();
  const [open, setOpen] = useState(false);
  const act = async (status: Recommendation["status"]) => {
    onError(null);
    try {
      await setRecommendationStatus(db, rec.id, status);
    } catch (e) {
      onError(friendlyError(e));
    }
  };
  return (
    <div className="card">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={severityTone(rec.severity)}>{rec.severity}</Badge>
        <Badge>{rec.category}</Badge>
        {rec.source === "agent" && <Badge tone="blue">AI</Badge>}
        {rec.status !== "new" && <Badge tone="gray">{rec.status}</Badge>}
        <h3 className="font-semibold">{rec.title}</h3>
      </div>
      <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{rec.detail}</p>
      {rec.resource_id && (
        <p className="mt-1 text-sm">
          VM: <Link className="text-sky-600 hover:underline" to={`/resources/${rec.resource_id}`}>{resourceName ?? "view"}</Link>
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-ghost" onClick={() => setOpen(!open)}>{open ? "Hide evidence" : "Evidence"}</button>
        {writer && rec.status === "new" && (
          <>
            <button className="btn-primary" onClick={() => void act("done")}>Mark done</button>
            <button className="btn-ghost" onClick={() => void act("dismissed")}>Dismiss</button>
          </>
        )}
        {writer && rec.status !== "new" && (
          <button className="btn-ghost" onClick={() => void act("new")}>Reopen</button>
        )}
      </div>
      {open && (
        <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-100 p-3 text-xs dark:bg-slate-800">
          {JSON.stringify(rec.evidence, null, 2)}
        </pre>
      )}
    </div>
  );
}

const ORDER = ["critical", "warning", "info"];

export function Recommendations() {
  const db = useDb();
  const { role } = useAuth();
  const [status, setStatus] = useState("new");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const data = useLiveQuery(
    async () => ({ recs: await db.recommendations.toArray(), resources: await db.resources.toArray() }),
    [db],
  );
  if (!data) return <p className="text-slate-500">Loading…</p>;
  const names = new Map(data.resources.map((r) => [r.id, r.name]));
  const recs = data.recs
    .filter((r) => (!status || r.status === status) && (!category || r.category === category))
    .sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity) || b.created_at.localeCompare(a.created_at));

  return (
    <>
      <PageHeader title="Recommendations" subtitle="Rule-based and AI suggestions, each with its evidence" />
      <div className="mb-3 flex flex-wrap gap-2">
        <select className="input max-w-[11rem]" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="new">New</option>
          <option value="done">Done</option>
          <option value="dismissed">Dismissed</option>
          <option value="">All</option>
        </select>
        <select className="input max-w-[11rem]" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {["rightsizing", "reliability", "capacity", "waste", "pattern"].map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      </div>
      <ErrorNote message={error} />
      {recs.length === 0 ? (
        <Empty>No recommendations here.</Empty>
      ) : (
        <div className="mt-3 grid gap-3">
          {recs.map((r) => (
            <RecommendationCard key={r.id} rec={r} resourceName={r.resource_id ? names.get(r.resource_id) : undefined} writer={canWrite(role)} onError={setError} />
          ))}
        </div>
      )}
    </>
  );
}
