import { lazy, Suspense, type ComponentType, type ReactNode } from 'react';
import { BrowserRouter, HashRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider, useAuth } from '@/state/auth';
import Layout from '@/components/Layout';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { Spinner } from '@/components/ui';
import Login from '@/pages/Login';
import Dashboard from '@/pages/Dashboard';
import { BASE_PATH, ROUTER_MODE } from '@/config';

const named = <M extends Record<string, unknown>>(f: () => Promise<M>, k: keyof M) =>
  lazy(() => f().then((m) => ({ default: m[k] as ComponentType })));
const Agents = named(() => import('@/pages/Agents'), 'AgentsPage');
const AgentDetail = named(() => import('@/pages/Agents'), 'AgentDetail');
const Tools = lazy(() => import('@/pages/Tools'));
const Workflows = lazy(() => import('@/pages/WorkflowStudio'));
const Chat = lazy(() => import('@/pages/Chat'));
const Playground = lazy(() => import('@/pages/Playground'));
const Executions = named(() => import('@/pages/Executions'), 'ExecutionsPage');
const ExecutionDetail = named(() => import('@/pages/Executions'), 'ExecutionDetail');
const Logs = named(() => import('@/pages/Executions'), 'LogsPage');
const Monitoring = named(() => import('@/pages/Ops'), 'Monitoring');
const Guardrails = named(() => import('@/pages/Ops'), 'Guardrails');
const Deployments = named(() => import('@/pages/Ops'), 'DeploymentsPage');
const Cli = named(() => import('@/pages/Ops'), 'Cli');
const Credentials = named(() => import('@/pages/Admin'), 'CredentialsPage');
const Providers = named(() => import('@/pages/Admin'), 'ProvidersPage');
const Organizations = named(() => import('@/pages/Admin'), 'OrganizationsPage');
const Users = named(() => import('@/pages/Admin'), 'UsersPage');
const Settings = named(() => import('@/pages/Admin'), 'SettingsPage');

export const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 10_000 } } });

function Protected({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Spinner label="Restoring session…" />;
  if (!me) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

function NotFound() {
  return <div className="card"><h1 className="text-lg font-semibold">404 — Page not found</h1><p className="text-sm text-slate-500">The page you requested does not exist.</p></div>;
}

export function AppRoutes() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login" element={<Login mode="login" />} />
        <Route path="/register" element={<Login mode="register" />} />
        <Route element={<Protected><Layout /></Protected>}>
          <Route index element={<Dashboard />} />
          <Route path="agents" element={<Agents />} />
          <Route path="agents/:id" element={<AgentDetail />} />
          <Route path="tools" element={<Tools />} />
          <Route path="workflows" element={<Workflows />} />
          <Route path="chat" element={<Chat />} />
          <Route path="playground" element={<Playground />} />
          <Route path="cli" element={<Cli />} />
          <Route path="executions" element={<Executions />} />
          <Route path="executions/:id" element={<ExecutionDetail />} />
          <Route path="monitoring" element={<Monitoring />} />
          <Route path="logs" element={<Logs />} />
          <Route path="guardrails" element={<Guardrails />} />
          <Route path="credentials" element={<Credentials />} />
          <Route path="deployments" element={<Deployments />} />
          <Route path="organizations" element={<Organizations />} />
          <Route path="users" element={<Users />} />
          <Route path="providers" element={<Providers />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function App() {
  const Router = ROUTER_MODE === 'hash' ? HashRouter : BrowserRouter;
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }} {...(ROUTER_MODE === 'browser' ? { basename: BASE_PATH.replace(/\/$/, '') || '/' } : {})}>
          <AuthProvider>
            <ErrorBoundary><AppRoutes /></ErrorBoundary>
          </AuthProvider>
        </Router>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
