import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Executions } from '@/api/endpoints';
import { useAuth } from '@/state/auth';
import { EventTimeline } from '@/components/EventTimeline';
import { useExecutionStream } from '@/components/useExecutionStream';
import { Badge, ErrorState, Json, PageHeader, QueryState } from '@/components/ui';
import { fmtDate, fmtMs } from '@/lib/format';
import type { ExecKind, ExecStatus, Execution } from '@/types/api';

const KINDS: ExecKind[] = ['agent', 'agent_test', 'workflow', 'tool_test', 'chat'];
const STATUSES: ExecStatus[] = ['queued', 'running', 'succeeded', 'failed', 'cancelled'];
const live = (e?: Execution) => !!e && (e.status === 'queued' || e.status === 'running');

function ExecTable({ items }: { items: Execution[] }) {
  return (
    <table className="table"><thead><tr><th>ID</th><th>Kind</th><th>Status</th><th>Duration</th><th>Created</th></tr></thead><tbody>
      {items.map((e) => (
        <tr key={e.id}><td><Link className="font-mono text-brand-500" to={`/executions/${e.id}`}>{e.id.slice(0, 8)}</Link></td><td>{e.kind}</td>
          <td><Badge>{e.status}</Badge></td><td>{fmtMs(e.duration_ms)}</td><td>{fmtDate(e.created_at)}</td></tr>
      ))}
    </tbody></table>
  );
}

export function ExecutionsPage() {
  const [kind, setKind] = useState('');
  const [status, setStatus] = useState('');
  const list = useQuery({ queryKey: ['executions', kind, status], queryFn: () => Executions.list({ kind: kind || undefined, status: status || undefined }), refetchInterval: 5000 });
  return (
    <>
      <PageHeader title="Executions" subtitle="History of agent, tool, workflow and chat runs" />
      <div className="mb-3 flex gap-2">
        <select className="input max-w-[12rem]" aria-label="Kind filter" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All kinds</option>{KINDS.map((k) => <option key={k}>{k}</option>)}</select>
        <select className="input max-w-[12rem]" aria-label="Status filter" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{STATUSES.map((k) => <option key={k}>{k}</option>)}</select>
      </div>
      <div className="card"><QueryState q={list} empty={list.data?.items.length === 0}><ExecTable items={list.data?.items ?? []} /></QueryState></div>
    </>
  );
}

function Logs({ id }: { id: string }) {
  const logs = useQuery({ queryKey: ['execution', id, 'logs'], queryFn: () => Executions.logs(id) });
  return (
    <QueryState q={logs} empty={logs.data?.items.length === 0}>
      <pre className="pre">{logs.data?.items.map((l) => `${l.timestamp} ${l.level.toUpperCase().padEnd(7)} ${l.node_id ? `[${l.node_id}] ` : ''}${l.message}`).join('\n')}</pre>
    </QueryState>
  );
}

export function ExecutionDetail() {
  const { id = '' } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const ex = useQuery({ queryKey: ['execution', id], queryFn: () => Executions.get(id), refetchInterval: (q) => (live(q.state.data) ? 2000 : false) });
  const stream = useExecutionStream(id);
  const cancel = useMutation({ mutationFn: () => Executions.cancel(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['execution', id] }) });
  const e = ex.data;
  return (
    <QueryState q={ex}>
      {e && <>
        <PageHeader title={`Execution ${e.id.slice(0, 8)}`} subtitle={`${e.kind} · correlation ${e.correlation_id}`}
          actions={<><Badge>{e.status}</Badge>{live(e) && can('execution.run') && <button className="btn-danger" disabled={cancel.isPending} onClick={() => cancel.mutate()}>Cancel</button>}</>} />
        {cancel.error && <ErrorState error={cancel.error} />}
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="card space-y-2 text-sm">
            <div>Started: {fmtDate(e.started_at)} · Finished: {fmtDate(e.finished_at)} · Duration: {fmtMs(e.duration_ms)}</div>
            <div className="label">Input</div><Json value={e.input} />
            <div className="label">Output</div><Json value={e.output} />
            {e.error && <ErrorState error={new Error(e.error)} />}
          </div>
          <div className="card"><h2 className="mb-2 font-medium">Events</h2>{stream.error && <ErrorState error={new Error(stream.error)} />}<EventTimeline events={stream.events} /></div>
        </div>
        <div className="card mt-4"><h2 className="mb-2 font-medium">Logs</h2><Logs id={e.id} /></div>
      </>}
    </QueryState>
  );
}

export function LogsPage() {
  const list = useQuery({ queryKey: ['executions', 'logs'], queryFn: () => Executions.list({ page_size: 50 }) });
  const [sel, setSel] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Logs" subtitle="Structured execution logs" />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card">
          <QueryState q={list} empty={list.data?.items.length === 0}>
            <ul className="space-y-1 text-sm">{list.data?.items.map((e) => (
              <li key={e.id}><button className={`w-full rounded px-2 py-1 text-left hover:bg-slate-100 dark:hover:bg-slate-800 ${sel === e.id ? 'bg-slate-100 dark:bg-slate-800' : ''}`} onClick={() => setSel(e.id)}>
                <span className="font-mono">{e.id.slice(0, 8)}</span> {e.kind} <Badge>{e.status}</Badge><div className="text-xs text-slate-500">{fmtDate(e.created_at)}</div></button></li>
            ))}</ul>
          </QueryState>
        </div>
        <div className="card lg:col-span-2">{sel ? <Logs id={sel} /> : <p className="text-sm text-slate-500">Select an execution to view its logs.</p>}</div>
      </div>
    </>
  );
}
