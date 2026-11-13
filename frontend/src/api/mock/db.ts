import { storage } from '@/lib/storage';
import { uuid } from '@/lib/format';
import type {
  Agent, AgentConfig, AgentVersion, ChatMessage, ChatSession, Credential, Deployment, Execution, ExecutionEvent,
  ExecKind, LLMProvider, Member, Organization, Role, Tool, ToolVersion, User, Workflow, WorkflowDefinition, EventType,
} from '@/types/api';

/** In-browser demo database. Mirrors contract shapes; persisted to localStorage (best effort). */
export interface DemoDB {
  users: (User & { password: string })[];
  orgs: Organization[];
  members: (Member & { organization_id: string })[];
  providers: (LLMProvider & { organization_id: string })[];
  credentials: (Credential & { organization_id: string })[];
  agents: (Agent & { organization_id: string })[];
  agentVersions: AgentVersion[];
  tools: (Tool & { organization_id: string })[];
  toolVersions: (ToolVersion & { tool_id: string })[];
  workflows: (Workflow & { organization_id: string })[];
  workflowVersions: { id: string; workflow_id: string; version: number; definition: WorkflowDefinition; created_at: string }[];
  executions: (Execution & { organization_id: string })[];
  events: ExecutionEvent[];
  sessions: (ChatSession & { organization_id: string })[];
  messages: ChatMessage[];
  deployments: (Deployment & { organization_id: string })[];
}

const KEY = 'agentforge.demo.db.v1';
export const DEMO_USER = { email: 'demo@agentforge.ai', password: 'demo-password' };
export const now = () => new Date().toISOString();
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

export const defaultAgentConfig = (over: Partial<AgentConfig> = {}): AgentConfig => ({
  instructions: '', provider_id: null, model: null, temperature: 0.2, tool_ids: [], memory: 'none',
  max_retries: 1, timeout_seconds: 60, guardrails: { block_pii: false, max_output_chars: null },
  input_schema: null, output_schema: null, ...over,
});

