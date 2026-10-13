import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { ago } from "../lib/format";
import { requestSync } from "../lib/sync";
import { useSyncStatus } from "../lib/syncStore";
import { getTheme, setTheme, watchSystemTheme, type ThemePref } from "../lib/theme";
import { RoleBadge } from "../pages/Team";
import { ErrorBoundary } from "./ErrorBoundary";
import { Badge } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/resources", label: "Resources" },
  { to: "/alerts", label: "Alerts" },
  { to: "/recommendations", label: "Recommendations" },
  { to: "/insights", label: "Insights" },
  { to: "/accounts", label: "Cloud accounts" },
  { to: "/team", label: "Team" },
];

function SyncBadge() {
  const s = useSyncStatus();
  if (s.state === "syncing") return <Badge tone="blue">syncing…</Badge>;
  if (s.state === "offline")
    return (
      <Badge tone="amber">
        {navigator.onLine ? "server unreachable" : "offline"}, showing cached data
      </Badge>
    );
  if (s.state === "error")
    return (
      <button onClick={requestSync} title={s.error ?? ""}>
        <Badge tone="red">sync failed, retry</Badge>
      </button>
    );
  return <Badge tone="green">synced {ago(s.lastSync)}</Badge>;
}

function ThemeSwitch() {
  const [pref, setPref] = useState<ThemePref>(getTheme);
  useEffect(() => watchSystemTheme(), []);
  const choose = (p: ThemePref) => {
    setTheme(p);
    setPref(p);
  };
  return (
    <div className="inline-flex rounded-lg border border-line p-0.5 text-xs" role="group" aria-label="Theme">
      {(["light", "dark", "system"] as ThemePref[]).map((p) => (
        <button
          key={p}
          onClick={() => choose(p)}
          aria-pressed={pref === p}
          className={`rounded-md px-2 py-1 capitalize ${pref === p ? "bg-subtle font-semibold text-ink" : "text-muted hover:text-ink"}`}
        >
          {p}
        </button>
      ))}
    </div>
  );
}

export function Layout() {
  const { me, role, user, logout, offlineSession } = useAuth();
  const loc = useLocation();

  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-line bg-surface md:sticky md:top-0 md:flex md:h-screen md:w-60 md:flex-col md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-4 md:block">
          <div className="text-lg font-bold tracking-tight">
            Sync<span className="text-accent">Viewer</span>
          </div>
          {me && <div className="truncate text-xs font-medium text-muted md:mt-1" title={me.workspace.name}>{me.workspace.name}</div>}
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive ? "bg-accent text-white shadow-sm" : "text-ink/80 hover:bg-subtle hover:text-ink"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden space-y-3 border-t border-line px-4 py-4 md:block">
          <div className="truncate text-sm" title={user?.email}>{user?.email}</div>
          {role && <div><RoleBadge role={role} /></div>}
          <ThemeSwitch />
          <NavLink className="block text-sm text-muted hover:text-ink hover:underline" to="/account/password">
            Change password
          </NavLink>
          <button className="btn-ghost w-full" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-between gap-2 border-b border-line bg-surface px-4 py-2">
          <SyncBadge />
          <div className="flex items-center gap-2 md:hidden">
            {role && <RoleBadge role={role} />}
            <ThemeSwitch />
            <button className="btn-ghost btn-sm" onClick={() => void logout()}>
              Sign out
            </button>
          </div>
        </header>
        {offlineSession && (
          <div className="bg-amber-100 px-4 py-2 text-sm text-amber-900 dark:bg-amber-900/30 dark:text-amber-200">
            You're offline. Showing your cached data; changes are disabled until you reconnect.
          </div>
        )}
        {role === "viewer" && (
          <div className="border-b border-line bg-subtle px-4 py-1.5 text-xs text-muted">
            You have view-only access to this workspace. You can still ask the AI assistant on the Insights page.
          </div>
        )}
        <main className="mx-auto max-w-6xl p-4 md:p-6">
          <ErrorBoundary resetKey={loc.pathname}>
            <Suspense fallback={<p className="text-muted">Loading…</p>}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
