import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Credentials, Orgs, Providers } from '@/api/endpoints';
import { api } from '@/api/client';
import { useAuth } from '@/state/auth';
import { Badge, ErrorState, Field, Modal, PageHeader, QueryState } from '@/components/ui';
import { fmtDate } from '@/lib/format';
import { PERMISSIONS, RBAC, ROLES } from '@/lib/rbac';
import { getTheme, setTheme, type Theme } from '@/lib/theme';
import { API_BASE_URL, API_VERSION, DEMO_MODE, ROUTER_MODE, UI_VERSION } from '@/config';
import type { ConnectProvider, CredentialKind, Role } from '@/types/api';

const Notice = ({ msg }: { msg: string | null }) => (msg ? <p role="status" className="mb-3 rounded-md bg-sky-50 p-2 text-sm text-sky-800 dark:bg-sky-950/40 dark:text-sky-300">{msg}</p> : null);

export function CredentialsPage() {
  const { can } = useAuth();
  const w = can('llm.manage');
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['credentials'], queryFn: Credentials.list });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: '', kind: 'api_key' as CredentialKind, value: '', description: '' });
  const [msg, setMsg] = useState<string | null>(null);
  const inv = () => qc.invalidateQueries({ queryKey: ['credentials'] });
  const create = useMutation({ mutationFn: () => Credentials.create(f), onSuccess: () => (inv(), setOpen(false), setF({ ...f, name: '', value: '', description: '' })) });
  const rotate = useMutation({ mutationFn: (id: string) => { const v = window.prompt('New secret value'); return v ? Credentials.rotate(id, v) : Promise.reject(new Error('Rotation cancelled')); }, onSuccess: () => (inv(), setMsg('Credential rotated.')) });
  const validate = useMutation({ mutationFn: Credentials.validate, onSuccess: (r) => setMsg(`${r.valid ? 'Valid' : 'Invalid'}: ${r.message}`) });
  const remove = useMutation({ mutationFn: (id: string) => (window.confirm('Delete this credential?') ? Credentials.remove(id) : Promise.resolve()), onSuccess: inv });
  const err = create.error ?? rotate.error ?? validate.error ?? remove.error;
  return (
    <>
      <PageHeader title="Credentials" subtitle="Encrypted secrets for tools and API nodes — values are never shown again" actions={w && <button className="btn-primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />New credential</button>} />
      <Notice msg={msg} />{err && <div className="mb-3"><ErrorState error={err} /></div>}
      <div className="card"><QueryState q={list} empty={list.data?.items.length === 0}>
        <table className="table"><thead><tr><th>Name</th><th>Kind</th><th>Secret</th><th>Rotated</th><th /></tr></thead><tbody>
          {list.data?.items.map((c) => (
            <tr key={c.id}><td>{c.name}<div className="text-xs text-slate-500">{c.description}</div></td><td>{c.kind}</td><td className="font-mono">••••{c.key_hint}</td><td>{fmtDate(c.rotated_at)}</td>
              <td className="space-x-1 whitespace-nowrap">{w && <>
                <button className="btn-ghost !py-0.5 text-xs" onClick={() => validate.mutate(c.id)}>Validate</button>
                <button className="btn-ghost !py-0.5 text-xs" onClick={() => rotate.mutate(c.id)}>Rotate</button>
                <button className="btn-danger !py-0.5 text-xs" onClick={() => remove.mutate(c.id)}>Delete</button></>}</td></tr>
          ))}
        </tbody></table>
      </QueryState></div>
      {open && (
        <Modal title="New credential" onClose={() => setOpen(false)}>
          <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), create.mutate())}>
            <Field label="Name"><input className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Kind"><select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as CredentialKind })}>{['api_key', 'bearer_token', 'basic_auth', 'generic'].map((k) => <option key={k}>{k}</option>)}</select></Field>
            <Field label="Secret value"><input className="input" type="password" autoComplete="new-password" required value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} /></Field>
            <Field label="Description"><input className="input" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
            <button className="btn-primary" disabled={create.isPending}>Save</button>
          </form>
        </Modal>
      )}
    </>
  );
}

