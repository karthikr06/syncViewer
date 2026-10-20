import { useQueryClient } from "@tanstack/react-query";
import { useLiveQuery } from "dexie-react-hooks";
import { useState } from "react";
import { Link } from "react-router-dom";
import { canWrite, useAuth, useDb } from "../auth/AuthProvider";
import { ACTION_INFO, isReadOnlySource } from "../components/VmActions";
import { Badge, Empty, ErrorNote, PageHeader, severityTone } from "../components/ui";
import { friendlyError } from "../lib/api";
import { setRecommendationStatus, vmAction } from "../lib/mutations";
import type { Recommendation, Resource, VmActionName } from "../lib/types";
import { useVmIndex, VmText, type VmIndex } from "../lib/vmLinks";

/** The action that fixes a recommendation directly from SyncViewer, if there is one. */
export function fixFor(rec: Recommendation, resource?: Resource): VmActionName | null {
  if (rec.status !== "new" || !resource || isReadOnlySource(resource)) return null;
  if (rec.category === "waste" && resource.power_state === "stopped") return "deallocate";
  return null;
}

/** One-click fix with an inline confirmation; also marks the recommendation done. */
export function FixButton({
  rec,
  resource,
  onError,
}: {
  rec: Recommendation;
  resource?: Resource;
  onError?: (m: string | null) => void;
}) {
  const db = useDb();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const action = fixFor(rec, resource);
  if (!action || !resource) return null;
  const info = ACTION_INFO[action];
  const run = async () => {
    setBusy(true);
    setErr(null);
    onError?.(null);
    try {
      await vmAction(db, resource.id, action, rec.id);
    } catch (e) {
      const m = friendlyError(e);
      setErr(m);
      onError?.(m);
    } finally {
      setBusy(false);
      setConfirm(false);
      void qc.invalidateQueries({ queryKey: ["vm-actions", resource.id] });
    }
  };
  if (!confirm)
    return (
      <span className="inline-flex flex-col">
        <button className="btn-primary" onClick={() => setConfirm(true)}>
          Fix: {info.label.toLowerCase()} {resource.name}
        </button>
        {err && !onError && <span className="mt-1 text-xs text-red-600 dark:text-red-400">{err}</span>}
      </span>
    );
  return (
    <span className="inline-flex flex-wrap items-center gap-2 rounded-lg border border-line bg-subtle px-2 py-1 text-xs">
      <span>{info.explain}</span>
      <button className="btn-danger btn-sm" disabled={busy} onClick={() => void run()}>
        {busy ? "Working…" : `Yes, ${info.label.toLowerCase()}`}
      </button>
      <button className="btn-ghost btn-sm" disabled={busy} onClick={() => setConfirm(false)}>
        Cancel
      </button>
    </span>
  );
}

export function RecommendationCard({
  rec,
  resource,
  vms,
  writer,
  onError,
}: {
  rec: Recommendation;
  resource?: Resource;
  vms: VmIndex;
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
        <h3 className="font-semibold">
          <VmText text={rec.title} index={vms} />
        </h3>
      </div>
      <p className="mt-2 text-sm text-ink/80">
        <VmText text={rec.detail} index={vms} />
      </p>
      {rec.resource_id && resource && (
        <p className="mt-1 text-sm text-muted">
          VM:{" "}
          <Link className="link font-medium" to={`/resources/${rec.resource_id}`}>
            {resource.name}
          </Link>
          {" · "}
          {resource.power_state}
          {resource.region ? ` · ${resource.region}` : ""}
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-start gap-2">
        {writer && <FixButton rec={rec} resource={resource} onError={onError} />}
        <button className="btn-ghost" onClick={() => setOpen(!open)}>
          {open ? "Hide evidence" : "Evidence"}
        </button>
        {writer && rec.status === "new" && (
          <>
            <button className="btn-ghost" onClick={() => void act("done")}>
              Mark done
            </button>
            <button className="btn-ghost" onClick={() => void act("dismissed")}>
              Dismiss
            </button>
          </>
        )}
        {writer && rec.status !== "new" && (
          <button className="btn-ghost" onClick={() => void act("new")}>
            Reopen
          </button>
        )}
      </div>
      {open && (
        <pre className="mt-3 overflow-x-auto rounded-lg bg-subtle p-3 text-xs">
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
  const vms = useVmIndex();
  const [status, setStatus] = useState("new");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const data = useLiveQuery(
    async () => ({ recs: await db.recommendations.toArray(), resources: await db.resources.toArray() }),
    [db],
  );
  if (!data) return <p className="text-muted">Loading…</p>;
  const byId = new Map(data.resources.map((r) => [r.id, r]));
  const recs = data.recs
    .filter((r) => (!status || r.status === status) && (!category || r.category === category))
    .sort(
      (a, b) =>
        ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity) || b.created_at.localeCompare(a.created_at),
    );

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
            <RecommendationCard
              key={r.id}
              rec={r}
              resource={r.resource_id ? byId.get(r.resource_id) : undefined}
              vms={vms}
              writer={canWrite(role)}
              onError={setError}
            />
          ))}
        </div>
      )}
    </>
  );
}
