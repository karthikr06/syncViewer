import { useQueryClient } from "@tanstack/react-query";
import type { Session } from "@supabase/supabase-js";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, setAuthRejectedHandler } from "../lib/api";
import { deleteLocalDatabase, deleteOtherUsersDatabases, getState, LocalDb, setState } from "../lib/db";
import { supabase } from "../lib/supabase";
import { startSync } from "../lib/sync";
import type { Me, Role } from "../lib/types";

const LAST_USER_KEY = "sv:last-user";

interface AuthValue {
  loading: boolean;
  user: { id: string; email: string } | null;
  me: Me | null;
  role: Role | null;
  db: LocalDb | null;
  /** signed-in from the stored session but currently unable to verify it (offline) */
  offlineSession: boolean;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthValue | null>(null);

function readLastUser(): { id: string; email: string } | null {
  try {
    const raw = localStorage.getItem(LAST_USER_KEY);
    return raw ? (JSON.parse(raw) as { id: string; email: string }) : null;
  } catch {
    return null;
  }
}

function rememberUser(u: { id: string; email: string } | null) {
  try {
    if (u) localStorage.setItem(LAST_USER_KEY, JSON.stringify(u));
    else localStorage.removeItem(LAST_USER_KEY);
  } catch {
    /* storage unavailable: offline boot just won't work */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<Session | null>(null);
  const [offlineUser, setOfflineUser] = useState<{ id: string; email: string } | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [db, setDb] = useState<LocalDb | null>(null);
  const userRef = useRef<string | null>(null);

  const user = useMemo(
    () => (session?.user ? { id: session.user.id, email: session.user.email ?? "" } : offlineUser),
    [session, offlineUser],
  );

  const wipe = useCallback(
    async (userId: string | null) => {
      if (userId) await deleteLocalDatabase(userId).catch(() => undefined);
      try {
        if ("caches" in window) await Promise.all((await caches.keys()).map((k) => caches.delete(k)));
      } catch {
        /* ignore */
      }
      rememberUser(null);
      qc.clear();
      setMe(null);
      setDb(null);
    },
    [qc],
  );

  const logout = useCallback(async () => {
    const id = userRef.current;
    try {
      await supabase.auth.signOut();
    } catch {
      await supabase.auth.signOut({ scope: "local" }).catch(() => undefined);
    }
    await wipe(id);
    setSession(null);
    setOfflineUser(null);
  }, [wipe]);

  // 1. restore the persisted session; a network failure must never log the user out
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data, error } = await supabase.auth.getSession();
        if (cancelled) return;
        if (data.session) setSession(data.session);
        else if (error && !navigator.onLine) setOfflineUser(readLastUser());
        else if (error?.name === "AuthRetryableFetchError") setOfflineUser(readLastUser());
      } catch {
        if (!cancelled) setOfflineUser(readLastUser());
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    const { data: sub } = supabase.auth.onAuthStateChange((event, s) => {
      if (event === "SIGNED_OUT") {
        const id = userRef.current;
        setSession(null);
        setOfflineUser(null);
        void wipe(id);
      } else if (s) {
        setSession(s);
        setOfflineUser(null);
      }
    });
    setAuthRejectedHandler(() => void logout());
    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
      setAuthRejectedHandler(null);
    };
  }, [wipe, logout]);

  // 2. open this user's local database and start syncing
  useEffect(() => {
    if (!user) {
      userRef.current = null;
      return;
    }
    userRef.current = user.id;
    rememberUser(user);
    void deleteOtherUsersDatabases(user.id);
    const local = new LocalDb(user.id);
    setDb(local);
    let stop: (() => void) | undefined;
    let cancelled = false;

    void getState<Me>(local, "me").then((cached) => {
      if (!cancelled && cached && cached.id === user.id) setMe(cached);
    });
    const refreshMe = async () => {
      try {
        const fresh = await api<Me>("/me");
        if (cancelled) return;
        setMe(fresh);
        await setState(local, "me", fresh);
      } catch {
        /* offline or server down: keep the cached role */
      }
    };
    void refreshMe();
    window.addEventListener("online", refreshMe);
    stop = startSync(local);

    return () => {
      cancelled = true;
      window.removeEventListener("online", refreshMe);
      stop?.();
      local.close();
    };
  }, [user?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const value: AuthValue = {
    loading,
    user,
    me,
    role: me?.role ?? null,
    db,
    offlineSession: !session && !!offlineUser,
    logout,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

/** The signed-in user's local database; only call below the auth guard. */
export function useDb(): LocalDb {
  const { db } = useAuth();
  if (!db) throw new Error("Local database not ready");
  return db;
}

export const canWrite = (role: Role | null) => role === "admin" || role === "user";
