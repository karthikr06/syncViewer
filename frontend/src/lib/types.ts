export type Role = "admin" | "user" | "viewer";

export interface Me {
  id: string;
  email: string;
  role: Role;
}

export interface Account {
  id: string;
  provider_code: string;
  name: string;
  external_ref: string;
  config: Record<string, unknown>;
  status: "active" | "paused" | "error";
  last_collected_at: string | null;
  last_error: string | null;
  deleted_at: string | null;
  created_at: string;
  version: number;
}

export interface Resource {
  id: string;
  account_id: string;
  external_id: string;
  name: string;
  region: string | null;
  size_sku: string | null;
  power_state: "running" | "stopped" | "deallocated" | "unknown";
  health_state: "healthy" | "degraded" | "unavailable" | "unknown";
  tags: Record<string, string>;
  attributes: Record<string, unknown>;
  first_seen_at: string;
  last_seen_at: string;
  deleted_at: string | null;
  version: number;
}

export type Severity = "info" | "warning" | "critical";

export interface AlertRule {
  id: string;
  name: string;
  account_id: string | null;
  resource_id: string | null;
  metric: string;
  operator: ">" | ">=" | "<" | "<=";
  threshold: number;
  duration_minutes: number;
  severity: Severity;
  is_enabled: boolean;
  deleted_at: string | null;
  version: number;
}

export interface Alert {
  id: number;
  rule_id: string;
  resource_id: string;
  state: "open" | "acknowledged" | "resolved";
  opened_at: string;
  resolved_at: string | null;
  value_at_open: number | null;
  version: number;
}

export interface Recommendation {
  id: number;
  resource_id: string | null;
  category: "rightsizing" | "reliability" | "capacity" | "waste" | "pattern";
  severity: Severity;
  title: string;
  detail: string;
  evidence: Record<string, unknown>;
  status: "new" | "dismissed" | "done";
  source: "rule" | "agent";
  created_at: string;
  updated_at: string;
  version: number;
}

export interface Digest {
  id: number;
  period_start: string;
  period_end: string;
  summary_md: string;
  generated_by: "rules" | "agent";
  created_at: string;
  version: number;
}

export interface Incident {
  id: number;
  resource_id: string;
  started_at: string;
  ended_at: string | null;
  kind: "outage" | "degraded";
  version: number;
}

export interface Rollup {
  resource_id: string;
  bucket_start: string;
  up_samples: number;
  total_samples: number;
  avg_cpu: number | null;
  p95_cpu: number | null;
  max_cpu: number | null;
  avg_memory: number | null;
  max_disk: number | null;
  version: number;
}

export interface Sample {
  resource_id: string;
  metric: string;
  ts: string;
  value: number;
}

export interface AdminUser {
  id: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface CollectorRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  accounts_processed: number;
  samples_inserted: number;
  errors: number;
  error_details: { account_id: string; error: string }[] | null;
}

export interface PageOf<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type EntityName =
  | "cloud_accounts"
  | "resources"
  | "alert_rules"
  | "alerts"
  | "recommendations"
  | "insight_digests"
  | "incidents"
  | "uptime_rollups";
