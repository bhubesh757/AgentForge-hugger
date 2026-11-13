import { AxiosError, AxiosHeaders, type AxiosAdapter, type AxiosResponse } from 'axios';
import { uuid } from '@/lib/format';
import { can, type Permission } from '@/lib/rbac';
import { validateDefinition } from '@/features/workflow/validate';
import type { AgentConfig, Role, WorkflowDefinition, ConnectProvider } from '@/types/api';
import { getDB, saveDB, now, strip, roleOf, startExecution, addEvent, defaultAgentConfig, type DemoDB } from './db';

export interface MockRequest { method: string; url: string; params?: Record<string, unknown>; data?: unknown; headers?: Record<string, string | undefined> }
export interface MockResponse { status: number; data: unknown; headers: Record<string, string> }

class MockErr extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) {
    super(message);
  }
}
interface Ctx { m: RegExpMatchArray; q: URLSearchParams; body: Record<string, unknown>; userId: string; orgId: string; role: Role }
type Handler = (c: Ctx) => unknown;
interface Route { method: string; re: RegExp; auth: 'none' | 'user' | 'org'; perm?: Permission; status?: number; h: Handler }

const routes: Route[] = [];
const r = (method: string, path: string, auth: Route['auth'], h: Handler, perm?: Permission, status?: number) =>
  routes.push({ method, re: new RegExp(`^${path.replace(/:id/g, '([^/]+)')}$`), auth, h, perm, status });

const page = <T,>(items: T[], q: URLSearchParams) => {
  const p = Math.max(1, Number(q.get('page') ?? 1));
  const size = Math.min(100, Math.max(1, Number(q.get('page_size') ?? 20)));
  return { items: items.slice((p - 1) * size, p * size), total: items.length, page: p, page_size: size };
};
const tokens = (userId: string) => ({ access_token: `demo.${userId}`, refresh_token: `demo-r.${userId}.${uuid()}`, token_type: 'bearer', expires_in: 900 });
const db = (): DemoDB => getDB();
function find<T extends { id: string; organization_id?: string }>(list: T[], id: string, orgId?: string): T {
  const x = list.find((i) => i.id === id && (!orgId || i.organization_id === orgId));
  if (!x) throw new MockErr(404, 'NOT_FOUND', 'Resource not found');
  return x;
}
const search = <T extends { name: string }>(items: T[], q: URLSearchParams) => {
  const s = (q.get('search') ?? '').toLowerCase();
  return s ? items.filter((i) => i.name.toLowerCase().includes(s)) : items;
};
const byOrg = <T extends { organization_id: string }>(items: T[], c: Ctx) => items.filter((i) => i.organization_id === c.orgId).map(strip);
const required = (body: Record<string, unknown>, ...keys: string[]) => {
  const missing = keys.filter((k) => body[k] === undefined || body[k] === '');
  if (missing.length) throw new MockErr(422, 'VALIDATION_ERROR', `Missing fields: ${missing.join(', ')}`, { fields: missing });
};
const hint = (v: string) => `••••${v.slice(-4)}`;

// ---- auth
r('POST', '/auth/register', 'none', ({ body }) => {
  required(body, 'email', 'password', 'full_name');
  if (String(body.password).length < 10) throw new MockErr(422, 'VALIDATION_ERROR', 'Password must be at least 10 characters');
  if (db().users.some((u) => u.email === body.email)) throw new MockErr(409, 'CONFLICT', 'Email already registered');
  const u = { id: uuid(), email: String(body.email), full_name: String(body.full_name), status: 'active' as const, created_at: now(), password: String(body.password) };
  db().users.push(u);
  if (body.organization_name) createOrg(u.id, String(body.organization_name));
  return tokens(u.id);
}, undefined, 201);
r('POST', '/auth/login', 'none', ({ body }) => {
  const u = db().users.find((x) => x.email === body.email && x.password === body.password);
  if (!u) throw new MockErr(401, 'UNAUTHENTICATED', 'Invalid email or password');
  return tokens(u.id);
});
r('POST', '/auth/refresh', 'none', ({ body }) => {
  const id = String(body.refresh_token ?? '').split('.')[1];
  if (!id || !db().users.some((u) => u.id === id)) throw new MockErr(401, 'UNAUTHENTICATED', 'Invalid refresh token');
  return tokens(id);
});
r('POST', '/auth/logout', 'none', () => null, undefined, 204);
r('GET', '/auth/me', 'user', ({ userId }) => {
  const { password: _p, ...u } = find(db().users, userId);
  const memberships = db().members.filter((m) => m.user_id === userId).map((m) => {
    const o = find(db().orgs, m.organization_id);
    return { organization_id: o.id, organization_name: o.name, organization_slug: o.slug, role: m.role };
  });
  return { ...u, memberships };
});

