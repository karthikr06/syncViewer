import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { canWrite, useAuth, useDb } from "../auth/AuthProvider";
import { api, friendlyError } from "../lib/api";
import { ago } from "../lib/format";
import { vmAction } from "../lib/mutations";
import type { Resource, VmAction, VmActionName } from "../lib/types";
import { Badge, ErrorNote } from "./ui";

export const ACTION_INFO: Record<VmActionName, { label: string; explain: string; danger?: boolean }> = {
  start: { label: "Start", explain: "Boots the VM. Billing for compute resumes." },
  stop: { label: "Stop", explain: "Shuts the VM down but keeps it allocated, so compute is still billed.", danger: true },
  restart: { label: "Restart", explain: "Reboots the VM. Useful when it is running but not responding.", danger: true },
  deallocate: { label: "Deallocate", explain: "Stops the VM and releases its compute, so it is no longer billed. Disks are kept.", danger: true },
};

/** Which actions make sense for a power state, most useful first. */
export function actionsFor(power: Resource["power_state"]): VmActionName[] {
  if (power === "running") return ["restart", "stop", "deallocate"];
  if (power === "stopped") return ["start", "deallocate"];
  if (power === "deallocated") return ["start"];
  return [];
}

export function VmActions({ resource }: { resource: Resource }) {
  const db = useDb();
  const { role } = useAuth();
  const qc = useQueryClient();
  const writer = canWrite(role);
  const [pending, setPending] = useState<VmActionName | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const history = useQuery({
    queryKey: ["vm-actions", resource.id],
    queryFn: () => api<VmAction[]>(`/resources/${resource.id}/actions`),
    retry: false,
  });

  const run = async (action: VmActionName) => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const r = await vmAction(db, resource.id, action);
      setDone(`${ACTION_INFO[action].label} done: the VM is now ${r.to_state}.`);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(false);
      setPending(null);
      void qc.invalidateQueries({ queryKey: ["vm-actions", resource.id] });
    }
  };

  const available = actionsFor(resource.power_state);
  return (
    <section className="card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Power actions</h2>
        {!writer && <span className="text-xs text-muted">Admins and developers can act on VMs.</span>}
      </div>
      {writer && (
        <div className="mt-3 flex flex-wrap gap-2">
          {available.length === 0 && <span className="text-sm text-muted">No actions available while the state is {resource.power_state}.</span>}
          {available.map((a) => (
            <button key={a} className={ACTION_INFO[a].danger ? "btn-ghost" : "btn-primary"} disabled={busy}
              onClick={() => { setPending(a); setDone(null); setError(null); }}>
              {ACTION_INFO[a].label}
            </button>
          ))}
        </div>
      )}
      {pending && (
        <div className="mt-3 rounded-lg border border-line bg-subtle p-3 text-sm" role="alertdialog" aria-label="Confirm action">
          <p>
            <span className="font-semibold">{ACTION_INFO[pending].label} {resource.name}?</span>{" "}
            {ACTION_INFO[pending].explain}
          </p>
          <div className="mt-2 flex gap-2">
            <button className={ACTION_INFO[pending].danger ? "btn-danger btn-sm" : "btn-primary btn-sm"} disabled={busy}
              onClick={() => void run(pending)}>
              {busy ? "Working…" : `Yes, ${ACTION_INFO[pending].label.toLowerCase()}`}
            </button>
            <button className="btn-ghost btn-sm" disabled={busy} onClick={() => setPending(null)}>Cancel</button>
          </div>
        </div>
      )}
      <div className="mt-3"><ErrorNote message={error} /></div>
      {done && <p className="mt-2 text-sm text-emerald-700 dark:text-emerald-400">{done}</p>}
      <h3 className="mt-4 text-sm font-semibold">Recent actions</h3>
      {history.isError ? (
        <p className="text-sm text-muted">History needs a connection.</p>
      ) : !history.data || history.data.length === 0 ? (
        <p className="text-sm text-muted">No actions taken from SyncViewer yet.</p>
      ) : (
        <ul className="mt-1 divide-y divide-line text-sm">
          {history.data.map((h) => (
            <li key={h.id} className="flex flex-wrap items-center gap-2 py-1.5">
              <Badge tone={h.status === "succeeded" ? "green" : "red"}>{h.status}</Badge>
              <span className="font-medium">{ACTION_INFO[h.action].label}</span>
              <span className="text-muted">
                {h.from_state}{h.to_state ? ` → ${h.to_state}` : ""} · {h.requested_by ?? "someone"} · {ago(h.requested_at)}
              </span>
              {h.error && <span className="text-xs text-red-600 dark:text-red-400">{h.error}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
