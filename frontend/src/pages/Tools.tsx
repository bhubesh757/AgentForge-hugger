import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Sparkles } from 'lucide-react';
import { Tools } from '@/api/endpoints';
import { useAuth } from '@/state/auth';
import { Badge, Empty, ErrorState, Field, Modal, PageHeader, QueryState } from '@/components/ui';
import { ExecutionPanel, JsonInput, Search, useJsonState } from '@/components/common';
import LazyEditor from '@/components/LazyEditor';
import { fmtDate, tryParseJSON } from '@/lib/format';
import type { Tool, ToolDraft } from '@/types/api';

const STARTER = `def run(input: dict) -> dict:\n    """Entry point called by the sandbox."""\n    return {"echo": input}\n`;
const blank = (): ToolDraft => ({ name: '', description: '', source_code: STARTER, input_schema: { type: 'object' }, output_schema: { type: 'object' }, requirements: [] });

function ToolEditor({ tool, onSaved }: { tool: Tool; onSaved: () => void }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [src, setSrc] = useState(tool.source_code);
  const [reqs, setReqs] = useState(tool.requirements.join('\n'));
  const input = useJsonState({});
  const [execId, setExecId] = useState<string | null>(null);
  useEffect(() => (setSrc(tool.source_code), setReqs(tool.requirements.join('\n')), setExecId(null)), [tool.id, tool.source_code, tool.requirements]);
  const versions = useQuery({ queryKey: ['tool', tool.id, 'versions'], queryFn: () => Tools.versions(tool.id) });
  const done = () => (qc.invalidateQueries({ queryKey: ['tools'] }), qc.invalidateQueries({ queryKey: ['tool', tool.id] }), onSaved());
  const save = useMutation({ mutationFn: () => Tools.update(tool.id, { source_code: src, requirements: reqs.split('\n').map((s) => s.trim()).filter(Boolean) }), onSuccess: done });
  const publish = useMutation({ mutationFn: () => Tools.publish(tool.id), onSuccess: done });
  const test = useMutation({ mutationFn: () => Tools.test(tool.id, input.value ?? {}), onSuccess: (e) => setExecId(e.id) });
  const err = save.error ?? publish.error ?? test.error;
  const write = can('resource.write');
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="font-semibold">{tool.name} <Badge>{tool.status}</Badge> <span className="text-xs text-slate-500">v{tool.current_version}</span></h2><p className="text-sm text-slate-500">{tool.description}</p></div>
        {write && <div className="flex gap-2">
          <button className="btn-ghost" disabled={save.isPending} onClick={() => save.mutate()}>Save version</button>
          {tool.status !== 'published' && <button className="btn-primary" disabled={publish.isPending} onClick={() => publish.mutate()}>Publish</button>}
        </div>}
      </div>
      {err && <ErrorState error={err} />}
      <LazyEditor language="python" height={320} value={src} onChange={setSrc} readOnly={!write} />
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Requirements (one per line)"><textarea className="input font-mono" rows={4} value={reqs} readOnly={!write} onChange={(e) => setReqs(e.target.value)} /></Field>
        <div><span className="label">Input schema</span><pre className="pre !max-h-28">{JSON.stringify(tool.input_schema, null, 2)}</pre></div>
        <div><span className="label">Versions</span>
          <ul className="max-h-28 overflow-auto text-xs">{versions.data?.items.map((v) => <li key={v.id}>v{v.version} · {fmtDate(v.created_at)}</li>)}</ul>
        </div>
      </div>
      {can('execution.run') && (
        <div>
          <JsonInput label="Test input (JSON)" value={input.text} onChange={input.setText} rows={3} />
          <button className="btn-primary mt-2" disabled={!input.ok || test.isPending} onClick={() => test.mutate()}>Run in sandbox</button>
          <ExecutionPanel id={execId} />
        </div>
      )}
    </div>
  );
}

