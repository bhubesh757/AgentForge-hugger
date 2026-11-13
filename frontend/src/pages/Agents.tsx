import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Sparkles } from 'lucide-react';
import { Agents, Providers, Tools } from '@/api/endpoints';
import { useAuth } from '@/state/auth';
import { Badge, ErrorState, Field, Modal, PageHeader, QueryState } from '@/components/ui';
import { ExecutionPanel, JsonInput, Search, useJsonState } from '@/components/common';
import { fmtDate } from '@/lib/format';
import type { AgentConfig, AgentDraft, AgentStatus } from '@/types/api';

const STATUSES: AgentStatus[] = ['draft', 'configured', 'testing', 'approved', 'published', 'archived'];
export const blankConfig = (): AgentConfig => ({
  instructions: '', provider_id: null, model: null, temperature: 0.2, tool_ids: [], memory: 'none', max_retries: 1, timeout_seconds: 60,
  guardrails: { block_pii: false, max_output_chars: null }, input_schema: null, output_schema: null,
});

/** Editable form for name/description/AgentConfig. */
function AgentForm({ initial, onSubmit, busy, submitLabel }: { initial: AgentDraft; onSubmit: (d: AgentDraft) => void; busy?: boolean; submitLabel: string }) {
  const [d, setD] = useState<AgentDraft>(initial);
  const providers = useQuery({ queryKey: ['providers'], queryFn: Providers.list });
  const tools = useQuery({ queryKey: ['tools'], queryFn: () => Tools.list() });
  const c = d.config;
  const set = (p: Partial<AgentConfig>) => setD({ ...d, config: { ...c, ...p } });
  const ins = useJsonState(c.input_schema);
  const outs = useJsonState(c.output_schema);
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); onSubmit({ ...d, config: { ...c, input_schema: (ins.value as object) ?? null, output_schema: (outs.value as object) ?? null } }); }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name"><input className="input" required value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></Field>
        <Field label="Description"><input className="input" value={d.description} onChange={(e) => setD({ ...d, description: e.target.value })} /></Field>
      </div>
      <Field label="Instructions"><textarea className="input" rows={5} required value={c.instructions} onChange={(e) => set({ instructions: e.target.value })} /></Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Provider">
          <select className="input" value={c.provider_id ?? ''} onChange={(e) => set({ provider_id: e.target.value || null })}>
            <option value="">Org default</option>
            {providers.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.provider})</option>)}
          </select>
        </Field>
        <Field label="Model"><input className="input" placeholder="provider default" value={c.model ?? ''} onChange={(e) => set({ model: e.target.value || null })} /></Field>
        <Field label={`Temperature (${c.temperature})`}><input className="w-full" type="range" min={0} max={2} step={0.1} value={c.temperature} onChange={(e) => set({ temperature: Number(e.target.value) })} /></Field>
        <Field label="Memory">
          <select className="input" value={c.memory} onChange={(e) => set({ memory: e.target.value as AgentConfig['memory'] })}><option value="none">none</option><option value="conversation">conversation</option></select>
        </Field>
        <Field label="Max retries"><input className="input" type="number" min={0} max={5} value={c.max_retries} onChange={(e) => set({ max_retries: Number(e.target.value) })} /></Field>
        <Field label="Timeout (s)"><input className="input" type="number" min={1} max={600} value={c.timeout_seconds} onChange={(e) => set({ timeout_seconds: Number(e.target.value) })} /></Field>
      </div>
      <Field label="Tools">
        <div className="flex flex-wrap gap-3 text-sm">
          {tools.data?.items.length ? tools.data.items.map((t) => (
            <label key={t.id} className="flex items-center gap-1">
              <input type="checkbox" checked={c.tool_ids.includes(t.id)} onChange={(e) => set({ tool_ids: e.target.checked ? [...c.tool_ids, t.id] : c.tool_ids.filter((x) => x !== t.id) })} />{t.name}
            </label>
          )) : <span className="text-slate-500">No tools yet</span>}
        </div>
      </Field>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-1"><input type="checkbox" checked={c.guardrails.block_pii} onChange={(e) => set({ guardrails: { ...c.guardrails, block_pii: e.target.checked } })} />Block PII</label>
        <label className="flex items-center gap-2">Max output chars
          <input className="input w-28" type="number" min={1} value={c.guardrails.max_output_chars ?? ''} onChange={(e) => set({ guardrails: { ...c.guardrails, max_output_chars: e.target.value ? Number(e.target.value) : null } })} />
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <JsonInput label="Input schema (JSON, optional)" value={ins.text} onChange={ins.setText} />
        <JsonInput label="Output schema (JSON, optional)" value={outs.text} onChange={outs.setText} />
      </div>
      <button className="btn-primary" disabled={busy || !ins.ok || !outs.ok}>{busy ? 'Saving…' : submitLabel}</button>
    </form>
  );
}

