import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Bot, GitBranch, Server, Wrench } from 'lucide-react';
import { Executions, Monitoring } from '@/api/endpoints';
import { Badge, PageHeader, QueryState } from '@/components/ui';
import { fmtDate, fmtMs } from '@/lib/format';

export function Stat({ label, value }: { label: string; value: string | number }) {
  return <div className="card"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold">{value}</div></div>;
}

export default function Dashboard() {
  const sum = useQuery({ queryKey: ['summary'], queryFn: Monitoring.summary });
  const recent = useQuery({ queryKey: ['executions', 'recent'], queryFn: () => Executions.list({ page_size: 8 }) });
  const s = sum.data;
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Overview of the last 24 hours" />
      <QueryState q={sum}>
        {s && (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Executions (24h)" value={s.executions_24h} />
            <Stat label="Succeeded" value={s.succeeded_24h} />
            <Stat label="Failed" value={s.failed_24h} />
            <Stat label="Avg duration" value={fmtMs(s.avg_duration_ms)} />
            <Stat label="Agents" value={s.agents} />
            <Stat label="Tools" value={s.tools} />
            <Stat label="Workflows" value={s.workflows} />
            <div className="card">
              <div className="text-xs text-slate-500">Active LLM provider</div>
              {s.active_provider ? <div className="mt-1 text-sm">{s.active_provider.name} <Badge>{s.active_provider.status}</Badge><div className="text-xs text-slate-500">{s.active_provider.default_model}</div></div>
                : <Link className="mt-1 block text-sm text-brand-500" to="/providers">Connect a provider →</Link>}
            </div>
          </div>
        )}
      </QueryState>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <h2 className="mb-2 font-medium">Recent executions</h2>
          <QueryState q={recent} empty={recent.data?.items.length === 0}>
            <table className="table"><thead><tr><th>Kind</th><th>Status</th><th>Duration</th><th>Created</th></tr></thead><tbody>
              {recent.data?.items.map((e) => <tr key={e.id}><td><Link className="text-brand-500" to={`/executions/${e.id}`}>{e.kind}</Link></td><td><Badge>{e.status}</Badge></td><td>{fmtMs(e.duration_ms)}</td><td>{fmtDate(e.created_at)}</td></tr>)}
            </tbody></table>
          </QueryState>
        </div>
        <div className="card">
          <h2 className="mb-2 font-medium">Quick actions</h2>
          <div className="grid gap-2">
            <Link className="btn-ghost" to="/agents"><Bot className="h-4 w-4" />Create an agent</Link>
            <Link className="btn-ghost" to="/tools"><Wrench className="h-4 w-4" />Generate a tool</Link>
            <Link className="btn-ghost" to="/workflows"><GitBranch className="h-4 w-4" />Design a workflow</Link>
            <Link className="btn-ghost" to="/providers"><Server className="h-4 w-4" />Manage LLM providers</Link>
          </div>
        </div>
      </div>
    </>
  );
}
