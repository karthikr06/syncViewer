import { useLiveQuery } from "dexie-react-hooks";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { canWrite, useAuth, useDb } from "../auth/AuthProvider";
import { Badge, Empty, ErrorNote, PageHeader } from "../components/ui";
import { api, friendlyError } from "../lib/api";
import { fmtDate } from "../lib/format";
import { generateDigest } from "../lib/mutations";
import { useSyncStatus } from "../lib/syncStore";
import { linkifyMarkdown, useVmIndex } from "../lib/vmLinks";
import { RecommendationCard } from "./Recommendations";

/** Model/cloud-sourced text is untrusted: markdown is rendered without raw HTML and sanitized.
 * VM names become links to the VM's page (in-app navigation, no page reload). */
function Md({ children }: { children: string }) {
  const vms = useVmIndex();
  return (
    <div className="prose-sm space-y-2 text-sm [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:ml-4 [&_li]:list-disc [&_ol>li]:list-decimal [&_code]:rounded [&_code]:bg-subtle [&_code]:px-1 [&_strong]:font-semibold [&_table]:w-full [&_td]:border-b [&_td]:px-2 [&_td]:py-1 [&_th]:px-2 [&_th]:text-left">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          a: ({ href, children: label }) =>
            href?.startsWith("/") ? (
              <Link className="link font-medium" to={href}>
                {label}
              </Link>
            ) : (
              <a className="link" href={href} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            ),
          code: ({ children: code, className }) => {
            const text = String(code);
            const id = vms.byName.get(text);
            return id && !className ? (
              <Link className="link font-mono font-medium" to={`/resources/${id}`}>
                {text}
              </Link>
            ) : (
              <code className={className}>{code}</code>
            );
          },
        }}
      >
        {linkifyMarkdown(children, vms)}
      </ReactMarkdown>
    </div>
  );
}

interface ChatMsg {
  from: "me" | "ai";
  text: string;
  tools?: string[];
}
interface ChatReply {
  reply: string;
  session_id: string;
  configured: boolean;
  tools_called: string[];
}

const PROMPTS = [
  "Which VM had the most downtime this week?",
  "What can I downsize?",
  "Will any disk fill up soon?",
  "Does any VM fail at the same time every day?",
];

function Chat({ disabled }: { disabled: boolean }) {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const session = useRef<string | undefined>(undefined);
  const end = useRef<HTMLDivElement>(null);

  async function send(message: string) {
    const m = message.trim();
    if (!m || busy) return;
    setError(null);
    setText("");
    setMsgs((x) => [...x, { from: "me", text: m }]);
    setBusy(true);
    try {
      const r = await api<ChatReply>("/agent/chat", {
        method: "POST",
        body: JSON.stringify({ message: m, session_id: session.current }),
      });
      session.current = r.session_id;
      setMsgs((x) => [...x, { from: "ai", text: r.reply, tools: r.tools_called }]);
    } catch (e) {
      setError(friendlyError(e));
    } finally {
      setBusy(false);
      setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }

  return (
    <div className="card flex flex-col">
      <h2 className="mb-2 font-semibold">Ask the assistant</h2>
      {disabled && <p className="mb-2 text-sm text-amber-700 dark:text-amber-300">Chat needs a network connection.</p>}
      <div className="mb-3 flex flex-wrap gap-2">
        {PROMPTS.map((p) => (
          <button key={p} className="btn-ghost text-xs" disabled={disabled || busy} onClick={() => void send(p)}>
            {p}
          </button>
        ))}
      </div>
      <div className="mb-3 max-h-96 min-h-[6rem] space-y-3 overflow-y-auto">
        {msgs.length === 0 && <p className="text-sm text-muted">Ask about uptime, incidents, trends or savings.</p>}
        {msgs.map((m, i) => (
          <div key={i} className={m.from === "me" ? "text-right" : ""}>
            <div className={`inline-block max-w-full rounded-xl px-3 py-2 text-left ${m.from === "me" ? "bg-accent text-white" : "bg-subtle"}`}>
              {m.from === "me" ? m.text : <Md>{m.text}</Md>}
            </div>
            {m.tools && m.tools.length > 0 && (
              <div className="mt-1 text-xs text-muted">used: {[...new Set(m.tools)].join(", ")}</div>
            )}
          </div>
        ))}
        {busy && <p className="text-sm text-muted">Thinking…</p>}
        <div ref={end} />
      </div>
      <ErrorNote message={error} />
      <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
        <input className="input" placeholder="Ask a question…" value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} disabled={disabled} />
        <button className="btn-primary" disabled={disabled || busy || !text.trim()}>Send</button>
      </form>
    </div>
  );
}

export function Insights() {
  const vms = useVmIndex();
  const db = useDb();
  const { role } = useAuth();
  const sync = useSyncStatus();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const data = useLiveQuery(
    async () => ({
      digests: await db.insight_digests.orderBy("period_end").reverse().toArray(),
      recs: await db.recommendations.where("status").equals("new").toArray(),
      resources: await db.resources.toArray(),
    }),
    [db],
  );
  if (!data) return <p className="text-muted">Loading…</p>;
  const offline = sync.state === "offline" || !navigator.onLine;
  const byId = new Map(data.resources.map((r) => [r.id, r]));
  const latest = data.digests[0];

  return (
    <>
      <PageHeader
        title="Insights"
        subtitle="Daily and weekly summaries, advice and an assistant"
        actions={
          canWrite(role) && (
            <button
              className="btn-primary"
              disabled={busy || offline}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await generateDigest(db, 7);
                } catch (e) {
                  setError(friendlyError(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Generating…" : "Generate weekly digest"}
            </button>
          )
        }
      />
      <ErrorNote message={error} />
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="card">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-semibold">Latest digest</h2>
              {latest && <Badge>{fmtDate(latest.period_end)}</Badge>}
            </div>
            {latest ? <Md>{latest.summary_md}</Md> : <Empty>No digest yet. One is created after the first collection.</Empty>}
          </div>
          {data.digests.length > 1 && (
            <details className="card">
              <summary className="cursor-pointer font-semibold">Earlier digests ({data.digests.length - 1})</summary>
              <div className="mt-3 space-y-4">
                {data.digests.slice(1, 8).map((d) => (
                  <div key={d.id}>
                    <div className="mb-1 text-xs text-muted">{fmtDate(d.period_start)} to {fmtDate(d.period_end)}</div>
                    <Md>{d.summary_md}</Md>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
        <Chat disabled={offline} />
      </div>

      <h2 className="mb-2 mt-6 font-semibold">Open recommendations</h2>
      {data.recs.length === 0 ? (
        <Empty>Nothing to improve right now.</Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {data.recs.slice(0, 8).map((r) => (
            <RecommendationCard key={r.id} rec={r} resource={r.resource_id ? byId.get(r.resource_id) : undefined} vms={vms} writer={canWrite(role)} onError={setError} />
          ))}
        </div>
      )}
    </>
  );
}