export function AgentsPage() {
  const { can } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [mode, setMode] = useState<null | 'create' | 'generate'>(null);
  const [prompt, setPrompt] = useState('');
  const [draft, setDraft] = useState<AgentDraft | null>(null);
  const list = useQuery({ queryKey: ['agents', q, status], queryFn: () => Agents.list({ q: q || undefined, status: status || undefined }) });
  const create = useMutation({ mutationFn: (d: AgentDraft) => Agents.create(d), onSuccess: (a) => (qc.invalidateQueries({ queryKey: ['agents'] }), nav(`/agents/${a.id}`)) });
  const gen = useMutation({ mutationFn: () => Agents.generate(prompt), onSuccess: (r) => setDraft(r.draft) });
  const close = () => (setMode(null), setDraft(null), create.reset(), gen.reset());
  return (
    <>
      <PageHeader title="Agents" subtitle="Create, version, test and publish AI agents"
        actions={can('resource.write') && <>
          <button className="btn-ghost" onClick={() => setMode('generate')}><Sparkles className="h-4 w-4" />Generate with AI</button>
          <button className="btn-primary" onClick={() => setMode('create')}><Plus className="h-4 w-4" />New agent</button>
        </>} />
      <div className="mb-3 flex flex-wrap gap-2">
        <Search value={q} onChange={setQ} placeholder="Search agents…" />
        <select className="input max-w-[12rem]" aria-label="Status filter" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <div className="card">
        <QueryState q={list} empty={list.data?.items.length === 0}>
          <table className="table"><thead><tr><th>Name</th><th>Status</th><th>Version</th><th>Updated</th></tr></thead><tbody>
            {list.data?.items.map((a) => (
              <tr key={a.id}><td><Link className="font-medium text-brand-500" to={`/agents/${a.id}`}>{a.name}</Link><div className="text-xs text-slate-500">{a.description}</div></td>
                <td><Badge>{a.status}</Badge></td><td>v{a.current_version}</td><td>{fmtDate(a.updated_at)}</td></tr>
            ))}
          </tbody></table>
        </QueryState>
      </div>
      {mode === 'create' && (
        <Modal title="New agent" wide onClose={close}>
          {create.error && <ErrorState error={create.error} />}
          <AgentForm initial={{ name: '', description: '', config: blankConfig() }} busy={create.isPending} submitLabel="Create agent" onSubmit={(d) => create.mutate(d)} />
        </Modal>
      )}
      {mode === 'generate' && (
        <Modal title="Generate agent with AI" wide onClose={close}>
          {(gen.error || create.error) && <ErrorState error={gen.error ?? create.error} />}
          {!draft ? (
            <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), gen.mutate())}>
              <Field label="Describe the agent"><textarea className="input" rows={4} required value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Create a Kubernetes monitoring agent" /></Field>
              <button className="btn-primary" disabled={gen.isPending}><Sparkles className="h-4 w-4" />{gen.isPending ? 'Generating…' : 'Generate draft'}</button>
            </form>
          ) : (
            <>
              <p className="mb-3 text-sm text-slate-500">Review the generated draft, edit anything, then save.</p>
              <AgentForm initial={draft} busy={create.isPending} submitLabel="Save agent" onSubmit={(d) => create.mutate(d)} />
            </>
          )}
        </Modal>
      )}
    </>
  );
}

