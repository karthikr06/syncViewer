const e = import.meta.env;

export const env = {
  supabaseUrl: (e.VITE_SUPABASE_URL as string | undefined) ?? "",
  supabaseAnonKey: (e.VITE_SUPABASE_ANON_KEY as string | undefined) ?? "",
  apiUrl: ((e.VITE_API_URL as string | undefined) ?? "http://localhost:8000").replace(/\/$/, ""),
  syncIntervalMs: Number(e.VITE_SYNC_INTERVAL_MS ?? 30_000),
  /** show "Continue with Google" only once the provider is enabled in Supabase */
  googleAuth: e.VITE_ENABLE_GOOGLE_AUTH === "true",
};

export const missingConfig: string[] = [
  !env.supabaseUrl && "VITE_SUPABASE_URL",
  !env.supabaseAnonKey && "VITE_SUPABASE_ANON_KEY",
].filter(Boolean) as string[];