const blankConn = { provider: 'gemini' as 'gemini' | 'azure_openai', name: '', api_key: '', endpoint: '', deployment_name: '', api_version: '2024-06-01', default_model: '' };

export function ProvidersPage() {
  const { can } = useAuth();
  const w = can('llm.manage');
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['providers'], queryFn: Providers.list });
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(blankConn);
  const [msg, setMsg] = useState<string | null>(null);
  const [models, setModels] = useState<{ id: string; list: { id: string; display_name: string }[] } | null>(null);
  const inv = () => (qc.invalidateQueries({ queryKey: ['providers'] }), qc.invalidateQueries({ queryKey: ['summary'] }));
  const connect = useMutation({
    mutationFn: () => {
      const base = { name: f.name || undefined, api_key: f.api_key, default_model: f.default_model || undefined };
      const body: ConnectProvider = f.provider === 'gemini' ? { provider: 'gemini', ...base } : { provider: 'azure_openai', ...base, endpoint: f.endpoint, deployment_name: f.deployment_name, api_version: f.api_version };
      return Providers.connect(body);
    },
    onSuccess: () => (inv(), setOpen(false), setF(blankConn), setMsg('Provider connected. Validate it, then activate.')),
  });
  const validate = useMutation({ mutationFn: Providers.validate, onSuccess: (r) => (inv(), setMsg(`${r.valid ? 'Valid' : 'Invalid'}: ${r.message}`)) });
  const loadModels = useMutation({ mutationFn: (id: string) => Providers.models(id).then((r) => ({ id, list: r.models })), onSuccess: setModels });
  const activate = useMutation({ mutationFn: ({ id, model }: { id: string; model?: string }) => Providers.activate(id, model), onSuccess: () => (inv(), setMsg('Provider activated as organization default.')) });
  const deactivate = useMutation({ mutationFn: Providers.deactivate, onSuccess: inv });
  const remove = useMutation({ mutationFn: (id: string) => (window.confirm('Delete this provider?') ? Providers.remove(id) : Promise.resolve()), onSuccess: inv });
  const err = connect.error ?? validate.error ?? loadModels.error ?? activate.error ?? deactivate.error ?? remove.error;
  return (
    <>
      <PageHeader title="LLM Providers" subtitle="Bring your own key — Google Gemini or Azure OpenAI. Keys are encrypted and never displayed." actions={w && <button className="btn-primary" onClick={() => setOpen(true)}><Plus className="h-4 w-4" />Connect provider</button>} />
      <Notice msg={msg} />{err && <div className="mb-3"><ErrorState error={err} /></div>}
      <div className="card"><QueryState q={list} empty={list.data?.items.length === 0}>
        <table className="table"><thead><tr><th>Name</th><th>Provider</th><th>Status</th><th>Key</th><th>Default model</th><th /></tr></thead><tbody>
          {list.data?.items.map((p) => (
            <tr key={p.id}><td>{p.name}{p.is_default && <span className="ml-1 text-xs text-emerald-500">(default)</span>}<div className="text-xs text-slate-500">validated {fmtDate(p.last_validated_at)}</div></td>
              <td>{p.provider}</td><td><Badge>{p.status}</Badge></td><td className="font-mono">••••{p.key_hint}</td><td>{p.default_model ?? '—'}</td>
              <td className="space-x-1 whitespace-nowrap">{w && <>
                <button className="btn-ghost !py-0.5 text-xs" onClick={() => validate.mutate(p.id)}>Validate</button>
                <button className="btn-ghost !py-0.5 text-xs" onClick={() => loadModels.mutate(p.id)}>Models</button>
                {p.status === 'active' ? <button className="btn-ghost !py-0.5 text-xs" onClick={() => deactivate.mutate(p.id)}>Deactivate</button>
                  : <button className="btn-primary !py-0.5 text-xs" onClick={() => activate.mutate({ id: p.id })}>Activate</button>}
                <button className="btn-danger !py-0.5 text-xs" onClick={() => remove.mutate(p.id)}>Delete</button></>}</td></tr>
          ))}
        </tbody></table>
      </QueryState></div>
      {models && (
        <Modal title="Available models" onClose={() => setModels(null)}>
          <ul className="space-y-1 text-sm">{models.list.map((m) => (
            <li key={m.id} className="flex items-center justify-between">{m.display_name} <code className="text-xs">{m.id}</code>
              {w && <button className="btn-ghost !py-0.5 text-xs" onClick={() => (activate.mutate({ id: models.id, model: m.id }), setModels(null))}>Activate with this model</button>}</li>
          ))}</ul>
        </Modal>
      )}
      {open && (
        <Modal title="Connect LLM provider" onClose={() => setOpen(false)}>
          <form className="space-y-3" onSubmit={(e) => (e.preventDefault(), connect.mutate())}>
            <Field label="Provider"><select className="input" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value as typeof f.provider })}><option value="gemini">Google Gemini</option><option value="azure_openai">Azure OpenAI</option></select></Field>
            <Field label="Display name"><input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="API key"><input className="input" type="password" autoComplete="off" required value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })} /></Field>
            {f.provider === 'azure_openai' && <>
              <Field label="Endpoint"><input className="input" type="url" required placeholder="https://my-resource.openai.azure.com" value={f.endpoint} onChange={(e) => setF({ ...f, endpoint: e.target.value })} /></Field>
              <Field label="Deployment name"><input className="input" required value={f.deployment_name} onChange={(e) => setF({ ...f, deployment_name: e.target.value })} /></Field>
              <Field label="API version"><input className="input" required value={f.api_version} onChange={(e) => setF({ ...f, api_version: e.target.value })} /></Field>
            </>}
            <Field label="Default model (optional)"><input className="input" placeholder={f.provider === 'gemini' ? 'gemini-1.5-flash' : 'gpt-4o-mini'} value={f.default_model} onChange={(e) => setF({ ...f, default_model: e.target.value })} /></Field>
            <button className="btn-primary" disabled={connect.isPending}>Connect</button>
          </form>
        </Modal>
      )}
    </>
  );
}