// ---- organizations
function createOrg(userId: string, name: string, slug?: string) {
  const u = find(db().users, userId);
  const o = { id: uuid(), name, slug: slug || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''), status: 'active' as const, created_at: now() };
  db().orgs.push(o);
  db().members.push({ organization_id: o.id, user_id: u.id, email: u.email, full_name: u.full_name, role: 'owner', joined_at: now() });
  return o;
}
const orgMember = (c: Ctx, orgId: string) => {
  const role = roleOf(orgId, c.userId);
  if (!role) throw new MockErr(404, 'NOT_FOUND', 'Organization not found');
  return role;
};
r('POST', '/organizations', 'user', ({ body, userId }) => (required(body, 'name'), createOrg(userId, String(body.name), body.slug as string)), undefined, 201);
r('GET', '/organizations', 'user', ({ userId, q }) =>
  page(db().members.filter((m) => m.user_id === userId).map((m) => ({ ...find(db().orgs, m.organization_id), role: m.role })), q));
r('GET', '/organizations/:id', 'user', (c) => (orgMember(c, c.m[1]), find(db().orgs, c.m[1])));
r('PUT', '/organizations/:id', 'user', (c) => {
  if (!can(orgMember(c, c.m[1]), 'org.manage')) throw new MockErr(403, 'FORBIDDEN', 'Requires org.manage');
  return Object.assign(find(db().orgs, c.m[1]), c.body.name ? { name: c.body.name } : {});
});
r('GET', '/organizations/:id/members', 'user', (c) => (orgMember(c, c.m[1]), page(db().members.filter((m) => m.organization_id === c.m[1]).map(strip), c.q)));
r('POST', '/organizations/:id/members', 'user', (c) => {
  if (!can(orgMember(c, c.m[1]), 'org.manage')) throw new MockErr(403, 'FORBIDDEN', 'Requires org.manage');
  const u = db().users.find((x) => x.email === c.body.email);
  if (!u) throw new MockErr(404, 'NOT_FOUND', 'User not found — they must register first');
  if (db().members.some((m) => m.organization_id === c.m[1] && m.user_id === u.id)) throw new MockErr(409, 'CONFLICT', 'Already a member');
  const mem = { organization_id: c.m[1], user_id: u.id, email: u.email, full_name: u.full_name, role: c.body.role as Role, joined_at: now() };
  db().members.push(mem);
  return strip(mem);
}, undefined, 201);
r('DELETE', '/organizations/:id/members/([^/]+)', 'user', (c) => {
  if (!can(orgMember(c, c.m[1]), 'org.manage')) throw new MockErr(403, 'FORBIDDEN', 'Requires org.manage');
  const members = db().members.filter((m) => m.organization_id === c.m[1]);
  const target = members.find((m) => m.user_id === c.m[2]);
  if (!target) throw new MockErr(404, 'NOT_FOUND', 'Member not found');
  if (target.role === 'owner' && members.filter((m) => m.role === 'owner').length === 1) throw new MockErr(409, 'CONFLICT', 'Cannot remove the last owner');
  db().members.splice(db().members.indexOf(target), 1);
  return null;
}, undefined, 204);

