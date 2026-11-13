import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react';
import {
  addEdge, Background, Controls, MiniMap, ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow,
  type Connection, type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Agents, Tools, Workflows } from '@/api/endpoints';
import { useAuth } from '@/state/auth';
import { useExecutionStream } from '@/components/useExecutionStream';
import { EventTimeline } from '@/components/EventTimeline';
import { Badge, ErrorState, Field, Json, PageHeader, QueryState } from '@/components/ui';
import { JsonInput, useJsonState } from '@/components/common';
import { DEFAULT_CONFIG, emptyDefinition, fromDefinition, nextNodeId, toDefinition, type FlowNode } from '@/features/workflow/serialize';
import { validateDefinition } from '@/features/workflow/validate';
import { NODE_META, nodeTypes } from '@/features/workflow/nodes';
import type { NodeType, ValidationIssue, Workflow } from '@/types/api';

const PALETTE = Object.keys(NODE_META) as NodeType[];
const DND = 'application/agentforge-node';

function ConfigPanel({ node, onChange, onDelete }: { node: FlowNode; onChange: (label: string, config: Record<string, unknown>) => void; onDelete: () => void }) {
  const agents = useQuery({ queryKey: ['agents'], queryFn: () => Agents.list(), enabled: node.type === 'agent' });
  const tools = useQuery({ queryKey: ['tools'], queryFn: () => Tools.list(), enabled: node.type === 'tool' });
  const c = node.data.config;
  const set = (k: string, v: unknown) => onChange(node.data.label, { ...c, [k]: v });
  const text = (k: string, label: string, area = false) => (
    <Field label={label}>{area
      ? <textarea className="input font-mono" rows={3} value={String(c[k] ?? '')} onChange={(e) => set(k, e.target.value)} />
      : <input className="input" value={String(c[k] ?? '')} onChange={(e) => set(k, e.target.value)} />}</Field>
  );
  const num = (k: string, label: string, step = 1) => <Field label={label}><input className="input" type="number" step={step} value={Number(c[k] ?? 0)} onChange={(e) => set(k, Number(e.target.value))} /></Field>;
  const json = (k: string, label: string) => {
    const v = JSON.stringify(c[k] ?? {}, null, 2);
    return <Field label={label}><textarea key={node.id + k} className="input font-mono" rows={3} defaultValue={v} onBlur={(e) => { try { set(k, JSON.parse(e.target.value || '{}')); } catch { /* keep previous */ } }} /></Field>;
  };
  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center justify-between"><h3 className="font-medium">{NODE_META[node.type as NodeType].label} node</h3><span className="font-mono text-xs text-slate-500">{node.id}</span></div>
      <Field label="Label"><input className="input" value={node.data.label} onChange={(e) => onChange(e.target.value, c)} /></Field>
      {node.type === 'agent' && <>
        <Field label="Agent"><select className="input" value={String(c.agent_id ?? '')} onChange={(e) => set('agent_id', e.target.value)}>
          <option value="">Select…</option>{agents.data?.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
        {text('input_template', 'Input template', true)}
      </>}
      {node.type === 'tool' && <>
        <Field label="Tool"><select className="input" value={String(c.tool_id ?? '')} onChange={(e) => set('tool_id', e.target.value)}>
          <option value="">Select…</option>{tools.data?.items.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
        {json('input_mapping', 'Input mapping (JSON)')}
      </>}
      {node.type === 'llm' && <>{text('model', 'Model (optional)')}{text('prompt_template', 'Prompt template', true)}{num('temperature', 'Temperature', 0.1)}</>}
      {node.type === 'rag' && <>{text('query_template', 'Query template', true)}{num('top_k', 'Top K')}</>}
      {node.type === 'api' && <>
        <Field label="Method"><select className="input" value={String(c.method ?? 'GET')} onChange={(e) => set('method', e.target.value)}>{['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => <option key={m}>{m}</option>)}</select></Field>
        {text('url', 'URL')}{json('headers', 'Headers (JSON)')}{text('body_template', 'Body template', true)}{num('timeout_seconds', 'Timeout (s)')}
        {text('credential_id', 'Credential ID (optional)')}
      </>}
      {node.type === 'condition' && text('expression', 'Expression (uses state)', true)}
      {node.type !== 'start' && <button className="btn-danger mt-2" onClick={onDelete}>Delete node</button>}
    </div>
  );
}

function Studio({ wf, onSaved }: { wf: Workflow | null; onSaved: (w: Workflow) => void }) {
  const { can } = useAuth();
  const write = can('resource.write');
  const rf = useReactFlow();
  const initial = useMemo(() => fromDefinition(wf?.definition ?? emptyDefinition()), [wf]);
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initial.edges);
  const [name, setName] = useState(wf?.name ?? 'Untitled workflow');
  const [selId, setSelId] = useState<string | null>(null);
  const [issues, setIssues] = useState<ValidationIssue[] | null>(null);
  const [view, setView] = useState<'canvas' | 'json'>('canvas');
  const [execId, setExecId] = useState<string | null>(null);
  const input = useJsonState({ message: 'hello' });
  const stream = useExecutionStream(execId);
  useEffect(() => { setNodes(initial.nodes); setEdges(initial.edges); setName(wf?.name ?? 'Untitled workflow'); setIssues(null); setExecId(null); }, [initial, wf, setNodes, setEdges]);

  // live node status from SSE node.* events
  useEffect(() => {
    const st: Record<string, 'running' | 'succeeded' | 'failed'> = {};
    for (const e of stream.events) {
      if (!e.node_id) continue;
      if (e.event_type === 'node.started') st[e.node_id] = 'running';
      if (e.event_type === 'node.completed') st[e.node_id] = 'succeeded';
      if (e.event_type === 'node.failed') st[e.node_id] = 'failed';
    }
    setNodes((ns) => ns.map((n) => (n.data.status === st[n.id] ? n : { ...n, data: { ...n.data, status: st[n.id] } })));
  }, [stream.events, setNodes]);

  const definition = () => toDefinition(nodes, edges, rf.getViewport());
  const onConnect = useCallback((c: Connection) => setEdges((es) => addEdge({ ...c, id: `e-${c.source}-${c.sourceHandle ?? 'out'}-${c.target}`, ...(c.sourceHandle ? { label: c.sourceHandle } : {}) }, es)), [setEdges]);
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData(DND) as NodeType;
    if (!type || !write) return;
    const position = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    setNodes((ns) => [...ns, { id: nextNodeId(type, ns), type, position, data: { label: NODE_META[type].label, config: DEFAULT_CONFIG[type]() } }]);
  };
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: () => (wf ? Workflows.update(wf.id, { name, definition: definition() }) : Workflows.create({ name, definition: definition() })),
    onSuccess: (w) => (qc.invalidateQueries({ queryKey: ['workflows'] }), qc.invalidateQueries({ queryKey: ['workflow', w.id] }), onSaved(w)),
  });
  const validate = useMutation({
    mutationFn: async () => {
      const def = definition();
      const local = validateDefinition(def);
      if (!wf) return { valid: local.length === 0, issues: local };
      return Workflows.validate(wf.id, def);
    },
    onSuccess: (r) => setIssues(r.issues),
  });
  const execute = useMutation({ mutationFn: () => Workflows.execute(wf!.id, input.value), onSuccess: (e) => setExecId(e.id) });
  const publish = useMutation({ mutationFn: () => Workflows.publish(wf!.id), onSuccess: (w) => (qc.invalidateQueries({ queryKey: ['workflows'] }), onSaved(w)) });
  const err = save.error ?? validate.error ?? execute.error ?? publish.error;
  const sel = nodes.find((n) => n.id === selId) ?? null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input className="input max-w-xs" aria-label="Workflow name" value={name} onChange={(e) => setName(e.target.value)} disabled={!write} />
        {wf && <><Badge>{wf.status}</Badge><span className="text-xs text-slate-500">v{wf.current_version}</span></>}
        <div className="ml-auto flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => setView(view === 'canvas' ? 'json' : 'canvas')}>{view === 'canvas' ? 'JSON view' : 'Canvas'}</button>
          <button className="btn-ghost" onClick={() => validate.mutate()} disabled={validate.isPending}>Validate</button>
          {write && <button className="btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? 'Saving…' : 'Save'}</button>}
          {write && wf && <button className="btn-ghost" onClick={() => publish.mutate()} disabled={publish.isPending}>Publish</button>}
        </div>
      </div>
      {err && <ErrorState error={err} />}
      {issues && (issues.length === 0
        ? <p className="text-sm text-emerald-600">Workflow is valid.</p>
        : <ul role="alert" className="list-disc rounded-md border border-amber-300 bg-amber-50 p-2 pl-6 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {issues.map((i, k) => <li key={k}><code>{i.code}</code> {i.message}{i.node_id && <button className="ml-1 underline" onClick={() => setSelId(i.node_id)}>select</button>}</li>)}</ul>)}
      <div className="grid gap-3 lg:grid-cols-[140px_1fr_280px]">
        <div className="card !p-2" aria-label="Node palette">
          <div className="label">Drag onto canvas</div>
          {PALETTE.map((t) => (
            <div key={t} draggable={write} onDragStart={(e) => (e.dataTransfer.setData(DND, t), (e.dataTransfer.effectAllowed = 'move'))}
              className={`mb-1 cursor-grab rounded border-l-4 bg-slate-50 px-2 py-1 text-xs dark:bg-slate-800 ${NODE_META[t].color}`}>{NODE_META[t].label}</div>
          ))}
        </div>
        <div className="card h-[520px] !p-0" onDragOver={(e) => (e.preventDefault(), (e.dataTransfer.dropEffect = 'move'))} onDrop={onDrop}>
          {view === 'canvas' ? (
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
              onNodeClick={(_, n) => setSelId(n.id)} onPaneClick={() => setSelId(null)} defaultViewport={initial.viewport} nodesDraggable={write} nodesConnectable={write} fitView>
              <Background /><Controls /><MiniMap pannable zoomable />
            </ReactFlow>
          ) : <pre className="pre !max-h-full h-full">{JSON.stringify(definition(), null, 2)}</pre>}
        </div>
        <div className="card">
          {sel ? <ConfigPanel node={sel}
            onChange={(label, config) => setNodes((ns) => ns.map((n) => (n.id === sel.id ? { ...n, data: { ...n.data, label, config } } : n)))}
            onDelete={() => (setNodes((ns) => ns.filter((n) => n.id !== sel.id)), setEdges((es) => es.filter((e) => e.source !== sel.id && e.target !== sel.id)), setSelId(null))} />
            : <p className="text-sm text-slate-500">Select a node to configure it. Connect condition nodes via the green (true) and red (false) handles.</p>}
        </div>
      </div>
      {wf && can('execution.run') && (
        <div className="card">
          <h2 className="mb-2 font-medium">Execute</h2>
          <JsonInput label="Input (JSON)" value={input.text} onChange={input.setText} rows={3} />
          <button className="btn-primary mt-2" disabled={!input.ok || execute.isPending} onClick={() => execute.mutate()}>Run workflow</button>
          {execId && <div className="mt-3">{stream.error && <ErrorState error={new Error(stream.error)} />}<EventTimeline events={stream.events} />
            {stream.done && <Json value={stream.events.find((e) => e.event_type === 'execution.completed')?.payload ?? {}} />}</div>}
        </div>
      )}
    </div>
  );
}

export default function WorkflowStudio() {
  const list = useQuery({ queryKey: ['workflows'], queryFn: () => Workflows.list() });
  const [selId, setSelId] = useState<string | null>(null);
  const wf = useQuery({ queryKey: ['workflow', selId], queryFn: () => Workflows.get(selId!), enabled: !!selId });
  return (
    <>
      <PageHeader title="Workflow Studio" subtitle="Design multi-step workflows with agents, tools and conditions" />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select className="input max-w-xs" aria-label="Workflow" value={selId ?? ''} onChange={(e) => setSelId(e.target.value || null)}>
          <option value="">+ New workflow</option>
          {list.data?.items.map((w) => <option key={w.id} value={w.id}>{w.name} ({w.status})</option>)}
        </select>
        {list.error && <ErrorState error={list.error} />}
      </div>
      {selId && (wf.isLoading || wf.error)
        ? <QueryState q={wf}>{null}</QueryState>
        : <ReactFlowProvider><Studio key={selId ?? 'new'} wf={selId ? wf.data ?? null : null} onSaved={(w) => setSelId(w.id)} /></ReactFlowProvider>}
    </>
  );
}
