import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Send } from 'lucide-react';
import { Agents, Chat, Workflows } from '@/api/endpoints';
import { useAuth } from '@/state/auth';
import { useExecutionStream } from '@/components/useExecutionStream';
import { Empty, ErrorState, Field, Modal, PageHeader, QueryState } from '@/components/ui';
import { fmtDate } from '@/lib/format';

function NewSession({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [type, setType] = useState<'agent' | 'workflow'>('agent');
  const [target, setTarget] = useState('');
  const [title, setTitle] = useState('');
  const agents = useQuery({ queryKey: ['agents'], queryFn: () => Agents.list() });
  const wfs = useQuery({ queryKey: ['workflows'], queryFn: () => Workflows.list() });
  const opts = type === 'agent' ? agents.data?.items : wfs.data?.items;
  const qc = useQueryClient();
  const create = useMutation({ mutationFn: () => Chat.create({ target_type: type, target_id: target, title: title || undefined }), onSuccess: (s) => (qc.invalidateQueries({ queryKey: ['chat-sessions'] }), onCreated(s.id)) });
  return (
    <Modal title="New chat session" onClose={onClose}>
      {create.error && <ErrorState error={create.error} />}
      <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), create.mutate())}>
        <Field label="Chat with"><select className="input" value={type} onChange={(e) => (setType(e.target.value as 'agent' | 'workflow'), setTarget(''))}><option value="agent">Agent</option><option value="workflow">Workflow</option></select></Field>
        <Field label={type === 'agent' ? 'Agent' : 'Workflow'}><select className="input" required value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Select…</option>{opts?.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>
        <Field label="Title (optional)"><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <button className="btn-primary" disabled={create.isPending || !target}>Start</button>
      </form>
    </Modal>
  );
}

function Conversation({ id }: { id: string }) {
  const qc = useQueryClient();
  const msgs = useQuery({ queryKey: ['chat-messages', id], queryFn: () => Chat.messages(id) });
  const [text, setText] = useState('');
  const [execId, setExecId] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const stream = useExecutionStream(execId);
  const end = useRef<HTMLDivElement>(null);
  const send = useMutation({ mutationFn: (c: string) => Chat.send(id, c), onSuccess: (r) => (setExecId(r.execution.id), setPending(r.user_message.content)) });
  const live = stream.events.filter((e) => e.event_type === 'llm.token').map((e) => String(e.payload.text ?? '')).join('');
  useEffect(() => {
    if (stream.done) { setExecId(null); setPending(null); qc.invalidateQueries({ queryKey: ['chat-messages', id] }); }
  }, [stream.done, id, qc]);
  useEffect(() => end.current?.scrollIntoView?.({ block: 'end' }), [msgs.data, live]);
  const busy = send.isPending || !!execId;
  return (
    <div className="flex h-[60vh] flex-col">
      <div className="flex-1 space-y-2 overflow-auto p-1" aria-live="polite">
        <QueryState q={msgs} empty={!msgs.data?.items.length && !pending}>
          {msgs.data?.items.map((m) => (
            <div key={m.id} className={`max-w-[80%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${m.role === 'user' ? 'ml-auto bg-brand-600 text-white' : 'bg-slate-100 dark:bg-slate-800'}`}>{m.content}</div>
          ))}
          {pending && <div className="ml-auto max-w-[80%] rounded-lg bg-brand-600 px-3 py-2 text-sm text-white">{pending}</div>}
          {execId && <div className="max-w-[80%] whitespace-pre-wrap rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">{live || '…'}</div>}
        </QueryState>
        <div ref={end} />
      </div>
      {(send.error || stream.error) && <ErrorState error={send.error ?? new Error(stream.error!)} />}
      <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send.mutate(text.trim()); setText(''); } }}>
        <input className="input" aria-label="Message" placeholder="Type a message…" value={text} onChange={(e) => setText(e.target.value)} disabled={busy} />
        <button className="btn-primary" disabled={busy || !text.trim()} aria-label="Send"><Send className="h-4 w-4" /></button>
      </form>
    </div>
  );
}

export default function ChatPage() {
  const { can } = useAuth();
  const sessions = useQuery({ queryKey: ['chat-sessions'], queryFn: Chat.sessions });
  const [sel, setSel] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader title="Chat" subtitle="Converse with agents and workflows" actions={can('execution.run') && <button className="btn-primary" onClick={() => setCreating(true)}><Plus className="h-4 w-4" />New session</button>} />
      <div className="grid gap-4 lg:grid-cols-4">
        <div className="card">
          <QueryState q={sessions} empty={sessions.data?.items.length === 0}>
            <ul className="space-y-1">
              {sessions.data?.items.map((s) => (
                <li key={s.id}><button className={`w-full rounded px-2 py-1 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800 ${sel === s.id ? 'bg-slate-100 dark:bg-slate-800' : ''}`} onClick={() => setSel(s.id)}>
                  {s.title}<div className="text-xs text-slate-500">{s.target_type} · {fmtDate(s.updated_at)}</div></button></li>
              ))}
            </ul>
          </QueryState>
        </div>
        <div className="card lg:col-span-3">{sel ? <Conversation key={sel} id={sel} /> : <Empty>Select or start a chat session.</Empty>}</div>
      </div>
      {creating && <NewSession onClose={() => setCreating(false)} onCreated={(id) => (setSel(id), setCreating(false))} />}
    </>
  );
}
