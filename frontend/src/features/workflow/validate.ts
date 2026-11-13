import type { ValidationIssue, WorkflowDefinition } from '@/types/api';

export const NODE_TYPES = ['start', 'end', 'agent', 'tool', 'llm', 'rag', 'api', 'condition'] as const;

/** Client-side mirror of contract §8.1 validation rules (backend is authoritative). */
export function validateDefinition(def: WorkflowDefinition, refs?: { agentIds?: string[]; toolIds?: string[] }): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const add = (code: string, message: string, node_id: string | null = null, edge_id: string | null = null) => issues.push({ node_id, edge_id, code, message });
  const ids = new Set(def.nodes.map((n) => n.id));
  const starts = def.nodes.filter((n) => n.type === 'start');
  if (starts.length !== 1) add('START_COUNT', `Workflow must have exactly one start node (found ${starts.length})`);
  if (!def.nodes.some((n) => n.type === 'end')) add('NO_END', 'Workflow must have at least one end node');
  for (const n of def.nodes) if (!(NODE_TYPES as readonly string[]).includes(n.type)) add('UNKNOWN_TYPE', `Unknown node type "${n.type}"`, n.id);
  for (const e of def.edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) add('DANGLING_EDGE', `Edge ${e.id} references a missing node`, null, e.id);
  }
  const out = (id: string) => def.edges.filter((e) => e.source === id);
  for (const n of def.nodes) {
    const o = out(n.id);
    if (n.type !== 'end' && o.length === 0) add('NO_OUTGOING', `"${n.data.label}" has no outgoing edge`, n.id);
    if (n.type !== 'condition' && n.type !== 'end' && o.length > 1) add('FANOUT', `"${n.data.label}" has multiple outgoing edges; only condition nodes may branch`, n.id);
    if (n.type === 'end' && o.length) add('END_HAS_OUTGOING', `End node "${n.data.label}" must not have outgoing edges`, n.id);
    const c = n.data.config ?? {};
    if (n.type === 'condition') {
      const t = o.filter((e) => e.source_handle === 'true').length;
      const f = o.filter((e) => e.source_handle === 'false').length;
      if (t !== 1 || f !== 1 || o.length !== 2) add('CONDITION_BRANCHES', `Condition "${n.data.label}" needs exactly one "true" and one "false" edge`, n.id);
      if (!String(c.expression ?? '').trim()) add('MISSING_CONFIG', `Condition "${n.data.label}" needs an expression`, n.id);
    }
    if (n.type === 'agent') {
      if (!c.agent_id) add('MISSING_CONFIG', `Agent node "${n.data.label}" needs an agent`, n.id);
      else if (refs?.agentIds && !refs.agentIds.includes(String(c.agent_id))) add('UNKNOWN_AGENT', `Agent node "${n.data.label}" references an unknown agent`, n.id);
    }
    if (n.type === 'tool') {
      if (!c.tool_id) add('MISSING_CONFIG', `Tool node "${n.data.label}" needs a tool`, n.id);
      else if (refs?.toolIds && !refs.toolIds.includes(String(c.tool_id))) add('UNKNOWN_TOOL', `Tool node "${n.data.label}" references an unknown tool`, n.id);
    }
    if (n.type === 'llm' && !String(c.prompt_template ?? '').trim()) add('MISSING_CONFIG', `LLM node "${n.data.label}" needs a prompt template`, n.id);
    if (n.type === 'rag' && !String(c.query_template ?? '').trim()) add('MISSING_CONFIG', `RAG node "${n.data.label}" needs a query template`, n.id);
    if (n.type === 'api' && (!c.url || !c.method)) add('MISSING_CONFIG', `API node "${n.data.label}" needs method and URL`, n.id);
  }
  if (starts.length === 1) {
    const seen = new Set<string>([starts[0].id]);
    const stack = [starts[0].id];
    while (stack.length) for (const e of out(stack.pop()!)) if (ids.has(e.target) && !seen.has(e.target)) {
      seen.add(e.target);
      stack.push(e.target);
    }
    for (const n of def.nodes) if (!seen.has(n.id)) add('UNREACHABLE', `"${n.data.label}" is not reachable from start`, n.id);
  }
  // cycle detection (DFS colouring)
  const color = new Map<string, number>();
  let cyclic = false;
  const visit = (id: string) => {
    color.set(id, 1);
    for (const e of out(id)) {
      const c = color.get(e.target) ?? 0;
      if (c === 1) cyclic = true;
      else if (c === 0 && ids.has(e.target)) visit(e.target);
    }
    color.set(id, 2);
  };
  for (const n of def.nodes) if (!color.get(n.id)) visit(n.id);
  if (cyclic) add('CYCLE', 'Workflow contains a cycle (loops are not supported yet)');
  return issues;
}