export function AgentDetail() {
  const { id = '' } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const agent = useQuery({ queryKey: ['agent', id], queryFn: () => Agents.get(id) });
  const versions = useQuery({ queryKey: ['agent', id, 'versions'], queryFn: () => Agents.versions(id) });
  const [editing, setEditing] = useState(false);
  const input = useJsonState({ message: 'Hello!' });
  const [execId, setExecId] = useState<string | null>(null);
  const refresh = () => (qc.invalidateQueries({ queryKey: ['agent', id] }), qc.invalidateQueries({ queryKey: ['agents'] }));
  const update = useMutation({ mutationFn: (d: AgentDraft) => Agents.update(id, d), onSuccess: () => (refresh(), setEditing(false)) });
  const publish = useMutation({ mutationFn: () => Agents.publish(id), onSuccess: refresh });
  const rollback = useMutation({ mutationFn: (v: number) => Agents.rollback(id, v), onSuccess: refresh });
  const test = useMutation({ mutationFn: () => Agents.test(id, input.value), onSuccess: (e) => setExecId(e.id) });
  const err = update.error ?? publish.error ?? rollback.error ?? test.error;
  const a = agent.data;
  return (
    <QueryState q={agent}>
      {a && <>
        <PageHeader title={a.name} subtitle={a.description}
          actions={<>
            <Badge>{a.status}</Badge>
            {can('resource.write') && <button className="btn-ghost" onClick={() => setEditing(true)}>Edit</button>}
            {can('resource.write') && a.status !== 'published' && <button className="btn-primary" disabled={publish.isPending} onClick={() => publish.mutate()}>Publish</button>}
          </>} />
        {err && <div className="mb-3"><ErrorState error={err} /></div>}
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="card lg:col-span-2">
            <h2 className="mb-2 font-medium">Configuration (v{a.current_version})</h2>
            <p className="mb-2 whitespace-pre-wrap text-sm">{a.config.instructions}</p>
            <pre className="pre">{JSON.stringify(a.config, null, 2)}</pre>
          </div>
          <div className="card">
            <h2 className="mb-2 font-medium">Versions</h2>
            <QueryState q={versions} empty={versions.data?.items.length === 0}>
              <ul className="space-y-1 text-sm">
                {versions.data?.items.map((v) => (
                  <li key={v.id} className="flex items-center justify-between gap-2">
                    <span>v{v.version} <span className="text-xs text-slate-500">{fmtDate(v.created_at)}</span></span>
                    {can('resource.write') && v.version !== a.current_version && <button className="btn-ghost !px-2 !py-0.5 text-xs" disabled={rollback.isPending} onClick={() => rollback.mutate(v.version)}>Rollback</button>}
                  </li>
                ))}
              </ul>
            </QueryState>
          </div>
        </div>
        {can('execution.run') && (
          <div className="card mt-4">
            <h2 className="mb-2 font-medium">Test agent</h2>
            <JsonInput label="Input (JSON)" value={input.text} onChange={input.setText} />
            <button className="btn-primary mt-2" disabled={!input.ok || test.isPending} onClick={() => test.mutate()}>Run test</button>
            <ExecutionPanel id={execId} />
          </div>
        )}
        {editing && (
          <Modal title={`Edit ${a.name}`} wide onClose={() => setEditing(false)}>
            <AgentForm initial={{ name: a.name, description: a.description, config: a.config }} busy={update.isPending} submitLabel="Save new version" onSubmit={(d) => update.mutate(d)} />
          </Modal>
        )}
      </>}
    </QueryState>
  );
}