export function OrganizationsPage() {
  const { org, selectOrg, refreshMe } = useAuth();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ['orgs'], queryFn: Orgs.list });
  const [name, setName] = useState('');
  const create = useMutation({ mutationFn: () => Orgs.create({ name }), onSuccess: async () => (setName(''), qc.invalidateQueries({ queryKey: ['orgs'] }), await refreshMe()) });
  return (
    <>
      <PageHeader title="Organizations" subtitle="Switch between or create organizations" />
      <form className="card mb-4 flex gap-2" onSubmit={(e) => (e.preventDefault(), create.mutate())}>
        <input className="input max-w-sm" aria-label="Organization name" placeholder="New organization name" required value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn-primary" disabled={create.isPending}><Plus className="h-4 w-4" />Create</button>
      </form>
      {create.error && <ErrorState error={create.error} />}
      <div className="card"><QueryState q={list} empty={list.data?.items.length === 0}>
        <table className="table"><thead><tr><th>Name</th><th>Slug</th><th>Your role</th><th /></tr></thead><tbody>
          {list.data?.items.map((o) => (
            <tr key={o.id}><td>{o.name}</td><td className="font-mono text-xs">{o.slug}</td><td><Badge>{o.role}</Badge></td>
              <td>{org?.organization_id === o.id ? <span className="text-xs text-emerald-500">current</span> : <button className="btn-ghost !py-0.5 text-xs" onClick={() => selectOrg(o.id)}>Switch</button>}</td></tr>
          ))}
        </tbody></table>
      </QueryState></div>
    </>
  );
}