// ---- LLM providers (demo: keys starting with "mock-" or "demo" validate; nothing is called)
r('GET', '/llm/providers', 'org', (c) => page(byOrg(db().providers, c), c.q));
r('POST', '/llm/providers/connect', 'org', ({ body, orgId }) => {
  const b = body as unknown as ConnectProvider;
  required(body, 'provider', 'api_key');
  if (b.provider === 'azure_openai') required(body, 'endpoint', 'deployment_name', 'api_version');
  const valid = /^(mock-|demo)/.test(b.api_key);
  const p = {
    organization_id: orgId, id: uuid(), provider: b.provider, name: b.name || (b.provider === 'gemini' ? 'Gemini' : 'Azure OpenAI'),
    status: valid ? ('valid' as const) : ('invalid' as const), is_default: false, default_model: b.default_model ?? null, key_hint: hint(b.api_key),
    config: b.provider === 'azure_openai' ? { endpoint: b.endpoint, deployment_name: b.deployment_name, api_version: b.api_version } : {},
    last_validated_at: now(), created_at: now(),
  };
  db().providers.push(p);
  return strip(p);
}, 'llm.manage', 201);
r('POST', '/llm/providers/:id/validate', 'org', (c) => {
  const p = find(db().providers, c.m[1], c.orgId);
  p.last_validated_at = now();
  const valid = p.status !== 'invalid';
  return { valid, message: valid ? 'Demo: key format accepted (no network call made)' : 'Demo: use a key starting with "mock-" to simulate a valid key', provider: strip(p) };
}, 'llm.manage');
r('GET', '/llm/providers/:id/models', 'org', (c) => {
  const p = find(db().providers, c.m[1], c.orgId);
  const ids = p.provider === 'gemini' ? ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash'] : [p.config.deployment_name ?? 'gpt-4o'];
  return { models: ids.map((id) => ({ id, display_name: id })) };
});
r('POST', '/llm/providers/:id/activate', 'org', (c) => {
  const p = find(db().providers, c.m[1], c.orgId);
  if (p.status === 'invalid' || p.status === 'pending_validation') throw new MockErr(409, 'CONFLICT', 'Provider must be valid before activation');
  db().providers.filter((x) => x.organization_id === c.orgId).forEach((x) => {
    if (x.is_default) Object.assign(x, { is_default: false, status: 'valid' });
  });
  Object.assign(p, { status: 'active', is_default: true }, c.body.default_model ? { default_model: c.body.default_model } : {});
  return strip(p);
}, 'llm.manage');
r('POST', '/llm/providers/:id/deactivate', 'org', (c) => strip(Object.assign(find(db().providers, c.m[1], c.orgId), { status: 'inactive', is_default: false })), 'llm.manage');
r('DELETE', '/llm/providers/:id', 'org', (c) => (db().providers.splice(db().providers.indexOf(find(db().providers, c.m[1], c.orgId)), 1), null), 'llm.manage', 204);

// ---- credentials
r('GET', '/credentials', 'org', (c) => page(byOrg(db().credentials, c), c.q));
r('POST', '/credentials', 'org', ({ body, orgId }) => {
  required(body, 'name', 'kind', 'value');
  const cr = { organization_id: orgId, id: uuid(), name: String(body.name), kind: body.kind as 'api_key', description: String(body.description ?? ''), key_hint: hint(String(body.value)), created_at: now(), rotated_at: null };
  db().credentials.push(cr);
  return strip(cr);
}, 'llm.manage', 201);
r('POST', '/credentials/:id/validate', 'org', (c) => (find(db().credentials, c.m[1], c.orgId), { valid: true, message: 'Format OK (demo)' }), 'llm.manage');
r('POST', '/credentials/:id/rotate', 'org', (c) => {
  required(c.body, 'value');
  return strip(Object.assign(find(db().credentials, c.m[1], c.orgId), { key_hint: hint(String(c.body.value)), rotated_at: now() }));
}, 'llm.manage');
r('DELETE', '/credentials/:id', 'org', (c) => (db().credentials.splice(db().credentials.indexOf(find(db().credentials, c.m[1], c.orgId)), 1), null), 'llm.manage', 204);

