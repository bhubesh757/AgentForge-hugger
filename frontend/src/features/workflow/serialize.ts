import type { Edge, Node, Viewport } from '@xyflow/react';
import type { NodeType, WorkflowDefinition, WorkflowEdge, WorkflowNode } from '@/types/api';

export type FlowNodeData = { label: string; config: Record<string, unknown>; status?: 'running' | 'succeeded' | 'failed' };
export type FlowNode = Node<FlowNodeData>;

export const DEFAULT_CONFIG: Record<NodeType, () => Record<string, unknown>> = {
  start: () => ({}),
  end: () => ({}),
  agent: () => ({ agent_id: '', agent_version: null, input_template: '{{input}}' }),
  tool: () => ({ tool_id: '', tool_version: null, input_mapping: {} }),
  llm: () => ({ provider_id: null, model: null, prompt_template: '{{input}}', temperature: 0.2 }),
  rag: () => ({ query_template: '{{input}}', top_k: 5 }),
  api: () => ({ method: 'GET', url: '', headers: {}, body_template: '', timeout_seconds: 30 }),
  condition: () => ({ expression: "state['last_output'].get('ok') == True" }),
};

/** React Flow graph → canonical definition JSON (contract §8.1). Strips UI-only fields. */
export function toDefinition(nodes: FlowNode[], edges: Edge[], viewport: Viewport = { x: 0, y: 0, zoom: 1 }): WorkflowDefinition {
  return {
    schema_version: '1.0',
    nodes: nodes.map(
      (n): WorkflowNode => ({
        id: n.id,
        type: n.type as NodeType,
        position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
        data: { label: n.data.label, config: { ...n.data.config } },
      }),
    ),
    edges: edges.map((e): WorkflowEdge => {
      const out: WorkflowEdge = { id: e.id, source: e.source, target: e.target };
      if (e.sourceHandle === 'true' || e.sourceHandle === 'false') out.source_handle = e.sourceHandle;
      return out;
    }),
    viewport: { x: Math.round(viewport.x), y: Math.round(viewport.y), zoom: Number(viewport.zoom.toFixed(3)) },
  };
}

/** Canonical definition → React Flow graph. */
export function fromDefinition(def: WorkflowDefinition | null | undefined): { nodes: FlowNode[]; edges: Edge[]; viewport: Viewport } {
  if (!def) return { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } };
  return {
    nodes: def.nodes.map((n) => ({ id: n.id, type: n.type, position: { ...n.position }, data: { label: n.data.label, config: { ...(n.data.config ?? {}) } } })),
    edges: def.edges.map((e) => ({
      id: e.id, source: e.source, target: e.target,
      ...(e.source_handle ? { sourceHandle: e.source_handle, label: e.source_handle } : {}),
    })),
    viewport: def.viewport ?? { x: 0, y: 0, zoom: 1 },
  };
}

export function emptyDefinition(): WorkflowDefinition {
  return {
    schema_version: '1.0',
    nodes: [
      { id: 'start-1', type: 'start', position: { x: 0, y: 100 }, data: { label: 'Start', config: {} } },
      { id: 'end-1', type: 'end', position: { x: 400, y: 100 }, data: { label: 'End', config: {} } },
    ],
    edges: [{ id: 'e-start-1-end-1', source: 'start-1', target: 'end-1' }],
    viewport: { x: 0, y: 0, zoom: 1 },
  };
}

export function nextNodeId(type: NodeType, nodes: { id: string }[]): string {
  let i = 1;
  while (nodes.some((n) => n.id === `${type}-${i}`)) i++;
  return `${type}-${i}`;
}
