import type { Rollup } from "./types";

export function fmtDate(ts: string | null | undefined): string {
  if (!ts) return "-";
  return new Date(ts).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ago(ts: number | string | null | undefined): string {
  if (ts == null) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function duration(startIso: string, endIso: string | null): string {
  const ms = (endIso ? new Date(endIso).getTime() : Date.now()) - new Date(startIso).getTime();
  const m = Math.max(0, Math.round(ms / 60000));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function uptimePercent(rollups: Pick<Rollup, "up_samples" | "total_samples">[]): number | null {
  const up = rollups.reduce((a, r) => a + r.up_samples, 0);
  const total = rollups.reduce((a, r) => a + r.total_samples, 0);
  return total === 0 ? null : (100 * up) / total;
}

export const pct = (v: number | null | undefined, digits = 2) =>
  v == null ? "-" : `${v.toFixed(digits)}%`;

/** Client-side pagination. */
export function paginate<T>(items: T[], page: number, size: number) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const p = Math.min(Math.max(1, page), pages);
  return { rows: items.slice((p - 1) * size, p * size), page: p, pages, total: items.length };
}