// ---- agents
r('GET', '/agents', 'org', (c) => {
  const st = c.q.get('status');
  return page(search(byOrg(db().agents, c), c.q).filter((a) => !st || a.status === st), c.q);
});
r('POST', '/agents/generate', 'org', ({ body }) => {
  required(body, 'prompt');
  const p = String(body.prompt);
  const name = p.split(/\s+/).slice(0, 4).join(' ').replace(/[^\w\s-]/g, '') || 'Generated Agent';
  return { draft: { name, description: `Demo draft generated from: "${p.slice(0, 80)}"`, config: defaultAgentConfig({ instructions: `You are an assistant. Task: ${p}\n(Demo template — no LLM was called.)` }) } };
}, 'resource.write');
r('POST', '/agents', 'org', ({ body, orgId, userId }) => {
  required(body, 'name', 'config');
  const a = { organization_id: orgId, id: uuid(), name: String(body.name), description: String(body.description ?? ''), status: 'draft' as const, current_version: 1, config: body.config as AgentConfig, created_by: userId, created_at: now(), updated_at: now() };
  db().agents.push(a);
  db().agentVersions.push({ id: uuid(), agent_id: a.id, version: 1, config: a.config, created_at: now(), created_by: userId });
  return strip(a);
}, 'resource.write', 201);
r('GET', '/agents/:id', 'org', (c) => strip(find(db().agents, c.m[1], c.orgId)));
const newAgentVersion = (a: DemoDB['agents'][number], config: AgentConfig, userId: string) => {
  a.current_version += 1;
  a.config = config;
  db().agentVersions.push({ id: uuid(), agent_id: a.id, version: a.current_version, config, created_at: now(), created_by: userId });
};
r('PUT', '/agents/:id', 'org', (c) => {
  const a = find(db().agents, c.m[1], c.orgId);
  if (c.body.name) a.name = String(c.body.name);
  if (c.body.description !== undefined) a.description = String(c.body.description);
  if (c.body.config) newAgentVersion(a, c.body.config as AgentConfig, c.userId);
  a.updated_at = now();
  return strip(a);
}, 'resource.write');
r('POST', '/agents/:id/publish', 'org', (c) => strip(Object.assign(find(db().agents, c.m[1], c.orgId), { status: 'published', updated_at: now() })), 'resource.write');
r('GET', '/agents/:id/versions', 'org', (c) => (find(db().agents, c.m[1], c.orgId), page(db().agentVersions.filter((v) => v.agent_id === c.m[1]).sort((a, b) => b.version - a.version), c.q)));
r('POST', '/agents/:id/rollback', 'org', (c) => {
  const a = find(db().agents, c.m[1], c.orgId);
  const v = db().agentVersions.find((x) => x.agent_id === a.id && x.version === Number(c.body.version));
  if (!v) throw new MockErr(404, 'NOT_FOUND', 'Version not found');
  newAgentVersion(a, v.config, c.userId);
  return strip(a);
}, 'resource.write');
r('POST', '/agents/:id/(test|execute)', 'org', (c) => {
  const a = find(db().agents, c.m[1], c.orgId);
  return strip(startExecution(c.orgId, c.userId, c.m[2] === 'test' ? 'agent_test' : 'agent', a.id, a.current_version, c.body.input));
}, 'execution.run', 202);

