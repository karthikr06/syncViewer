import { useLiveQuery } from "dexie-react-hooks";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useDb } from "../auth/AuthProvider";
import { Badge, Empty, Pager, PageHeader, healthTone, powerTone } from "../components/ui";
import { paginate } from "../lib/format";

const PAGE_SIZE = 12;

export function Resources() {
  const db = useDb();
  const [q, setQ] = useState("");
  const [account, setAccount] = useState("");
  const [power, setPower] = useState("");
  const [health, setHealth] = useState("");
  const [region, setRegion] = useState("");
  const [sort, setSort] = useState<"name" | "region" | "power_state" | "size_sku">("name");
  const [page, setPage] = useState(1);

  const data = useLiveQuery(
    async () => ({
      resources: await db.resources.toArray(),
      accounts: await db.cloud_accounts.toArray(),
    }),
    [db],
  );

  const filtered = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    return data.resources
      .filter(
        (r) =>
          (!needle || r.name.toLowerCase().includes(needle) || r.external_id.toLowerCase().includes(needle)) &&
          (!account || r.account_id === account) &&
          (!power || r.power_state === power) &&
          (!health || r.health_state === health) &&
          (!region || r.region === region),
      )
      .sort((a, b) => String(a[sort] ?? "").localeCompare(String(b[sort] ?? "")));
  }, [data, q, account, power, health, region, sort]);

  if (!data) return <p className="text-muted">Loading…</p>;
  const regions = [...new Set(data.resources.map((r) => r.region).filter(Boolean))] as string[];
  const view = paginate(filtered, page, PAGE_SIZE);
  const accountName = new Map(data.accounts.map((a) => [a.id, a.name]));
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };

  return (
    <>
      <PageHeader title="Resources" subtitle="Virtual machines across your cloud accounts" />
      <div className="card mb-3 grid gap-2 md:grid-cols-6">
        <input className="input md:col-span-2" placeholder="Search name or id" value={q} onChange={(e) => reset(setQ)(e.target.value)} />
        <select className="input" value={account} onChange={(e) => reset(setAccount)(e.target.value)}>
          <option value="">All accounts</option>
          {data.accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <select className="input" value={power} onChange={(e) => reset(setPower)(e.target.value)}>
          <option value="">Any power state</option>
          <option value="running">running</option>
          <option value="stopped">stopped</option>
          <option value="deallocated">deallocated</option>
        </select>
        <select className="input" value={health} onChange={(e) => reset(setHealth)(e.target.value)}>
          <option value="">Any health</option>
          <option value="healthy">healthy</option>
          <option value="degraded">degraded</option>
          <option value="unavailable">unavailable</option>
        </select>
        <select className="input" value={region} onChange={(e) => reset(setRegion)(e.target.value)}>
          <option value="">All regions</option>
          {regions.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </div>

      {view.total === 0 ? (
        <Empty>{data.resources.length === 0 ? "No VMs yet. Add a cloud account." : "No VMs match your filters."}</Empty>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full">
            <thead className="border-b border-line">
              <tr>
                {(["name", "region", "size_sku", "power_state"] as const).map((c) => (
                  <th key={c} className="th cursor-pointer" onClick={() => setSort(c)}>
                    {c.replace("_", " ")} {sort === c ? "▲" : ""}
                  </th>
                ))}
                <th className="th">Health</th>
                <th className="th">Account</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {view.rows.map((r) => (
                <tr key={r.id} className="hover:bg-subtle/60">
                  <td className="td font-medium">
                    <Link className="text-link hover:underline" to={`/resources/${r.id}`}>{r.name}</Link>
                  </td>
                  <td className="td">{r.region ?? "-"}</td>
                  <td className="td">{r.size_sku ?? "-"}</td>
                  <td className="td"><Badge tone={powerTone(r.power_state)}>{r.power_state}</Badge></td>
                  <td className="td"><Badge tone={healthTone(r.health_state)}>{r.health_state}</Badge></td>
                  <td className="td text-muted">{accountName.get(r.account_id) ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager page={view.page} pages={view.pages} total={view.total} onPage={setPage} />
    </>
  );
}
