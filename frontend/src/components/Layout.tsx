import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  Activity, Bot, Building2, ChartLine, FileText, GitBranch, KeyRound, LayoutDashboard, LogOut, Menu, MessageSquare,
  Rocket, Send, Server, Settings, Shield, Terminal, Users, Wrench,
} from 'lucide-react';
import { useAuth } from '@/state/auth';
import { API_VERSION, DEMO_MODE, UI_VERSION } from '@/config';

export const NAV = [
  { group: 'WORKSPACE', items: [
    ['/', 'Dashboard', LayoutDashboard], ['/agents', 'Agents', Bot], ['/tools', 'Tools Factory', Wrench], ['/workflows', 'Workflow Studio', GitBranch],
    ['/chat', 'AI Chat', MessageSquare], ['/playground', 'API Playground', Send], ['/cli', 'CLI', Terminal]] },
  { group: 'OPERATIONS', items: [
    ['/executions', 'Executions', Activity], ['/monitoring', 'Monitoring', ChartLine], ['/logs', 'Logs', FileText], ['/guardrails', 'Guardrails', Shield],
    ['/credentials', 'Credentials', KeyRound], ['/deployments', 'Deployments', Rocket]] },
  { group: 'SETTINGS', items: [
    ['/organizations', 'Organizations', Building2], ['/users', 'Users & Roles', Users], ['/providers', 'LLM Providers', Server], ['/settings', 'Settings', Settings]] },
] as const;

export function DemoBanner() {
  if (!DEMO_MODE) return null;
  return (
    <div role="status" className="sticky top-0 z-40 bg-amber-400 px-4 py-1 text-center text-xs font-semibold text-amber-950">
      Demo mode — no backend connected. Data is simulated in your browser; no LLM calls are made.
    </div>
  );
}

export default function Layout() {
  const { me, org, logout, selectOrg } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen flex-col">
      <DemoBanner />
      <div className="flex flex-1">
        <aside className={`${open ? 'flex' : 'hidden'} fixed inset-y-0 left-0 z-30 w-60 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 md:static md:flex`}>
          <div className="flex items-center gap-2 px-4 py-4 font-semibold">
            <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" className="h-6 w-6" /> AgentForge AI
          </div>
          <nav className="flex-1 overflow-y-auto px-2" aria-label="Main">
            {NAV.map((g) => (
              <div key={g.group} className="mb-3">
                <div className="px-2 pb-1 text-[10px] font-semibold tracking-widest text-slate-400">{g.group}</div>
                {g.items.map(([to, label, Icon]) => (
                  <NavLink key={to} to={to} end={to === '/'} onClick={() => setOpen(false)}
                    className={({ isActive }) => `flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${isActive ? 'bg-brand-600/15 font-medium text-brand-600 dark:text-brand-400' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
                    <Icon className="h-4 w-4" />{label}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="border-t border-slate-200 px-4 py-3 text-xs text-slate-500 dark:border-slate-800">UI {UI_VERSION} · API {API_VERSION}{DEMO_MODE && ' · demo'}</div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2 dark:border-slate-800 dark:bg-slate-900">
            <button className="btn-ghost !p-1.5 md:hidden" aria-label="Toggle navigation" onClick={() => setOpen(!open)}><Menu className="h-4 w-4" /></button>
            <label className="flex items-center gap-2 text-sm">
              <span className="sr-only">Organization</span>
              <Building2 className="h-4 w-4 text-slate-400" />
              <select className="input !w-auto !py-1" value={org?.organization_id ?? ''} onChange={(e) => selectOrg(e.target.value)} aria-label="Select organization">
                {!me?.memberships.length && <option value="">No organization</option>}
                {me?.memberships.map((m) => <option key={m.organization_id} value={m.organization_id}>{m.organization_name} ({m.role})</option>)}
              </select>
            </label>
            <div className="ml-auto flex items-center gap-3 text-sm">
              <span className="hidden text-slate-500 sm:inline">{me?.email}</span>
              <button className="btn-ghost !py-1" onClick={() => void logout()}><LogOut className="h-4 w-4" />Logout</button>
            </div>
          </header>
          <main className="min-w-0 flex-1 p-4 md:p-6">
            {!org && <div className="card mb-4 text-sm">You are not a member of any organization yet. Create one under <NavLink className="text-brand-500 underline" to="/organizations">Organizations</NavLink>.</div>}
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}
