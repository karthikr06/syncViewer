import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import type { Role } from "./lib/types";

// Pages are split into their own chunks; the service worker precaches all of them, so they
// still load offline.
const page = <K extends string>(load: () => Promise<Record<K, () => JSX.Element>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })));
const Accounts = page(() => import("./pages/Accounts"), "Accounts");
const Admin = page(() => import("./pages/Admin"), "Admin");
const Alerts = page(() => import("./pages/Alerts"), "Alerts");
const ChangePassword = page(() => import("./pages/ChangePassword"), "ChangePassword");
const Dashboard = page(() => import("./pages/Dashboard"), "Dashboard");
const Insights = page(() => import("./pages/Insights"), "Insights");
const Recommendations = page(() => import("./pages/Recommendations"), "Recommendations");
const ResourceDetail = page(() => import("./pages/ResourceDetail"), "ResourceDetail");
const Resources = page(() => import("./pages/Resources"), "Resources");

function Splash() {
  return <div className="flex min-h-screen items-center justify-center text-slate-500">Loading…</div>;
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const { loading, user, db } = useAuth();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/login" replace />;
  if (!db) return <Splash />;
  return children;
}

function RequireRole({ roles, children }: { roles: Role[]; children: JSX.Element }) {
  const { role } = useAuth();
  if (!role) return <Splash />;
  if (!roles.includes(role)) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  const { user, loading } = useAuth();
  return (
    <Suspense fallback={<Splash />}>
      <Routes>
        <Route
          path="/login"
          element={loading ? <Splash /> : user ? <Navigate to="/" replace /> : <Login />}
        />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="resources" element={<Resources />} />
          <Route path="resources/:id" element={<ResourceDetail />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="recommendations" element={<Recommendations />} />
          <Route path="insights" element={<Insights />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="account/password" element={<ChangePassword />} />
          <Route
            path="admin"
            element={
              <RequireRole roles={["admin"]}>
                <Admin />
              </RequireRole>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
