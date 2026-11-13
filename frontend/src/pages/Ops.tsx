import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Agents, Deployments, Monitoring as MonitoringApi, Workflows } from '@/api/endpoints';
import { useAuth } from '@/state/auth';
import { Badge, CopyButton, ErrorState, Field, PageHeader, QueryState } from '@/components/ui';
import { Stat } from './Dashboard';
import { fmtDate, fmtMs } from '@/lib/format';
import { API_BASE_URL } from '@/config';
import type { Agent, Deployment } from '@/types/api';

const BAR_COLORS: Record<string, string> = { succeeded: '#10b981', failed: '#f43f5e', running: '#0ea5e9', queued: '#f59e0b', cancelled: '#94a3b8' };

/** Lightweight horizontal bar chart in plain SVG. */
export function BarChart({ data, title }: { data: Record<string, number>; title: string }) {
  const rows = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map((r) => r[1]));
  const h = 24;
  return (
    <figure className="card">
      <figcaption className="mb-2 font-medium">{title}</figcaption>
      {rows.length === 0 ? <p className="text-sm text-slate-500">No data in the last 24h.</p> : (
        <svg role="img" aria-label={title} viewBox={`0 0 300 ${rows.length * h}`} className="w-full" style={{ maxHeight: rows.length * h * 1.4 }}>
          {rows.map(([k, v], i) => (
            <g key={k} transform={`translate(0 ${i * h})`}>
              <text x={0} y={15} className="fill-slate-500 text-[10px]">{k}</text>
              <rect x={80} y={4} height={14} rx={3} width={(v / max) * 190} fill={BAR_COLORS[k] ?? '#6366f1'} />
              <text x={84 + (v / max) * 190} y={15} className="fill-current text-[10px]">{v}</text>
            </g>
          ))}
        </svg>
      )}
    </figure>
  );
}

export function Monitoring() {
  const s = useQuery({ queryKey: ['summary'], queryFn: MonitoringApi.summary, refetchInterval: 10_000 });
  const d = s.data;
  const rate = d && d.executions_24h ? `${Math.round((d.succeeded_24h / d.executions_24h) * 100)}%` : '—';
  return (
    <>
      <PageHeader title="Monitoring" subtitle="Execution health over the last 24 hours (auto-refreshes)" />
      <QueryState q={s}>
        {d && <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Executions (24h)" value={d.executions_24h} /><Stat label="Success rate" value={rate} />
            <Stat label="Failed" value={d.failed_24h} /><Stat label="Avg duration" value={fmtMs(d.avg_duration_ms)} />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2"><BarChart title="By status" data={d.by_status} /><BarChart title="By kind" data={d.by_kind} /></div>
          <p className="mt-4 text-sm text-slate-500">Prometheus metrics are exposed by the backend at <code>/metrics</code>; Grafana dashboards ship with the monitoring compose profile.</p>
        </>}
      </QueryState>
    </>
  );
}

function GuardrailRow({ a, write }: { a: Agent; write: boolean }) {
  const qc = useQueryClient();
  const [g, setG] = useState(a.config.guardrails);
  const save = useMutation({ mutationFn: () => Agents.update(a.id, { config: { ...a.config, guardrails: g } }), onSuccess: () => qc.invalidateQueries({ queryKey: ['agents'] }) });
  const dirty = JSON.stringify(g) !== JSON.stringify(a.config.guardrails);
  return (
    <tr>
      <td><Link className="text-brand-500" to={`/agents/${a.id}`}>{a.name}</Link></td>
      <td><input type="checkbox" aria-label={`Block PII for ${a.name}`} disabled={!write} checked={g.block_pii} onChange={(e) => setG({ ...g, block_pii: e.target.checked })} /></td>
      <td><input className="input w-28" type="number" min={1} aria-label={`Max output chars for ${a.name}`} disabled={!write} value={g.max_output_chars ?? ''} onChange={(e) => setG({ ...g, max_output_chars: e.target.value ? Number(e.target.value) : null })} /></td>
      <td>{a.config.max_retries} / {a.config.timeout_seconds}s</td>
      <td>{write && dirty && <button className="btn-primary !py-0.5 text-xs" disabled={save.isPending} onClick={() => save.mutate()}>Save</button>}{save.error && <ErrorState error={save.error} />}</td>
    </tr>
  );
}

