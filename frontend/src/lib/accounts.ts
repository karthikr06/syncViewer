export interface AccountForm {
  name: string;
  provider: "mock" | "prometheus" | "azure";
  external_ref: string;
  scenario: "small" | "medium" | "large";
  source: "node_exporter" | "otel";
  job: string;
  auth: "none" | "token" | "basic";
  token: string;
  username: string;
  password: string;
}

export interface AccountCreate {
  name: string;
  provider: AccountForm["provider"];
  external_ref: string;
  config: Record<string, string>;
  credentials?: Record<string, string>;
}

/** The create-account request for each provider: config and credentials differ. */
export function accountBody(v: AccountForm): AccountCreate {
  const base = { name: v.name, provider: v.provider, external_ref: v.external_ref.trim() };
  if (v.provider === "mock") return { ...base, config: { scenario: v.scenario } };
  if (v.provider !== "prometheus") return { ...base, config: {} };
  let credentials: Record<string, string> | undefined;
  if (v.auth === "token") credentials = { token: v.token };
  if (v.auth === "basic") credentials = { username: v.username, password: v.password };
  return { ...base, config: { source: v.source, ...(v.job.trim() ? { job: v.job.trim() } : {}) }, credentials };
}