// ---- tools
r('GET', '/tools', 'org', (c) => page(search(byOrg(db().tools, c), c.q), c.q));
r('POST', '/tools/generate', 'org', ({ body }) => {
  required(body, 'prompt');
  const name = (String(body.prompt).toLowerCase().match(/[a-z]+/g) ?? ['tool']).slice(0, 3).join('_');
  const source_code = `def run(input: dict) -> dict:\n    """${String(body.prompt).replace(/"/g, "'").slice(0, 120)}\n\n    Demo template generated without an LLM.\n    """\n    value = input.get("value")\n    return {"result": value}\n`;
  return {
    draft: { name, description: String(body.prompt).slice(0, 200), source_code, input_schema: { type: 'object', properties: { value: { type: 'string' } } }, output_schema: { type: 'object', properties: { result: {} } }, requirements: [], tests: [] },
    static_analysis: { ok: true, issues: [] },
  };
}, 'resource.write');
const analyze = (code: string) => {
  const issues: string[] = [];
  if (!/def run\(input: dict\) -> dict:/.test(code)) issues.push('Missing `def run(input: dict) -> dict:` entrypoint');
  for (const mod of ['os', 'subprocess', 'socket', 'sys', 'shutil']) if (new RegExp(`^\\s*(import|from)\\s+${mod}\\b`, 'm').test(code)) issues.push(`Blocked import: ${mod}`);
  return issues;
};
r('POST', '/tools', 'org', ({ body, orgId }) => {
  required(body, 'name', 'source_code');
  const issues = analyze(String(body.source_code));
  if (issues.length) throw new MockErr(422, 'VALIDATION_ERROR', 'Static analysis failed', { issues });
  const t = { organization_id: orgId, id: uuid(), name: String(body.name), description: String(body.description ?? ''), status: 'draft' as const, current_version: 1, source_code: String(body.source_code), input_schema: (body.input_schema as object) ?? {}, output_schema: (body.output_schema as object) ?? {}, requirements: (body.requirements as string[]) ?? [], created_at: now(), updated_at: now() };
  db().tools.push(t);
  db().toolVersions.push({ id: uuid(), tool_id: t.id, version: 1, source_code: t.source_code, created_at: now() });
  return strip(t);
}, 'resource.write', 201);
r('GET', '/tools/:id', 'org', (c) => strip(find(db().tools, c.m[1], c.orgId)));
r('PUT', '/tools/:id', 'org', (c) => {
  const t = find(db().tools, c.m[1], c.orgId);
  if (c.body.source_code !== undefined) {
    const issues = analyze(String(c.body.source_code));
    if (issues.length) throw new MockErr(422, 'VALIDATION_ERROR', 'Static analysis failed', { issues });
  }
  Object.assign(t, c.body, { current_version: t.current_version + 1, updated_at: now() });
  db().toolVersions.push({ id: uuid(), tool_id: t.id, version: t.current_version, source_code: t.source_code, created_at: now() });
  return strip(t);
}, 'resource.write');
r('POST', '/tools/:id/publish', 'org', (c) => strip(Object.assign(find(db().tools, c.m[1], c.orgId), { status: 'published' })), 'resource.write');
r('GET', '/tools/:id/versions', 'org', (c) => page(db().toolVersions.filter((v) => v.tool_id === c.m[1]).map(({ tool_id: _t, ...v }) => v).sort((a, b) => b.version - a.version), c.q));
r('POST', '/tools/:id/test', 'org', (c) => {
  const t = find(db().tools, c.m[1], c.orgId);
  if (t.status === 'draft') t.status = 'tested';
  return strip(startExecution(c.orgId, c.userId, 'tool_test', t.id, t.current_version, c.body.input));
}, 'execution.run', 202);

