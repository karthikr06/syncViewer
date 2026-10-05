import { useSyncExternalStore } from "react";

export interface SyncStatus {
  state: "idle" | "syncing" | "offline" | "error";
  lastSync: number | null;
  error: string | null;
}

let status: SyncStatus = {
  state: typeof navigator !== "undefined" && !navigator.onLine ? "offline" : "idle",
  lastSync: null,
  error: null,
};
const listeners = new Set<() => void>();

export function setSyncStatus(patch: Partial<SyncStatus>) {
  status = { ...status, ...patch };
  listeners.forEach((l) => l());
}

export function useSyncStatus(): SyncStatus {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => status,
  );
}