function seed(): DemoDB {
  const uid = uuid();
  const org = uuid();
  const t = ago(60 * 24 * 3);
  const prov = uuid();
  const agentId = uuid();
  const toolId = uuid();
  const wfId = uuid();
  const cfg = defaultAgentConfig({
    instructions: 'You triage production incidents. Classify severity (low/medium/high) and propose next steps.',
    tool_ids: [toolId], guardrails: { block_pii: true, max_output_chars: 4000 },
  });
  const definition: WorkflowDefinition = {
    schema_version: '1.0',
    nodes: [
      { id: 'start-1', type: 'start', position: { x: 0, y: 80 }, data: { label: 'Start', config: {} } },
      { id: 'agent-1', type: 'agent', position: { x: 240, y: 80 }, data: { label: 'Incident Agent', config: { agent_id: agentId, agent_version: null, input_template: '{{input}}' } } },
      { id: 'cond-1', type: 'condition', position: { x: 500, y: 80 }, data: { label: 'Severe?', config: { expression: "state['last_output'].get('severity') == 'high'" } } },
      { id: 'tool-1', type: 'tool', position: { x: 760, y: 0 }, data: { label: 'Page on-call', config: { tool_id: toolId, tool_version: null, input_mapping: {} } } },
      { id: 'end-1', type: 'end', position: { x: 1000, y: 80 }, data: { label: 'End', config: {} } },
    ],
    edges: [
      { id: 'e1', source: 'start-1', target: 'agent-1' },
      { id: 'e2', source: 'agent-1', target: 'cond-1' },
      { id: 'e3', source: 'cond-1', target: 'tool-1', source_handle: 'true' },
      { id: 'e4', source: 'cond-1', target: 'end-1', source_handle: 'false' },
      { id: 'e5', source: 'tool-1', target: 'end-1' },
    ],
    viewport: { x: 40, y: 80, zoom: 0.9 },
  };
  const src = 'import httpx\n\n\ndef run(input: dict) -> dict:\n    """Notify the on-call engineer (demo)."""\n    return {"notified": True, "summary": input.get("summary", "")}\n';
  const db: DemoDB = {
    users: [{ id: uid, email: DEMO_USER.email, full_name: 'Demo User', status: 'active', created_at: t, password: DEMO_USER.password }],
    orgs: [{ id: org, name: 'Demo Org', slug: 'demo-org', status: 'active', created_at: t }],
    members: [{ organization_id: org, user_id: uid, email: DEMO_USER.email, full_name: 'Demo User', role: 'owner', joined_at: t }],
    providers: [{ organization_id: org, id: prov, provider: 'gemini', name: 'Gemini (demo)', status: 'active', is_default: true, default_model: 'gemini-1.5-flash', key_hint: '••••demo', config: {}, last_validated_at: t, created_at: t }],
    credentials: [{ organization_id: org, id: uuid(), name: 'pagerduty-token', kind: 'bearer_token', description: 'On-call paging', key_hint: '••••7f3a', created_at: t, rotated_at: null }],
    agents: [{ organization_id: org, id: agentId, name: 'Incident Triage', description: 'Classifies incidents and drafts responses', status: 'published', current_version: 1, config: cfg, created_by: uid, created_at: t, updated_at: t }],
    agentVersions: [{ id: uuid(), agent_id: agentId, version: 1, config: cfg, created_at: t, created_by: uid }],
    tools: [{ organization_id: org, id: toolId, name: 'page_oncall', description: 'Pages the on-call engineer', status: 'published', current_version: 1, source_code: src, input_schema: { type: 'object', properties: { summary: { type: 'string' } } }, output_schema: { type: 'object' }, requirements: ['httpx'], created_at: t, updated_at: t }],
    toolVersions: [{ id: uuid(), tool_id: toolId, version: 1, source_code: src, created_at: t }],
    workflows: [{ organization_id: org, id: wfId, name: 'Incident Response', description: 'Triage then page if severe', status: 'valid', current_version: 1, definition, created_at: t, updated_at: t }],
    workflowVersions: [{ id: uuid(), workflow_id: wfId, version: 1, definition, created_at: t }],
    executions: [], events: [], sessions: [], messages: [], deployments: [],
  };
  // Historical executions so dashboards are not empty.
  const kinds: [ExecKind, string][] = [['workflow', wfId], ['agent', agentId], ['tool_test', toolId], ['agent_test', agentId]];
  for (let i = 0; i < 14; i++) {
    const [kind, rid] = kinds[i % kinds.length];
    const failed = i % 5 === 3;
    const created = ago(i * 95 + 7);
    const dur = 800 + ((i * 337) % 4200);
    const id = uuid();
    db.executions.push({
      organization_id: org, id, kind, status: failed ? 'failed' : 'succeeded', resource_id: rid, resource_version: 1,
      input: { summary: `Demo incident #${100 + i}` }, output: failed ? null : { result: '[demo] simulated output' },
      error: failed ? 'Simulated failure (demo data)' : null, correlation_id: uuid(), created_by: uid, created_at: created,
      started_at: created, finished_at: new Date(Date.parse(created) + dur).toISOString(), duration_ms: dur,
    });
    const evs: [EventType, string | null, Record<string, unknown>][] = [
      ['execution.queued', null, {}], ['execution.started', null, {}], ['log', null, { level: 'INFO', message: 'Demo execution started' }],
      [failed ? 'execution.failed' : 'execution.completed', null, failed ? { error: 'Simulated failure (demo data)' } : {}],
    ];
    evs.forEach(([event_type, node_id, payload], s) =>
      db.events.push({ id: uuid(), execution_id: id, sequence: s + 1, event_type, node_id, payload, created_at: created }),
    );
  }
  return db;
}

let cache: DemoDB | null = null;
export function getDB(): DemoDB {
  if (!cache) cache = storage.getJSON<DemoDB>(KEY) ?? seed();
  return cache;
}
export function saveDB(): void {
  if (cache) storage.setJSON(KEY, cache);
}
export function resetDB(): void {
  cache = seed();
  saveDB();
}

