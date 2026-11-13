import { describe, expect, it } from 'vitest';
import { emptyDefinition, fromDefinition, nextNodeId, toDefinition } from '@/features/workflow/serialize';
import { validateDefinition } from '@/features/workflow/validate';
import type { WorkflowDefinition } from '@/types/api';

const codes = (d: WorkflowDefinition) => validateDefinition(d).map((i) => i.code);
const branching = (): WorkflowDefinition => ({
  schema_version: '1.0',
  nodes: [
    { id: 'start-1', type: 'start', position: { x: 0, y: 0 }, data: { label: 'Start', config: {} } },
    { id: 'condition-1', type: 'condition', position: { x: 100, y: 0 }, data: { label: 'If', config: { expression: 'True' } } },
    { id: 'end-1', type: 'end', position: { x: 200, y: 0 }, data: { label: 'A', config: {} } },
    { id: 'end-2', type: 'end', position: { x: 200, y: 100 }, data: { label: 'B', config: {} } },
  ],
  edges: [
    { id: 'e1', source: 'start-1', target: 'condition-1' },
    { id: 'e2', source: 'condition-1', target: 'end-1', source_handle: 'true' },
    { id: 'e3', source: 'condition-1', target: 'end-2', source_handle: 'false' },
  ],
  viewport: { x: 0, y: 0, zoom: 1 },
});

describe('workflow serializer', () => {
  it('round-trips a definition including condition handles', () => {
    const def = branching();
    const g = fromDefinition(def);
    expect(g.edges.find((e) => e.id === 'e2')?.sourceHandle).toBe('true');
    expect(toDefinition(g.nodes, g.edges, g.viewport)).toEqual(def);
  });
  it('strips UI-only fields and rounds positions', () => {
    const g = fromDefinition(emptyDefinition());
    g.nodes[0] = { ...g.nodes[0], position: { x: 1.6, y: 2.2 }, selected: true, data: { ...g.nodes[0].data, status: 'running' } };
    const out = toDefinition(g.nodes, g.edges);
    expect(out.nodes[0]).toEqual({ id: 'start-1', type: 'start', position: { x: 2, y: 2 }, data: { label: 'Start', config: {} } });
    expect(out.edges[0]).not.toHaveProperty('source_handle');
  });
  it('generates unique node ids', () => {
    expect(nextNodeId('agent', [{ id: 'agent-1' }, { id: 'agent-2' }])).toBe('agent-3');
  });
  it('handles null definition', () => expect(fromDefinition(null).nodes).toEqual([]));
});

describe('workflow validator', () => {
  it('accepts the empty start→end definition and valid branching', () => {
    expect(codes(emptyDefinition())).toEqual([]);
    expect(codes(branching())).toEqual([]);
  });
  it('requires exactly one start and an end', () => {
    const d = emptyDefinition();
    d.nodes = d.nodes.filter((n) => n.type !== 'start');
    d.edges = [];
    expect(codes(d)).toContain('START_COUNT');
    const e = emptyDefinition();
    e.nodes = e.nodes.filter((n) => n.type !== 'end');
    expect(codes(e)).toEqual(expect.arrayContaining(['NO_END', 'DANGLING_EDGE']));
  });
  it('requires both condition branches', () => {
    const d = branching();
    d.edges = d.edges.filter((e) => e.id !== 'e3');
    expect(codes(d)).toEqual(expect.arrayContaining(['CONDITION_BRANCHES', 'UNREACHABLE']));
  });
  it('detects cycles, fan-out and missing config', () => {
    const d = branching();
    d.nodes.push({ id: 'agent-1', type: 'agent', position: { x: 0, y: 0 }, data: { label: 'Ag', config: { agent_id: '' } } });
    d.edges.push({ id: 'e4', source: 'start-1', target: 'agent-1' }, { id: 'e5', source: 'agent-1', target: 'condition-1' });
    const c = codes(d);
    expect(c).toEqual(expect.arrayContaining(['FANOUT', 'MISSING_CONFIG']));
    const cyc = branching();
    cyc.edges[1] = { id: 'e2', source: 'condition-1', target: 'start-1', source_handle: 'true' };
    expect(codes(cyc)).toContain('CYCLE');
  });
  it('flags unknown agent references when refs are given', () => {
    const d = emptyDefinition();
    d.nodes.push({ id: 'agent-1', type: 'agent', position: { x: 0, y: 0 }, data: { label: 'Ag', config: { agent_id: 'x' } } });
    d.edges = [{ id: 'a', source: 'start-1', target: 'agent-1' }, { id: 'b', source: 'agent-1', target: 'end-1' }];
    expect(validateDefinition(d, { agentIds: ['y'] }).map((i) => i.code)).toEqual(['UNKNOWN_AGENT']);
  });
});
