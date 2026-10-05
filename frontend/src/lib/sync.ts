import { api, NetworkError } from "./api";
import { env } from "./env";
import { getState, setState, type LocalDb } from "./db";
import { setSyncStatus } from "./syncStore";
import type { EntityName, Sample } from "./types";

/** Entities pulled with version cursors, in dependency order. */
export const ENTITIES: EntityName[] = [
  "cloud_accounts",
  "resources",
  "alert_rules",
  "alerts",
  "recommendations",
  "insight_digests",
  "incidents",
  "uptime_rollups",
];

/** Re-read this many versions behind the cursor: sequence values can commit out of order, so a
 * strict `> cursor` read could skip a row. Idempotent, version-guarded upserts make it safe. */
export const SYNC_OVERLAP = 500;
export const SAMPLE_OVERLAP_MS = 10 * 60_000;
const SAMPLE_WINDOW_MS = 24 * 3600_000;
const ROLLUP_WINDOW_MS = 14 * 24 * 3600_000;

interface ChangesPage {
  rows: Record<string, unknown>[];
  next_since: number;
  has_more: boolean;
}

type AnyRow = Record<string, unknown> & { version?: number; deleted_at?: string | null };

const iso = (v: unknown) => new Date(String(v)).toISOString();

function keyOf(entity: EntityName, row: AnyRow): unknown {
  if (entity === "uptime_rollups") return [row.resource_id, row.bucket_start];
  return row.id;
}

/** Delete everything that hangs off a resource (used for tombstones). */
export async function dropResourceData(db: LocalDb, resourceId: string): Promise<void> {
  await db.transaction(
    "rw",
    [db.incidents, db.alerts, db.uptime_rollups, db.samples],
    async () => {
      await db.incidents.where("resource_id").equals(resourceId).delete();
      await db.alerts.where("resource_id").equals(resourceId).delete();
      await db.uptime_rollups.where("resource_id").equals(resourceId).delete();
      await db.samples.where("[resource_id+metric]").between([resourceId, ""], [resourceId, "￿"]).delete();
    },
  );
}

/**
 * Apply server rows idempotently:
 *  - tombstones (deleted_at set) remove the local row (and what depends on it),
 *  - otherwise upsert, but never overwrite a newer local version with an older one.
 */
export async function applyRows(db: LocalDb, entity: EntityName, rows: AnyRow[]): Promise<void> {
  const table = db.table(entity);
  for (const raw of rows) {
    const row: AnyRow = { ...raw };
    if (entity === "uptime_rollups") row.bucket_start = iso(row.bucket_start);
    const key = keyOf(entity, row);

    if (row.deleted_at) {
      await table.delete(key as never);
      if (entity === "resources") await dropResourceData(db, row.id as string);
      if (entity === "cloud_accounts") {
        const ids = await db.resources.where("account_id").equals(row.id as string).primaryKeys();
        for (const rid of ids) {
          await db.resources.delete(rid);
          await dropResourceData(db, rid);
        }
      }
      continue;
    }
    const existing = (await table.get(key as never)) as AnyRow | undefined;
    if (existing && (existing.version ?? 0) > (row.version ?? 0)) continue;
    await table.put(row as never);
  }
}

async function pullEntity(db: LocalDb, entity: EntityName): Promise<void> {
  const cursor = (await getState<number>(db, `cursor:${entity}`)) ?? 0;
  let since = Math.max(0, cursor - SYNC_OVERLAP);
  let max = cursor;
  for (;;) {
    const page = await api<ChangesPage>(`/sync/changes?entity=${entity}&since=${since}&limit=500`);
    await applyRows(db, entity, page.rows as AnyRow[]);
    max = Math.max(max, page.next_since);
    if (!page.has_more || page.next_since <= since) break;
    since = page.next_since;
  }
  if (max !== cursor) await setState(db, `cursor:${entity}`, max);
}

interface MetricsPage {
  rows: Sample[];
  next_since: string | null;
  has_more: boolean;
}

async function pullSamples(db: LocalDb): Promise<void> {
  const cursor = await getState<string>(db, "cursor:samples");
  let since = cursor ? new Date(new Date(cursor).getTime() - SAMPLE_OVERLAP_MS) : null;
  let latest = cursor ?? "";
  for (let guard = 0; guard < 50; guard++) {
    const q = new URLSearchParams({ window: "24", step: "900" });
    if (since) q.set("since", since.toISOString());
    const page = await api<MetricsPage>(`/sync/metrics?${q}`);
    if (page.rows.length) {
      await db.samples.bulkPut(page.rows.map((r) => ({ ...r, ts: iso(r.ts) })));
    }
    if (page.next_since && page.next_since > latest) latest = page.next_since;
    if (!page.has_more || !page.next_since) break;
    const next = new Date(page.next_since);
    if (since && next <= since) break;
    since = next;
  }
  if (latest && latest !== cursor) await setState(db, "cursor:samples", latest);
  // keep only the last 24 h of samples and 14 days of rollups locally
  await db.samples.where("ts").below(new Date(Date.now() - SAMPLE_WINDOW_MS).toISOString()).delete();
  await db.uptime_rollups
    .where("bucket_start")
    .below(new Date(Date.now() - ROLLUP_WINDOW_MS).toISOString())
    .delete();
}

let running: Promise<void> | null = null;

/** One full pass. Concurrent calls share the same run. */
export function syncOnce(db: LocalDb): Promise<void> {
  if (running) return running;
  running = (async () => {
    setSyncStatus({ state: "syncing" });
    try {
      for (const entity of ENTITIES) await pullEntity(db, entity);
      await pullSamples(db);
      const at = Date.now();
      await setState(db, "last_sync", at);
      setSyncStatus({ state: "idle", lastSync: at, error: null });
    } catch (e) {
      const offline = e instanceof NetworkError || !navigator.onLine;
      setSyncStatus({
        state: offline ? "offline" : "error",
        error: offline ? null : e instanceof Error ? e.message : "Sync failed",
      });
      throw e;
    } finally {
      running = null;
    }
  })();
  return running;
}

/** Starts the background loop: on start, on reconnect, on tab focus, and every interval while the
 * tab is visible. Backs off exponentially after failures. Returns a stop function. */
export function startSync(db: LocalDb): () => void {
  let stopped = false;
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const delay = () => Math.min(5 * 60_000, env.syncIntervalMs * 2 ** failures);

  const tick = async () => {
    if (stopped) return;
    if (!document.hidden) {
      if (!navigator.onLine) {
        setSyncStatus({ state: "offline" });
      } else {
        try {
          await syncOnce(db);
          failures = 0;
        } catch {
          failures = Math.min(failures + 1, 4);
        }
      }
    }
    if (!stopped) timer = setTimeout(tick, delay());
  };

  const kick = () => {
    if (timer) clearTimeout(timer);
    failures = 0;
    void tick();
  };
  const goOffline = () => setSyncStatus({ state: "offline" });
  const onVisible = () => {
    if (!document.hidden) kick();
  };

  window.addEventListener("online", kick);
  window.addEventListener("offline", goOffline);
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("sv:sync-now", kick);
  void getState<number>(db, "last_sync").then((t) => t && setSyncStatus({ lastSync: t }));
  void tick();

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    window.removeEventListener("online", kick);
    window.removeEventListener("offline", goOffline);
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("sv:sync-now", kick);
  };
}

export const requestSync = () => window.dispatchEvent(new Event("sv:sync-now"));
