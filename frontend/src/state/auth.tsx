import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Auth } from '@/api/endpoints';
import { bootstrapSession } from '@/api/client';
import { session } from '@/api/session';
import { can, type Permission } from '@/lib/rbac';
import type { Me, Membership, Role } from '@/types/api';

interface AuthState {
  me: Me | null;
  loading: boolean;
  org: Membership | null;
  role: Role | null;
  login: (email: string, password: string) => Promise<void>;
  register: (b: { email: string; password: string; full_name: string; organization_name?: string }) => Promise<void>;
  logout: () => Promise<void>;
  selectOrg: (id: string) => void;
  refreshMe: () => Promise<void>;
  can: (p: Permission) => boolean;
}
const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [orgId, setOrgId] = useState<string | null>(session.getOrg());

  const loadMe = useCallback(async () => {
    const m = await Auth.me();
    setMe(m);
    setOrgId((cur) => {
      const valid = m.memberships.find((x) => x.organization_id === cur)?.organization_id ?? m.memberships[0]?.organization_id ?? null;
      session.setOrg(valid);
      return valid;
    });
  }, []);

  useEffect(() => {
    let alive = true;
    bootstrapSession()
      .then((ok) => (ok ? loadMe() : undefined))
      .catch(() => session.clear())
      .finally(() => alive && setLoading(false));
    const off = session.onLogout(() => {
      setMe(null);
      qc.clear();
    });
    return () => {
      alive = false;
      off();
    };
  }, [loadMe, qc]);

  const value = useMemo<AuthState>(() => {
    const org = me?.memberships.find((m) => m.organization_id === orgId) ?? null;
    return {
      me, loading, org, role: org?.role ?? null,
      login: async (email, password) => {
        const t = await Auth.login(email, password);
        session.setTokens(t.access_token, t.refresh_token);
        await loadMe();
      },
      register: async (b) => {
        const t = await Auth.register(b);
        session.setTokens(t.access_token, t.refresh_token);
        await loadMe();
      },
      logout: async () => {
        const rt = session.getRefresh();
        try {
          if (rt) await Auth.logout(rt);
        } catch {
          /* best effort */
        }
        session.clear();
        setMe(null);
        qc.clear();
      },
      selectOrg: (id) => {
        session.setOrg(id);
        setOrgId(id);
        qc.invalidateQueries();
      },
      refreshMe: loadMe,
      can: (p) => can(org?.role, p),
    };
  }, [me, loading, orgId, loadMe, qc]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth must be used inside AuthProvider');
  return v;
}