// ---- workflows
r('GET', '/workflows', 'org', (c) => page(search(byOrg(db().workflows, c), c.q), c.q));
r('POST', '/workflows', 'org', ({ body, orgId }) => {
  required(body, 'name', 'definition');
  const w = { organization_id: orgId, id: uuid(), name: String(body.name), description: String(body.description ?? ''), status: 'draft' as const, current_version: 1, definition: body.definition as WorkflowDefinition, created_at: now(), updated_at: now() };
  db().workflows.push(w);
  db().workflowVersions.push({ id: uuid(), workflow_id: w.id, version: 1, definition: w.definition, created_at: now() });
  return strip(w);
}, 'resource.write', 201);
r('GET', '/workflows/:id', 'org', (c) => strip(find(db().workflows, c.m[1], c.orgId)));
r('PUT', '/workflows/:id', 'org', (c) => {
  const w = find(db().workflows, c.m[1], c.orgId);
  if (c.body.name) w.name = String(c.body.name);
  if (c.body.description !== undefined) w.description = String(c.body.description);
  if (c.body.definition) {
    w.definition = c.body.definition as WorkflowDefinition;
    w.current_version += 1;
    w.status = 'draft';
    db().workflowVersions.push({ id: uuid(), workflow_id: w.id, version: w.current_version, definition: w.definition, created_at: now() });
  }
  w.updated_at = now();
  return strip(w);
}, 'resource.write');
const serverValidate = (c: Ctx, def: WorkflowDefinition) => {
  const issues = validateDefinition(def, {
    agentIds: db().agents.filter((a) => a.organization_id === c.orgId).map((a) => a.id),
    toolIds: db().tools.filter((t) => t.organization_id === c.orgId).map((t) => t.id),
  });
  return { valid: issues.length === 0, issues };
};
r('POST', '/workflows/:id/validate', 'org', (c) => {
  const w = find(db().workflows, c.m[1], c.orgId);
  const res = serverValidate(c, (c.body.definition as WorkflowDefinition) ?? w.definition);
  if (!c.body.definition && res.valid && w.status === 'draft') w.status = 'valid';
  return res;
});
r('POST', '/workflows/:id/publish', 'org', (c) => {
  const w = find(db().workflows, c.m[1], c.orgId);
  const res = serverValidate(c, w.definition);
  if (!res.valid) throw new MockErr(422, 'VALIDATION_ERROR', 'Workflow is invalid', { issues: res.issues });
  return strip(Object.assign(w, { status: 'published' }));
}, 'resource.write');
r('POST', '/workflows/:id/execute', 'org', (c) => {
  const w = find(db().workflows, c.m[1], c.orgId);
  const res = serverValidate(c, w.definition);
  if (!res.valid) throw new MockErr(422, 'VALIDATION_ERROR', 'Workflow is invalid', { issues: res.issues });
  return strip(startExecution(c.orgId, c.userId, 'workflow', w.id, w.current_version, c.body.input));
}, 'execution.run', 202);
r('GET', '/workflows/:id/versions', 'org', (c) => page(db().workflowVersions.filter((v) => v.workflow_id === c.m[1]).map(({ workflow_id: _w, ...v }) => v).sort((a, b) => b.version - a.version), c.q));

// ---- executions
r('GET', '/executions', 'org', (c) => {
  const f = (k: string) => c.q.get(k);
  return page(byOrg(db().executions, c).filter((e) => (!f('status') || e.status === f('status')) && (!f('kind') || e.kind === f('kind')) && (!f('resource_id') || e.resource_id === f('resource_id'))), c.q);
});
r('GET', '/executions/:id', 'org', (c) => strip(find(db().executions, c.m[1], c.orgId)));
r('GET', '/executions/:id/events', 'org', (c) => {
  find(db().executions, c.m[1], c.orgId);
  const after = Number(c.q.get('after_sequence') ?? 0);
  return { items: db().events.filter((e) => e.execution_id === c.m[1] && e.sequence > after).sort((a, b) => a.sequence - b.sequence) };
});
r('GET', '/executions/:id/logs', 'org', (c) => {
  find(db().executions, c.m[1], c.orgId);
  return {
    items: db().events.filter((e) => e.execution_id === c.m[1] && (e.event_type === 'log' || e.event_type === 'node.failed')).map((e) => ({
      timestamp: e.created_at, level: e.event_type === 'node.failed' ? 'ERROR' : String(e.payload.level ?? 'INFO'), message: String(e.payload.message ?? e.payload.error ?? ''), node_id: e.node_id,
    })),
  };
});
r('POST', '/executions/:id/cancel', 'org', (c) => {
  const e = find(db().executions, c.m[1], c.orgId);
  if (e.status === 'queued' || e.status === 'running') {
    Object.assign(e, { status: 'cancelled', finished_at: now() });
    addEvent(e.id, 'execution.cancelled');
  }
  return strip(e);
}, 'execution.run');

