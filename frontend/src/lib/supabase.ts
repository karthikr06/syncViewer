import { createClient } from "@supabase/supabase-js";
import { env } from "./env";

// Supabase is used for login only. All data goes through our API.
export const supabase = createClient(
  env.supabaseUrl || "http://localhost:54321",
  env.supabaseAnonKey || "missing-anon-key",
  { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } },
);