export function addEvent(executionId: string, event_type: EventType, payload: Record<string, unknown> = {}, node_id: string | null = null) {
  const db = getDB();
  const seq = db.events.filter((e) => e.execution_id === executionId).reduce((m, e) => Math.max(m, e.sequence), 0) + 1;
  const ev: ExecutionEvent = { id: uuid(), execution_id: executionId, sequence: seq, event_type, node_id, payload, created_at: now() };
  db.events.push(ev);
  saveDB();
  return ev;
}

export function mockEventsAfter(executionId: string, after: number): ExecutionEvent[] {
  return getDB().events.filter((e) => e.execution_id === executionId && e.sequence > after).sort((a, b) => a.sequence - b.sequence);
}

/** Plan of simulated node steps for a workflow (follows `true` branch of conditions). */
function workflowPath(def: WorkflowDefinition): string[] {
  const path: string[] = [];
  let cur = def.nodes.find((n) => n.type === 'start');
  const seen = new Set<string>();
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    path.push(cur.id);
    const out = def.edges.filter((e) => e.source === cur!.id);
    const next = out.find((e) => e.source_handle === 'true') ?? out[0];
    cur = next ? def.nodes.find((n) => n.id === next.target) : undefined;
  }
  return path;
}

const DEMO_REPLY = 'This is a simulated demo response. No LLM was called — connect a backend and an LLM provider for real output.';

/** Starts an execution and simulates its lifecycle with timers. */
export function startExecution(orgId: string, userId: string, kind: ExecKind, resourceId: string, version: number, input: unknown, onDone?: (output: string) => void) {
  const db = getDB();
  const exec: Execution & { organization_id: string } = {
    organization_id: orgId, id: uuid(), kind, status: 'queued', resource_id: resourceId, resource_version: version, input,
    output: null, error: null, correlation_id: uuid(), created_by: userId, created_at: now(), started_at: null, finished_at: null, duration_ms: null,
  };
  db.executions.unshift(exec);
  addEvent(exec.id, 'execution.queued');
  const steps: (() => void)[] = [];
  const set = (patch: Partial<Execution>) => {
    const e = getDB().executions.find((x) => x.id === exec.id);
    if (e) Object.assign(e, patch);
    saveDB();
    return e;
  };
  const live = () => getDB().executions.find((x) => x.id === exec.id)?.status !== 'cancelled';
  steps.push(() => {
    set({ status: 'running', started_at: now() });
    addEvent(exec.id, 'execution.started');
    addEvent(exec.id, 'log', { level: 'INFO', message: 'Demo mode: simulating execution (no LLM call).' });
  });
  if (kind === 'workflow') {
    const wf = db.workflows.find((w) => w.id === resourceId);
    for (const nodeId of wf ? workflowPath(wf.definition) : []) {
      steps.push(() => addEvent(exec.id, 'node.started', {}, nodeId));
      steps.push(() => addEvent(exec.id, 'node.completed', { output: `[demo] ${nodeId} done` }, nodeId));
    }
  } else if (kind === 'tool_test') {
    steps.push(() => addEvent(exec.id, 'log', { level: 'INFO', message: 'Sandbox run simulated (demo).' }));
  } else {
    for (const word of DEMO_REPLY.split(' ')) steps.push(() => addEvent(exec.id, 'llm.token', { text: `${word} ` }));
  }
  steps.push(() => {
    const e = set({ status: 'succeeded', output: { result: DEMO_REPLY }, finished_at: now() });
    if (e?.started_at) set({ duration_ms: Date.parse(e.finished_at!) - Date.parse(e.started_at) });
    addEvent(exec.id, 'execution.completed', { output: { result: DEMO_REPLY } });
    onDone?.(DEMO_REPLY);
  });
  steps.forEach((fn, i) => setTimeout(() => live() && fn(), 300 + i * (kind === 'workflow' ? 450 : 90)));
  saveDB();
  return exec;
}

export type Scoped = { organization_id: string };
export const strip = <T extends Scoped>(o: T): Omit<T, 'organization_id'> => {
  const { organization_id: _o, ...rest } = o;
  return rest;
};
export const roleOf = (orgId: string, userId: string): Role | undefined =>
  getDB().members.find((m) => m.organization_id === orgId && m.user_id === userId)?.role;