export function UsersPage() {
  const { org, can, me } = useAuth();
  const w = can('org.manage');
  const qc = useQueryClient();
  const id = org?.organization_id ?? '';
  const members = useQuery({ queryKey: ['members', id], queryFn: () => Orgs.members(id), enabled: !!id });
  const [f, setF] = useState<{ email: string; role: Role }>({ email: '', role: 'developer' });
  const add = useMutation({ mutationFn: () => Orgs.addMember(id, f), onSuccess: () => (setF({ ...f, email: '' }), qc.invalidateQueries({ queryKey: ['members', id] })) });
  const remove = useMutation({ mutationFn: (uid: string) => Orgs.removeMember(id, uid), onSuccess: () => qc.invalidateQueries({ queryKey: ['members', id] }) });
  return (
    <>
      <PageHeader title="Users & Roles" subtitle={`Members of ${org?.organization_name ?? 'this organization'}`} />
      {w && (
        <form className="card mb-4 flex flex-wrap gap-2" onSubmit={(e) => (e.preventDefault(), add.mutate())}>
          <input className="input max-w-sm" type="email" aria-label="Member email" placeholder="user@example.com (must be registered)" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          <select className="input max-w-[10rem]" aria-label="Role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
          <button className="btn-primary" disabled={add.isPending}>Add member</button>
        </form>
      )}
      {(add.error || remove.error) && <div className="mb-3"><ErrorState error={add.error ?? remove.error} /></div>}
      <div className="card mb-4"><QueryState q={members} empty={members.data?.items.length === 0}>
        <table className="table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th><th /></tr></thead><tbody>
          {members.data?.items.map((m) => (
            <tr key={m.user_id}><td>{m.full_name}</td><td>{m.email}</td><td><Badge>{m.role}</Badge></td><td>{fmtDate(m.joined_at)}</td>
              <td>{w && m.user_id !== me?.id && <button className="btn-danger !py-0.5 text-xs" onClick={() => window.confirm(`Remove ${m.email}?`) && remove.mutate(m.user_id)}>Remove</button>}</td></tr>
          ))}
        </tbody></table>
      </QueryState></div>
      <div className="card">
        <h2 className="mb-2 font-medium">RBAC matrix</h2>
        <table className="table" aria-label="RBAC matrix"><thead><tr><th>Permission</th>{ROLES.map((r) => <th key={r}>{r}</th>)}</tr></thead><tbody>
          {PERMISSIONS.map((p) => <tr key={p}><td className="font-mono text-xs">{p}</td>{ROLES.map((r) => <td key={r}>{RBAC[p].includes(r) ? '✓' : '—'}</td>)}</tr>)}
        </tbody></table>
      </div>
    </>
  );
}

export function SettingsPage() {
  const [theme, setT] = useState<Theme>(getTheme());
  const health = useQuery({ queryKey: ['health'], queryFn: () => api.get<{ status: string; version: string; api_version: string }>('/health').then((r) => r.data) });
  return (
    <>
      <PageHeader title="Settings" subtitle="Appearance and environment" />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card space-y-3">
          <h2 className="font-medium">Appearance</h2>
          <Field label="Theme"><select className="input" value={theme} onChange={(e) => { const t = e.target.value as Theme; setT(t); setTheme(t); }}><option value="dark">Dark</option><option value="light">Light</option><option value="system">System</option></select></Field>
        </div>
        <div className="card text-sm">
          <h2 className="mb-2 font-medium">Environment</h2>
          <dl className="grid grid-cols-[10rem_1fr] gap-y-1">
            <dt className="text-slate-500">UI version</dt><dd>{UI_VERSION}</dd>
            <dt className="text-slate-500">API base URL</dt><dd className="break-all font-mono text-xs">{API_BASE_URL}</dd>
            <dt className="text-slate-500">API version</dt><dd>{API_VERSION}</dd>
            <dt className="text-slate-500">Backend</dt><dd>{health.isLoading ? 'checking…' : health.data ? `${health.data.status} (v${health.data.version})` : 'unreachable'}</dd>
            <dt className="text-slate-500">Demo mode</dt><dd>{DEMO_MODE ? 'on — data lives in this browser only' : 'off'}</dd>
            <dt className="text-slate-500">Router</dt><dd>{ROUTER_MODE}</dd>
          </dl>
          <p className="mt-2 text-xs text-slate-500">API base and demo mode are set at build time via VITE_API_BASE_URL / VITE_DEMO_MODE.</p>
        </div>
      </div>
    </>
  );
}
