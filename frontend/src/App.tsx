import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";

// Lazy page chunks; the service worker precaches them all, so they still load offline
const page = <K extends string>(load: () => Promise<Record<K, () => JSX.Element>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })));
const Accounts = page(() => import("./pages/Accounts"), "Accounts");
const Alerts = page(() => import("./pages/Alerts"), "Alerts");
const ChangePassword = page(() => import("./pages/ChangePassword"), "ChangePassword");
const Dashboard = page(() => import("./pages/Dashboard"), "Dashboard");
const Insights = page(() => import("./pages/Insights"), "Insights");
const Recommendations = page(() => import("./pages/Recommendations"), "Recommendations");
const ResourceDetail = page(() => import("./pages/ResourceDetail"), "ResourceDetail");
const Resources = page(() => import("./pages/Resources"), "Resources");
const Team = page(() => import("./pages/Team"), "Team");

function Splash() {
  return <div className="flex min-h-screen items-center justify-center text-muted">Loading…</div>;
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const { loading, user, db } = useAuth();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/login" replace />;
  if (!db) return <Splash />;
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
          <Route path="team" element={<Team />} />
          <Route path="admin" element={<Navigate to="/team" replace />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