// ---- chat
r('GET', '/chat/sessions', 'org', (c) => page(byOrg(db().sessions, c).sort((a, b) => b.updated_at.localeCompare(a.updated_at)), c.q));
r('POST', '/chat/sessions', 'org', ({ body, orgId }) => {
  required(body, 'target_type', 'target_id');
  const s = { organization_id: orgId, id: uuid(), title: String(body.title || 'New chat'), target_type: body.target_type as 'agent', target_id: String(body.target_id), created_at: now(), updated_at: now() };
  db().sessions.push(s);
  return strip(s);
}, 'execution.run', 201);
r('GET', '/chat/sessions/:id/messages', 'org', (c) => (find(db().sessions, c.m[1], c.orgId), page(db().messages.filter((m) => m.session_id === c.m[1]), c.q)));
r('POST', '/chat/sessions/:id/messages', 'org', (c) => {
  const s = find(db().sessions, c.m[1], c.orgId);
  required(c.body, 'content');
  const user_message = { id: uuid(), session_id: s.id, role: 'user' as const, content: String(c.body.content), execution_id: null, created_at: now() };
  db().messages.push(user_message);
  s.updated_at = now();
  const execution = startExecution(c.orgId, c.userId, s.target_type === 'workflow' ? 'workflow' : 'chat', s.target_id, 1, { message: user_message.content }, (out) => {
    getDB().messages.push({ id: uuid(), session_id: s.id, role: 'assistant', content: out, execution_id: execution.id, created_at: now() });
    saveDB();
  });
  return { user_message, execution: strip(execution) };
}, 'execution.run', 202);

// ---- deployments, audit, monitoring
r('GET', '/deployments', 'org', (c) => page(byOrg(db().deployments, c), c.q));
r('POST', '/deployments', 'org', ({ body, orgId }) => {
  required(body, 'resource_type', 'resource_id', 'environment');
  const d = { organization_id: orgId, id: uuid(), resource_type: body.resource_type as 'agent', resource_id: String(body.resource_id), environment: body.environment as 'dev', status: 'recorded', created_at: now() };
  db().deployments.push(d);
  return strip(d);
}, 'resource.write', 201);
r('GET', '/deployments/:id', 'org', (c) => strip(find(db().deployments, c.m[1], c.orgId)));
r('GET', '/audit-logs', 'org', (c) => page([], c.q), 'org.manage');
r('GET', '/health', 'none', () => ({ status: 'ok', version: '1.0.1', api_version: 'v1' }));
r('GET', '/ready', 'none', () => ({ status: 'ready', checks: { database: 'demo', redis: 'demo', kafka: 'disabled' } }));
r('GET', '/monitoring/summary', 'org', (c) => {
  const since = Date.now() - 86_400_000;
  const ex = byOrg(db().executions, c).filter((e) => Date.parse(e.created_at) >= since);
  const count = (k: 'status' | 'kind') => ex.reduce<Record<string, number>>((acc, e) => ((acc[e[k]] = (acc[e[k]] ?? 0) + 1), acc), {});
  const durs = ex.map((e) => e.duration_ms).filter((d): d is number => d != null);
  const ap = db().providers.find((p) => p.organization_id === c.orgId && p.is_default);
  return {
    executions_24h: ex.length, succeeded_24h: ex.filter((e) => e.status === 'succeeded').length, failed_24h: ex.filter((e) => e.status === 'failed').length,
    avg_duration_ms: durs.length ? Math.round(durs.reduce((a, b) => a + b, 0) / durs.length) : null,
    by_status: count('status'), by_kind: count('kind'),
    agents: byOrg(db().agents, c).length, tools: byOrg(db().tools, c).length, workflows: byOrg(db().workflows, c).length,
    active_provider: ap ? strip(ap) : null,
  };
});

