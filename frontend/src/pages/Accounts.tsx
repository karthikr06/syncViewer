import { zodResolver } from "@hookform/resolvers/zod";
import { useLiveQuery } from "dexie-react-hooks";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { canWrite, useAuth, useDb } from "../auth/AuthProvider";
import { Badge, Empty, ErrorNote, Field, PageHeader } from "../components/ui";
import { friendlyError } from "../lib/api";
import { ago } from "../lib/format";
import { type AccountForm, accountBody } from "../lib/accounts";
import { accountApi } from "../lib/mutations";

const schema = z
  .object({
    name: z.string().min(1, "Required").max(120),
    provider: z.enum(["mock", "prometheus", "azure"]),
    external_ref: z.string().min(1, "Required").max(200),
    scenario: z.enum(["small", "medium", "large"]),
    source: z.enum(["node_exporter", "otel"]),
    job: z.string().max(100),
    auth: z.enum(["none", "token", "basic"]),
    token: z.string(),
    username: z.string(),
    password: z.string(),
  })
  .superRefine((v, ctx) => {
    if (v.provider !== "prometheus") return;
    if (!/^https?:\/\//.test(v.external_ref))
      ctx.addIssue({ code: "custom", path: ["external_ref"], message: "Start with http:// or https://" });
    if (v.auth === "token" && !v.token) ctx.addIssue({ code: "custom", path: ["token"], message: "Required" });
    if (v.auth === "basic" && !v.username) ctx.addIssue({ code: "custom", path: ["username"], message: "Required" });
  });
type Form = z.infer<typeof schema> & AccountForm;

const demoRef = () => `demo-${Math.random().toString(36).slice(2, 8)}`;
const PROMETHEUS_URL = "http://localhost:9090";

function AddAccount({ onDone }: { onDone: () => void }) {
  const db = useDb();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<Form>({
    resolver: zodResolver(schema),
    defaultValues: {
      provider: "mock", scenario: "small", external_ref: demoRef(), source: "node_exporter", job: "",
      auth: "none", token: "", username: "", password: "",
    },
  });
  const provider = watch("provider");
  const auth = watch("auth");
  const source = watch("source");

  // swap the placeholder id for a sensible default when the provider changes
  useEffect(() => {
    const ref = getValues("external_ref");
    if (provider === "prometheus" && ref.startsWith("demo-")) setValue("external_ref", PROMETHEUS_URL);
    if (provider === "mock" && ref === PROMETHEUS_URL) setValue("external_ref", demoRef());
  }, [provider, getValues, setValue]);

  async function submit(v: Form) {
    setError(null);
    try {
      await accountApi.create(db, accountBody(v));
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
          <option value="prometheus">Prometheus (Azure, AWS, GCP or any server)</option>
          <option value="azure">Microsoft Azure (coming soon)</option>
        </select>
      </Field>
      <Field
        label={provider === "mock" ? "Demo account id" : provider === "prometheus" ? "Prometheus URL" : "Subscription id"}
        error={errors.external_ref?.message}
      >
        <input className="input" {...register("external_ref")} />
      </Field>
      {provider === "mock" && (
        <Field label="Size of the demo fleet">
          <select className="input" {...register("scenario")}>
            <option value="small">Small (5 VMs)</option>
            <option value="medium">Medium (25 VMs)</option>
            <option value="large">Large (300 VMs, load testing: too big for a free database)</option>
          </select>
        </Field>
      )}
      {provider === "prometheus" && (
        <>
          <Field label="How the VMs report">
            <select className="input" {...register("source")}>
              <option value="node_exporter">node_exporter (Prometheus scrapes each VM)</option>
              <option value="otel">OpenTelemetry Collector (each VM pushes its metrics)</option>
            </select>
          </Field>
          <Field label="Job name (optional)">
            <input className="input" placeholder={source === "otel" ? "hosts" : "node"} {...register("job")} />
          </Field>
          <Field label="Authentication">
            <select className="input" {...register("auth")}>
              <option value="none">None</option>
              <option value="token">Bearer token</option>
              <option value="basic">Username and password (e.g. Grafana Cloud)</option>
            </select>
          </Field>
          {auth === "token" && (
            <Field label="Token" error={errors.token?.message}>
              <input className="input" type="password" autoComplete="off" {...register("token")} />
            </Field>
          )}
          {auth === "basic" && (
            <>
              <Field label="Username" error={errors.username?.message}>
                <input className="input" autoComplete="off" {...register("username")} />
              </Field>
              <Field label="Password or API key">
                <input className="input" type="password" autoComplete="off" {...register("password")} />
              </Field>
            </>
          )}
          <p className="text-sm text-muted md:col-span-2">
            SyncViewer lists every VM in this job, but can't start or stop them. New VMs appear on the next collection.
          </p>
        </>
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
  if (!data) return <p className="text-muted">Loading…</p>;
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
        <Empty>
          No accounts yet.
          {writer
            ? " Add a demo account to see SyncViewer in action, or connect a Prometheus server to watch real VMs."
            : " Your access is read-only, so you can't add accounts. Ask an admin to change your role."}
        </Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.accounts.map((a) => (
            <div key={a.id} className="card">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">{a.name}</h3>
                <Badge tone={a.status === "active" ? "green" : a.status === "error" ? "red" : "amber"}>{a.status}</Badge>
              </div>
              <p className="text-sm text-muted">
                {a.provider_code}
                {a.provider_code === "prometheus" && a.config.source === "otel" ? " (OpenTelemetry)" : ""} ·{" "}
                {a.external_ref} · {counts.get(a.id) ?? 0} VMs
              </p>
              <p className="text-sm text-muted">Last collected: {a.last_collected_at ? ago(a.last_collected_at) : "not yet"}</p>
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
