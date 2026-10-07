import { beforeEach, describe, expect, it } from "vitest";
import { LocalDb } from "./db";
import { applyRows } from "./sync";

let db: LocalDb;
beforeEach(async () => {
  db = new LocalDb(`test-${Math.random()}`);
});

const resource = (id: string, version: number, extra: Record<string, unknown> = {}) => ({
  id,
  account_id: "acc",
  external_id: id,
  name: id,
  version,
  deleted_at: null,
  ...extra,
});

describe("applyRows", () => {
  it("upserts and is idempotent", async () => {
    await applyRows(db, "resources", [resource("a", 5)]);
    await applyRows(db, "resources", [resource("a", 5)]);
    expect(await db.resources.count()).toBe(1);
  });

  it("never overwrites a newer local row with an older one (overlap re-reads)", async () => {
    await applyRows(db, "resources", [resource("a", 10, { name: "new" })]);
    await applyRows(db, "resources", [resource("a", 7, { name: "old" })]);
    expect((await db.resources.get("a"))?.name).toBe("new");
    await applyRows(db, "resources", [resource("a", 10, { name: "same-version" })]);
    expect((await db.resources.get("a"))?.name).toBe("same-version");
  });

  it("tombstones remove the row and everything hanging off it", async () => {
    await applyRows(db, "resources", [resource("a", 1)]);
    await db.incidents.put({ id: 1, resource_id: "a", started_at: "x", ended_at: null, kind: "outage", version: 1 });
    await db.samples.put({ resource_id: "a", metric: "cpu_percent", ts: "2026-01-01T00:00:00.000Z", value: 1 });
    await applyRows(db, "resources", [resource("a", 2, { deleted_at: "2026-01-02T00:00:00Z" })]);
    expect(await db.resources.count()).toBe(0);
    expect(await db.incidents.count()).toBe(0);
    expect(await db.samples.count()).toBe(0);
  });

  it("an account tombstone removes its resources", async () => {
    await applyRows(db, "resources", [resource("a", 1), resource("b", 2)]);
    await applyRows(db, "cloud_accounts", [{ id: "acc", version: 3, deleted_at: "2026-01-02T00:00:00Z" }]);
    expect(await db.resources.count()).toBe(0);
  });

  it("keeps the highest version when one page repeats a key", async () => {
    await applyRows(db, "resources", [
      resource("a", 4, { name: "v4" }),
      resource("a", 9, { name: "v9" }),
      resource("a", 6, { name: "v6" }),
    ]);
    expect((await db.resources.get("a"))?.name).toBe("v9");
  });

  it("a later tombstone in the same page wins over an earlier upsert", async () => {
    await applyRows(db, "resources", [
      resource("a", 1),
      resource("a", 2, { deleted_at: "2026-01-02T00:00:00Z" }),
      resource("b", 3),
    ]);
    expect(await db.resources.toCollection().primaryKeys()).toEqual(["b"]);
  });

  it("normalises rollup keys so repeated pulls do not duplicate", async () => {
    const r = { resource_id: "a", up_samples: 1, total_samples: 1, version: 1 };
    await applyRows(db, "uptime_rollups", [{ ...r, bucket_start: "2026-01-01T10:00:00Z" }]);
    await applyRows(db, "uptime_rollups", [{ ...r, bucket_start: "2026-01-01T10:00:00+00:00" }]);
    expect(await db.uptime_rollups.count()).toBe(1);
  });
});