const err = (status: number, code: string, message: string, details: Record<string, unknown> = {}): MockResponse => ({
  status, data: { error: { code, message, details, request_id: uuid() } }, headers: {},
});

/** Handles a request against the in-memory demo backend. Never throws. */
export async function mockRequest(req: MockRequest): Promise<MockResponse> {
  await new Promise((res) => setTimeout(res, 120));
  const url = new URL(req.url, 'http://mock.local');
  const path = url.pathname.replace(/^.*?\/api\/v1(?=\/)/, '').replace(/\/+$/, '') || '/';
  const q = url.searchParams;
  for (const [k, v] of Object.entries(req.params ?? {})) if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
  const method = req.method.toUpperCase();
  const headers = Object.fromEntries(Object.entries(req.headers ?? {}).map(([k, v]) => [k.toLowerCase(), v]));
  const reqId = headers['x-request-id'] ?? uuid();
  let body: Record<string, unknown> = {};
  if (typeof req.data === 'string' && req.data) {
    try {
      body = JSON.parse(req.data);
    } catch {
      return err(422, 'VALIDATION_ERROR', 'Malformed JSON body');
    }
  } else if (req.data && typeof req.data === 'object') body = req.data as Record<string, unknown>;

  const matches = routes.map((rt) => ({ rt, m: path.match(rt.re) })).filter((x) => x.m);
  const hit = matches.find((x) => x.rt.method === method);
  if (!hit) return matches.length ? err(405, 'VALIDATION_ERROR', 'Method not allowed') : err(404, 'NOT_FOUND', `No route for ${method} ${path}`);
  try {
    const ctx: Ctx = { m: hit.m!, q, body, userId: '', orgId: '', role: 'viewer' };
    if (hit.rt.auth !== 'none') {
      const tok = (headers['authorization'] ?? '').replace(/^Bearer\s+/i, '');
      const uid = tok.startsWith('demo.') ? tok.slice(5) : '';
      if (!uid || !db().users.some((u) => u.id === uid)) throw new MockErr(401, 'UNAUTHENTICATED', 'Not authenticated');
      ctx.userId = uid;
    }
    if (hit.rt.auth === 'org') {
      const org = headers['x-organization-id'];
      if (!org) throw new MockErr(400, 'ORG_HEADER_REQUIRED', 'X-Organization-ID header is required');
      const role = roleOf(org, ctx.userId);
      if (!role) throw new MockErr(403, 'ORG_FORBIDDEN', 'Not a member of this organization');
      Object.assign(ctx, { orgId: org, role });
    }
    if (hit.rt.perm && !can(ctx.role, hit.rt.perm)) throw new MockErr(403, 'FORBIDDEN', `Requires ${hit.rt.perm}`);
    const data = hit.rt.h(ctx);
    saveDB();
    return { status: hit.rt.status ?? 200, data: data ?? '', headers: { 'x-request-id': reqId, 'content-type': 'application/json' } };
  } catch (e) {
    if (e instanceof MockErr) return err(e.status, e.code, e.message, e.details);
    return err(500, 'INTERNAL_ERROR', (e as Error).message);
  }
}

export const mockAdapter: AxiosAdapter = async (config) => {
  const headers: Record<string, string> = {};
  AxiosHeaders.from(config.headers as AxiosHeaders).forEach((v: unknown, k: string) => (headers[k] = String(v)));
  const res = await mockRequest({ method: config.method ?? 'get', url: `${config.baseURL ?? ''}${config.url ?? ''}`, params: config.params, data: config.data, headers });
  const response: AxiosResponse = { data: res.data, status: res.status, statusText: String(res.status), headers: res.headers, config, request: {} };
  if (res.status >= 400) throw new AxiosError(`Request failed with status code ${res.status}`, AxiosError.ERR_BAD_RESPONSE, config, {}, response);
  return response;
};
