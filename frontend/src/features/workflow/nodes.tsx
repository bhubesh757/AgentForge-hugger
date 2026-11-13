import { Handle, Position, type NodeProps, type NodeTypes } from '@xyflow/react';
import type { NodeType } from '@/types/api';
import type { FlowNode } from './serialize';

export const NODE_META: Record<NodeType, { label: string; color: string }> = {
  start: { label: 'Start', color: 'border-emerald-500' },
  end: { label: 'End', color: 'border-slate-500' },
  agent: { label: 'Agent', color: 'border-violet-500' },
  tool: { label: 'Tool', color: 'border-amber-500' },
  llm: { label: 'LLM', color: 'border-sky-500' },
  rag: { label: 'RAG', color: 'border-teal-500' },
  api: { label: 'API', color: 'border-orange-500' },
  condition: { label: 'Condition', color: 'border-pink-500' },
};
const STATUS_BG: Record<string, string> = {
  running: 'bg-sky-100 dark:bg-sky-900/60 animate-pulse',
  succeeded: 'bg-emerald-100 dark:bg-emerald-900/60',
  failed: 'bg-rose-100 dark:bg-rose-900/60',
};

function Box({ type, data, selected }: NodeProps<FlowNode> & { type: NodeType }) {
  const m = NODE_META[type];
  return (
    <div data-testid={`node-${type}`} className={`min-w-[120px] rounded-md border-2 px-3 py-2 text-xs shadow-sm ${m.color} ${data.status ? STATUS_BG[data.status] : 'bg-white dark:bg-slate-900'} ${selected ? 'ring-2 ring-brand-500' : ''}`}>
      {type !== 'start' && <Handle type="target" position={Position.Left} />}
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{m.label}</div>
      <div className="font-medium text-slate-900 dark:text-slate-100">{data.label}</div>
      {type === 'condition' ? (
        <>
          <Handle id="true" type="source" position={Position.Right} style={{ top: '35%', background: '#10b981' }} />
          <Handle id="false" type="source" position={Position.Right} style={{ top: '75%', background: '#f43f5e' }} />
          <div className="absolute -right-8 top-[22%] text-[9px] text-emerald-500">true</div>
          <div className="absolute -right-8 top-[62%] text-[9px] text-rose-500">false</div>
        </>
      ) : type !== 'end' && <Handle type="source" position={Position.Right} />}
    </div>
  );
}

export const nodeTypes: NodeTypes = Object.fromEntries(
  (Object.keys(NODE_META) as NodeType[]).map((t) => [t, (p: NodeProps<FlowNode>) => <Box {...p} type={t} />]),
);
