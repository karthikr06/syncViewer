import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { ago } from "../lib/format";
import { requestSync } from "../lib/sync";
import { useSyncStatus } from "../lib/syncStore";
import { ErrorBoundary } from "./ErrorBoundary";
import { Badge } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", roles: ["admin", "user", "viewer"] },
  { to: "/resources", label: "Resources", roles: ["admin", "user", "viewer"] },
  { to: "/alerts", label: "Alerts", roles: ["admin", "user", "viewer"] },
  { to: "/recommendations", label: "Recommendations", roles: ["admin", "user", "viewer"] },
  { to: "/insights", label: "Insights", roles: ["admin", "user", "viewer"] },
  { to: "/accounts", label: "Cloud accounts", roles: ["admin", "user", "viewer"] },
  { to: "/admin", label: "Admin", roles: ["admin"] },
];

function SyncBadge() {
  const s = useSyncStatus();
  if (s.state === "syncing") return <Badge tone="blue">syncing…</Badge>;
  if (s.state === "offline") return <Badge tone="amber">offline, showing cached data</Badge>;
  if (s.state === "error")
    return (
      <button onClick={requestSync} title={s.error ?? ""}>
        <Badge tone="red">sync failed, retry</Badge>
      </button>
    );
  return <Badge tone="green">synced {ago(s.lastSync)}</Badge>;
}

export function Layout() {
  const { me, role, user, logout, offlineSession } = useAuth();
  const loc = useLocation();
  const items = NAV.filter((n) => !role || n.roles.includes(role));

  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 md:min-h-screen md:w-56 md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-3 md:block">
          <div className="text-lg font-bold">SyncViewer</div>
          <div className="text-xs text-slate-500 md:mt-1">{user?.email}</div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
          {items.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === "/"}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg px-3 py-2 text-sm ${
                  isActive
                    ? "bg-sky-600 text-white"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden px-4 py-4 md:block">
          {role && <Badge tone="gray">{role}</Badge>}
          <button className="btn-ghost mt-3 w-full" onClick={() => void logout()}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2 dark:border-slate-800 dark:bg-slate-900">
          <SyncBadge />
          <div className="flex items-center gap-2 md:hidden">
            {me && <Badge>{me.role}</Badge>}
            <button className="btn-ghost" onClick={() => void logout()}>
              Sign out
            </button>
          </div>
        </header>
        {offlineSession && (
          <div className="bg-amber-100 px-4 py-2 text-sm text-amber-900 dark:bg-amber-900/30 dark:text-amber-200">
            You're offline. Showing your cached data; changes are disabled until you reconnect.
          </div>
        )}
        <main className="mx-auto max-w-6xl p-4">
          <ErrorBoundary resetKey={loc.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
