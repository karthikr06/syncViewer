import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { Accounts } from "./pages/Accounts";
import { Admin } from "./pages/Admin";
import { Alerts } from "./pages/Alerts";
import { Dashboard } from "./pages/Dashboard";
import { Insights } from "./pages/Insights";
import { Login } from "./pages/Login";
import { Recommendations } from "./pages/Recommendations";
import { ResourceDetail } from "./pages/ResourceDetail";
import { Resources } from "./pages/Resources";
import type { Role } from "./lib/types";

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
  );
}
