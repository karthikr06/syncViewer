import { env } from "./env";
import { supabase } from "./supabase";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** The server could not be reached (offline, DNS, CORS...). Never a reason to log out. */
export class NetworkError extends Error {
  constructor(message = "Can't reach the server. Check your connection.") {
    super(message);
  }
}

let onAuthRejected: (() => void) | null = null;
export function setAuthRejectedHandler(fn: (() => void) | null) {
  onAuthRejected = fn;
}

function detailOf(body: unknown, fallback: string): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .join("; ") || fallback;
  }
  return fallback;
}

async function accessToken(): Promise<string | undefined> {
  try {
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token;
  } catch {
    return undefined;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let retried = false;
  for (;;) {
    const token = await accessToken();
    const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
    if (init.body) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;

    let res: Response;
    try {
      res = await fetch(`${env.apiUrl}/api/v1${path}`, { ...init, headers });
    } catch {
      throw new NetworkError();
    }

    if (res.status === 401) {
      if (!retried) {
        retried = true;
        const { error } = await supabase.auth.refreshSession();
        if (error && error.name === "AuthRetryableFetchError") throw new NetworkError();
        continue;
      }
      // refreshed and still rejected: a definitive auth failure
      onAuthRejected?.();
      throw new ApiError(401, "Your session has expired. Please sign in again.");
    }
    if (res.status === 503 || res.status === 502 || res.status === 504) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, detailOf(body, "The server is temporarily unavailable."));
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, detailOf(body, `Request failed (${res.status}).`));
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }
}

export function friendlyError(e: unknown): string {
  if (e instanceof NetworkError || e instanceof ApiError) return e.message;
  return "Something went wrong. Please try again.";
}