export function Guardrails() {
  const { can } = useAuth();
  const agents = useQuery({ queryKey: ['agents'], queryFn: () => Agents.list() });
  return (
    <>
      <PageHeader title="Guardrails" subtitle="Per-agent output safety policies (PII blocking, output length, retries, timeouts)" />
      <div className="card"><QueryState q={agents} empty={agents.data?.items.length === 0}>
        <table className="table"><thead><tr><th>Agent</th><th>Block PII</th><th>Max output chars</th><th>Retries / timeout</th><th /></tr></thead>
          <tbody>{agents.data?.items.map((a) => <GuardrailRow key={a.id + a.updated_at} a={a} write={can('resource.write')} />)}</tbody></table>
      </QueryState></div>
    </>
  );
}

export function DeploymentsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['deployments'], queryFn: Deployments.list });
  const agents = useQuery({ queryKey: ['agents'], queryFn: () => Agents.list() });
  const wfs = useQuery({ queryKey: ['workflows'], queryFn: () => Workflows.list() });
  const [f, setF] = useState<Pick<Deployment, 'resource_type' | 'resource_id' | 'environment'>>({ resource_type: 'agent', resource_id: '', environment: 'dev' });
  const create = useMutation({ mutationFn: () => Deployments.create(f), onSuccess: () => qc.invalidateQueries({ queryKey: ['deployments'] }) });
  const names = new Map([...(agents.data?.items ?? []), ...(wfs.data?.items ?? [])].map((x) => [x.id, x.name]));
  const opts = f.resource_type === 'agent' ? agents.data?.items : wfs.data?.items;
  return (
    <>
      <PageHeader title="Deployments" subtitle="Promote published agents and workflows to environments" />
      {can('resource.write') && (
        <form className="card mb-4 grid gap-3 sm:grid-cols-4" onSubmit={(e) => (e.preventDefault(), create.mutate())}>
          <Field label="Type"><select className="input" value={f.resource_type} onChange={(e) => setF({ ...f, resource_type: e.target.value as 'agent' | 'workflow', resource_id: '' })}><option>agent</option><option>workflow</option></select></Field>
          <Field label="Resource"><select className="input" required value={f.resource_id} onChange={(e) => setF({ ...f, resource_id: e.target.value })}><option value="">Select…</option>{opts?.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
          <Field label="Environment"><select className="input" value={f.environment} onChange={(e) => setF({ ...f, environment: e.target.value as Deployment['environment'] })}><option>dev</option><option>staging</option><option>production</option></select></Field>
          <div className="flex items-end"><button className="btn-primary" disabled={create.isPending}>Deploy</button></div>
          {create.error && <div className="sm:col-span-4"><ErrorState error={create.error} /></div>}
        </form>
      )}
      <div className="card"><QueryState q={list} empty={list.data?.items.length === 0}>
        <table className="table"><thead><tr><th>Resource</th><th>Type</th><th>Environment</th><th>Status</th><th>Created</th></tr></thead><tbody>
          {list.data?.items.map((d) => <tr key={d.id}><td>{names.get(d.resource_id) ?? d.resource_id.slice(0, 8)}</td><td>{d.resource_type}</td><td><Badge>{d.environment}</Badge></td><td>{d.status ?? 'active'}</td><td>{fmtDate(d.created_at)}</td></tr>)}
        </tbody></table>
      </QueryState></div>
    </>
  );
}

const CLI: [string, string][] = [
  ['Configure the API endpoint', `export AGENTFORGE_API_URL=${API_BASE_URL}`],
  ['Log in', 'agentforge login --email you@example.com'],
  ['Initialize a project', 'agentforge init my-project'],
  ['Create an agent', 'agentforge agent create incident-agent'],
  ['Generate an agent with GenAI', 'agentforge agent generate --prompt "Create a Kubernetes monitoring agent"'],
  ['Generate a tool', 'agentforge tool generate --prompt "Create a PostgreSQL query tool"'],
  ['List agents', 'agentforge agent list'],
  ['Test an agent', 'agentforge agent test incident-agent'],
  ['List workflows', 'agentforge workflow list'],
  ['Execute a workflow', 'agentforge workflow run incident-workflow'],
  ['Check logs', 'agentforge logs incident-agent'],
  ['Deploy', 'agentforge deploy incident-agent --env staging'],
  ['Check deployment status', 'agentforge status'],
];

export function Cli() {
  return (
    <>
      <PageHeader title="CLI" subtitle="The Typer-based agentforge CLI talks to the same authenticated API" />
      <div className="space-y-3">
        {CLI.map(([t, c]) => (
          <div key={t} className="card !p-3">
            <div className="mb-1 flex items-center justify-between"><span className="text-sm font-medium">{t}</span><CopyButton text={c} /></div>
            <pre className="pre">{c}</pre>
          </div>
        ))}
      </div>
    </>
  );
}
