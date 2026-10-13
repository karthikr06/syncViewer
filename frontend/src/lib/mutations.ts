/** Writes go to the API (they need a network); the local cache is updated right away with the
 * server's answer and reconciled by the next sync. */
import { api } from "./api";
import { applyRows, dropResourceData, requestSync } from "./sync";
import type { LocalDb } from "./db";
import type {
  Account,
  Alert,
  AlertRule,
  Digest,
  EntityName,
  Recommendation,
  Resource,
  VmAction,
  VmActionName,
} from "./types";

export class OfflineError extends Error {
  constructor() {
    super("You're offline. Changes need a connection - try again when you're back online.");
  }
}

function requireOnline() {
  if (!navigator.onLine) throw new OfflineError();
}

type Row = Record<string, unknown>;

async function write<T extends Row>(
  db: LocalDb,
  entity: EntityName,
  call: () => Promise<T>,
): Promise<T> {
  requireOnline();
  const row = await call();
  await applyRows(db, entity, [row]);
  requestSync();
  return row;
}

export const accountApi = {
  create: (db: LocalDb, body: unknown) =>
    write<Account & Row>(db, "cloud_accounts", () =>
      api("/cloud-accounts", { method: "POST", body: JSON.stringify(body) }),
    ).then(async (a) => {
      requestSync(); // pulls the freshly discovered resources
      return a;
    }),
  update: (db: LocalDb, id: string, body: unknown) =>
    write<Account & Row>(db, "cloud_accounts", () =>
      api(`/cloud-accounts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    ),
  remove: async (db: LocalDb, id: string) => {
    requireOnline();
    await api(`/cloud-accounts/${id}`, { method: "DELETE" });
    const ids = await db.resources.where("account_id").equals(id).primaryKeys();
    for (const rid of ids) {
      await db.resources.delete(rid);
      await dropResourceData(db, rid);
    }
    await db.cloud_accounts.delete(id);
    requestSync();
  },
  collectNow: async (id: string) => {
    requireOnline();
    const r = await api<{ samples_inserted: number }>(`/cloud-accounts/${id}/collect-now`, {
      method: "POST",
    });
    requestSync();
    return r;
  },
};

export const ruleApi = {
  create: (db: LocalDb, body: unknown) =>
    write<AlertRule & Row>(db, "alert_rules", () =>
      api("/alert-rules", { method: "POST", body: JSON.stringify(body) }),
    ),
  update: (db: LocalDb, id: string, body: unknown) =>
    write<AlertRule & Row>(db, "alert_rules", () =>
      api(`/alert-rules/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    ),
  remove: async (db: LocalDb, id: string) => {
    requireOnline();
    await api(`/alert-rules/${id}`, { method: "DELETE" });
    await db.alert_rules.delete(id);
    requestSync();
  },
};

/** Optimistic: flip the local row first, roll back if the server refuses. */
export async function acknowledgeAlert(db: LocalDb, id: number): Promise<void> {
  requireOnline();
  const before = await db.alerts.get(id);
  if (before) await db.alerts.update(id, { state: "acknowledged" });
  try {
    const row = await api<Alert & Row>(`/alerts/${id}/acknowledge`, { method: "POST" });
    await applyRows(db, "alerts", [row]);
    requestSync();
  } catch (e) {
    if (before) await db.alerts.put(before);
    throw e;
  }
}

export async function setRecommendationStatus(
  db: LocalDb,
  id: number,
  status: Recommendation["status"],
): Promise<void> {
  requireOnline();
  const before = await db.recommendations.get(id);
  if (before) await db.recommendations.update(id, { status });
  try {
    const row = await api<Recommendation & Row>(`/recommendations/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    await applyRows(db, "recommendations", [row]);
    requestSync();
  } catch (e) {
    if (before) await db.recommendations.put(before);
    throw e;
  }
}

export async function generateDigest(db: LocalDb, days: number): Promise<void> {
  requireOnline();
  const row = await api<Digest & Row>(`/insights/digests/generate?days=${days}`, { method: "POST" });
  await applyRows(db, "insight_digests", [row]);
  requestSync();
}

/** Start, stop, restart or deallocate a VM. The local copy reflects the new power state at once;
 * the next sync brings the server's version (and the collector later confirms it). Optionally
 * marks the recommendation that suggested the action as done. */
export async function vmAction(
  db: LocalDb,
  resourceId: string,
  action: VmActionName,
  recommendationId?: number,
): Promise<VmAction> {
  requireOnline();
  const r = await api<VmAction>(`/resources/${resourceId}/actions`, {
    method: "POST",
    body: JSON.stringify({ action, recommendation_id: recommendationId ?? null }),
  });
  if (r.to_state) {
    const power = r.to_state as Resource["power_state"];
    await db.resources.update(resourceId, {
      power_state: power,
      health_state: power === "running" ? "healthy" : "unavailable",
    });
  }
  if (recommendationId) await db.recommendations.update(recommendationId, { status: "done" });
  requestSync();
  return r;
}