export default function ToolsPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [sel, setSel] = useState<string | null>(null);
  const [mode, setMode] = useState<null | 'create' | 'generate'>(null);
  const [prompt, setPrompt] = useState('');
  const [draft, setDraft] = useState<ToolDraft>(blank);
  const [issues, setIssues] = useState<string[] | null>(null);
  const [schemaText, setSchemaText] = useState('');
  const list = useQuery({ queryKey: ['tools', q], queryFn: () => Tools.list({ q: q || undefined }) });
  const tool = useQuery({ queryKey: ['tool', sel], queryFn: () => Tools.get(sel!), enabled: !!sel });
  const gen = useMutation({ mutationFn: () => Tools.generate(prompt), onSuccess: (r) => (setDraft(r.draft), setSchemaText(JSON.stringify(r.draft.input_schema, null, 2)), setIssues(r.static_analysis.issues)) });
  const create = useMutation({
    mutationFn: () => {
      const s = tryParseJSON(schemaText);
      return Tools.create({ ...draft, requirements: draft.requirements.map((r) => r.trim()).filter(Boolean), input_schema: (s.ok && s.value ? s.value : draft.input_schema) as object });
    },
    onSuccess: (t) => (qc.invalidateQueries({ queryKey: ['tools'] }), setSel(t.id), close()),
  });
  const open = (m: 'create' | 'generate') => (setDraft(blank()), setSchemaText(JSON.stringify(blank().input_schema, null, 2)), setIssues(null), setMode(m));
  function close(): void {
    setMode(null);
    gen.reset();
    create.reset();
  }
  const showForm = mode === 'create' || (mode === 'generate' && issues !== null);
  return (
    <>
      <PageHeader title="Tools" subtitle="Python tools executed in the sandbox"
        actions={can('resource.write') && <>
          <button className="btn-ghost" onClick={() => open('generate')}><Sparkles className="h-4 w-4" />Generate from prompt</button>
          <button className="btn-primary" onClick={() => open('create')}><Plus className="h-4 w-4" />New tool</button>
        </>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card">
          <Search value={q} onChange={setQ} placeholder="Search tools…" />
          <QueryState q={list} empty={list.data?.items.length === 0}>
            <ul className="mt-3 divide-y divide-slate-100 dark:divide-slate-800">
              {list.data?.items.map((t) => (
                <li key={t.id}><button className={`w-full py-2 text-left text-sm ${sel === t.id ? 'text-brand-500' : ''}`} onClick={() => setSel(t.id)}>
                  <span className="font-medium">{t.name}</span> <Badge>{t.status}</Badge><div className="truncate text-xs text-slate-500">{t.description}</div>
                </button></li>
              ))}
            </ul>
          </QueryState>
        </div>
        <div className="card lg:col-span-2">
          {!sel ? <Empty>Select a tool to view or edit its source.</Empty> : <QueryState q={tool}>{tool.data && <ToolEditor tool={tool.data} onSaved={() => undefined} />}</QueryState>}
        </div>
      </div>
      {mode && (
        <Modal title={mode === 'generate' ? 'Generate tool' : 'New tool'} wide onClose={close}>
          {(gen.error || create.error) && <ErrorState error={gen.error ?? create.error} />}
          {mode === 'generate' && issues === null && (
            <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), gen.mutate())}>
              <Field label="Describe the tool"><textarea className="input" rows={3} required value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Create a PostgreSQL query tool" /></Field>
              <button className="btn-primary" disabled={gen.isPending}>{gen.isPending ? 'Generating…' : 'Generate'}</button>
            </form>
          )}
          {showForm && (
            <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), create.mutate())}>
              {issues && (issues.length
                ? <div role="alert" className="rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300"><b>Static analysis issues:</b><ul className="list-disc pl-5">{issues.map((i) => <li key={i}>{i}</li>)}</ul></div>
                : <p className="text-sm text-emerald-600">Static analysis passed.</p>)}
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Name"><input className="input" required pattern="[a-z][a-z0-9_]*" title="snake_case" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
                <Field label="Description"><input className="input" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></Field>
              </div>
              <LazyEditor language="python" height={260} value={draft.source_code} onChange={(v) => setDraft({ ...draft, source_code: v })} />
              <div className="grid gap-3 sm:grid-cols-2">
                <JsonInput label="Input schema" value={schemaText} onChange={setSchemaText} rows={3} />
                <Field label="Requirements (one per line)"><textarea className="input font-mono" rows={3} value={draft.requirements.join('\n')} onChange={(e) => setDraft({ ...draft, requirements: e.target.value.split('\n') })} /></Field>
              </div>
              <button className="btn-primary" disabled={create.isPending || !tryParseJSON(schemaText).ok}>Save tool</button>
            </form>
          )}
        </Modal>
      )}
    </>
  );
}
