import { zodResolver } from "@hookform/resolvers/zod";
import { useLiveQuery } from "dexie-react-hooks";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { canWrite, useAuth, useDb } from "../auth/AuthProvider";
import { Badge, Empty, ErrorNote, Field, PageHeader } from "../components/ui";
import { friendlyError } from "../lib/api";
import { ago } from "../lib/format";
import { accountApi } from "../lib/mutations";

const schema = z.object({
  name: z.string().min(1, "Required").max(120),
  provider: z.enum(["mock", "azure"]),
  external_ref: z.string().min(1, "Required").max(200),
  scenario: z.enum(["small", "medium", "large"]),
});
type Form = z.infer<typeof schema>;

function AddAccount({ onDone }: { onDone: () => void }) {
  const db = useDb();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: { provider: "mock", scenario: "small", external_ref: `demo-${Math.random().toString(36).slice(2, 8)}` },
  });
  const provider = watch("provider");

  async function submit(v: Form) {
    setError(null);
    try {
      await accountApi.create(db, {
        name: v.name,
        provider: v.provider,
        external_ref: v.external_ref,
        config: v.provider === "mock" ? { scenario: v.scenario } : {},
      });
      onDone();
    } catch (e) {
      setError(friendlyError(e));
    }
  }

  return (
    <form className="card mb-4 grid gap-3 md:grid-cols-2" onSubmit={handleSubmit(submit)} noValidate>
      <Field label="Name" error={errors.name?.message}>
        <input className="input" placeholder="Production" {...register("name")} />
      </Field>
      <Field label="Provider">
        <select className="input" {...register("provider")}>
          <option value="mock">Demo (generator)</option>
          <option value="azure">Microsoft Azure (coming soon)</option>
        </select>
      </Field>
      <Field label={provider === "mock" ? "Demo account id" : "Subscription id"} error={errors.external_ref?.message}>
        <input className="input" {...register("external_ref")} />
      </Field>
      {provider === "mock" && (
        <Field label="Size of the demo fleet">
          <select className="input" {...register("scenario")}>
            <option value="small">Small (5 VMs)</option>
            <option value="medium">Medium (25 VMs)</option>
            <option value="large">Large (300 VMs)</option>
          </select>
        </Field>
      )}
      <div className="md:col-span-2">
        <ErrorNote message={error} />
        <div className="mt-2 flex gap-2">
          <button className="btn-primary" disabled={isSubmitting}>{isSubmitting ? "Connecting…" : "Add account"}</button>
          <button type="button" className="btn-ghost" onClick={onDone}>Cancel</button>
        </div>
      </div>
    </form>
  );
}

export function Accounts() {
  const db = useDb();
  const { role } = useAuth();
  const writer = canWrite(role);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const data = useLiveQuery(
    async () => ({ accounts: await db.cloud_accounts.toArray(), resources: await db.resources.toArray() }),
    [db],
  );
  if (!data) return <p className="text-slate-500">Loading…</p>;
  const counts = new Map<string, number>();
  data.resources.forEach((r) => counts.set(r.account_id, (counts.get(r.account_id) ?? 0) + 1));

  const run = async (id: string, fn: () => Promise<unknown>, ok?: string) => {
    setError(null);
    setNote(null);
    setBusy(id);
    try {
      await fn();
      if (ok) setNote(ok);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Cloud accounts"
        subtitle="Connect accounts to monitor their VMs"
        actions={writer && !adding && <button className="btn-primary" onClick={() => setAdding(true)}>Add account</button>}
      />
      {adding && writer && <AddAccount onDone={() => setAdding(false)} />}
      <ErrorNote message={error} />
      {note && <p className="mb-2 text-sm text-emerald-700 dark:text-emerald-400">{note}</p>}
      {data.accounts.length === 0 ? (
        <Empty>No accounts yet.{writer ? " Add a demo account to see SyncViewer in action." : ""}</Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.accounts.map((a) => (
            <div key={a.id} className="card">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">{a.name}</h3>
                <Badge tone={a.status === "active" ? "green" : a.status === "error" ? "red" : "amber"}>{a.status}</Badge>
              </div>
              <p className="text-sm text-slate-500">
                {a.provider_code} · {a.external_ref} · {counts.get(a.id) ?? 0} VMs
              </p>
              <p className="text-sm text-slate-500">Last collected: {a.last_collected_at ? ago(a.last_collected_at) : "not yet"}</p>
              {a.last_error && <p className="mt-1 text-sm text-red-600">{a.last_error}</p>}
              {writer && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button className="btn-primary" disabled={busy === a.id}
                    onClick={() => void run(a.id, () => accountApi.collectNow(a.id), "Collection finished; data will appear shortly.")}>
                    {busy === a.id ? "Working…" : "Collect now"}
                  </button>
                  <button className="btn-ghost" disabled={busy === a.id}
                    onClick={() => void run(a.id, () => accountApi.update(db, a.id, { status: a.status === "paused" ? "active" : "paused" }))}>
                    {a.status === "paused" ? "Resume" : "Pause"}
                  </button>
                  <button className="btn-ghost" disabled={busy === a.id}
                    onClick={() => { if (confirm(`Remove "${a.name}" and its VMs from SyncViewer?`)) void run(a.id, () => accountApi.remove(db, a.id)); }}>
                    Remove
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
