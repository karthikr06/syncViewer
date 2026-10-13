import Dexie, { type Table } from "dexie";
import type {
  Account,
  Alert,
  AlertRule,
  Digest,
  Incident,
  Recommendation,
  Resource,
  Rollup,
  Sample,
} from "./types";

export interface SyncStateRow {
  key: string;
  value: unknown;
}

/** One IndexedDB database per signed-in user, mirroring the synced server entities. */
export class LocalDb extends Dexie {
  cloud_accounts!: Table<Account, string>;
  resources!: Table<Resource, string>;
  alert_rules!: Table<AlertRule, string>;
  alerts!: Table<Alert, number>;
  recommendations!: Table<Recommendation, number>;
  insight_digests!: Table<Digest, number>;
  incidents!: Table<Incident, number>;
  uptime_rollups!: Table<Rollup, [string, string]>;
  samples!: Table<Sample, [string, string, string]>;
  sync_state!: Table<SyncStateRow, string>;

  constructor(public userId: string) {
    super(dbName(userId));
    this.version(1).stores({
      cloud_accounts: "id, status",
      resources: "id, account_id, name, power_state, region",
      alert_rules: "id",
      alerts: "id, rule_id, resource_id, state",
      recommendations: "id, status, category, severity",
      insight_digests: "id, period_end",
      incidents: "id, resource_id, started_at",
      uptime_rollups: "[resource_id+bucket_start], resource_id, bucket_start",
      samples: "[resource_id+metric+ts], [resource_id+metric], ts",
      sync_state: "key",
    });
  }
}

export const dbName = (userId: string) => `syncviewer-${userId}`;

export async function getState<T>(db: LocalDb, key: string): Promise<T | undefined> {
  return (await db.sync_state.get(key))?.value as T | undefined;
}

export async function setState(db: LocalDb, key: string, value: unknown): Promise<void> {
  await db.sync_state.put({ key, value });
}

export async function deleteLocalDatabase(userId: string): Promise<void> {
  await Dexie.delete(dbName(userId));
}

/** Delete other users' local databases (left behind when a session expired instead of signing out). */
export async function deleteOtherUsersDatabases(userId: string): Promise<void> {
  try {
    const all = (await indexedDB.databases?.()) ?? [];
    for (const d of all) {
      if (d.name?.startsWith("syncviewer-") && d.name !== dbName(userId)) await Dexie.delete(d.name);
    }
  } catch {
    /* indexedDB.databases() unsupported: nothing we can enumerate */
  }
}
