import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '@/state/auth';
import { ErrorState, Field } from '@/components/ui';
import { DemoBanner } from '@/components/Layout';
import { DEMO_MODE, UI_VERSION } from '@/config';
import { DEMO_USER } from '@/api/mock/db';

export default function Login({ mode }: { mode: 'login' | 'register' }) {
  const auth = useAuth();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const [f, setF] = useState({ email: DEMO_MODE ? DEMO_USER.email : '', password: DEMO_MODE ? DEMO_USER.password : '', full_name: '', organization_name: '' });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (auth.me) return <Navigate to={loc.state?.from ?? '/'} replace />;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      if (mode === 'login') await auth.login(f.email, f.password);
      else await auth.register({ email: f.email, password: f.password, full_name: f.full_name, organization_name: f.organization_name || undefined });
      nav(loc.state?.from ?? '/', { replace: true });
    } catch (x) {
      setErr(x);
    } finally {
      setBusy(false);
    }
  };
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="min-h-screen">
      <DemoBanner />
      <form onSubmit={submit} className="card mx-auto mt-20 w-full max-w-sm space-y-3">
        <h1 className="text-lg font-semibold">AgentForge AI — {mode === 'login' ? 'Sign in' : 'Create account'}</h1>
        {DEMO_MODE && mode === 'login' && <p className="text-xs text-slate-500">Demo credentials are prefilled: {DEMO_USER.email} / {DEMO_USER.password}</p>}
        {mode === 'register' && <Field label="Full name"><input className="input" required value={f.full_name} onChange={set('full_name')} /></Field>}
        <Field label="Email"><input className="input" type="email" required autoComplete="email" value={f.email} onChange={set('email')} /></Field>
        <Field label="Password"><input className="input" type="password" required minLength={mode === 'register' ? 10 : 1} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={f.password} onChange={set('password')} /></Field>
        {mode === 'register' && <Field label="Organization name (optional)"><input className="input" value={f.organization_name} onChange={set('organization_name')} /></Field>}
        {err != null && <ErrorState error={err} />}
        <button className="btn-primary w-full justify-center" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Register'}</button>
        <p className="text-center text-xs text-slate-500">
          {mode === 'login' ? <>No account? <Link className="text-brand-500" to="/register">Register</Link></> : <>Have an account? <Link className="text-brand-500" to="/login">Sign in</Link></>}
          {' · '}UI {UI_VERSION}
        </p>
      </form>
    </div>
  );
}
