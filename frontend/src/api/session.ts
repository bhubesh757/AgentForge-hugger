import { storage } from '@/lib/storage';

const REFRESH_KEY = 'agentforge.refresh_token';
const ORG_KEY = 'agentforge.org_id';
let accessToken: string | null = null;
type Listener = () => void;
const logoutListeners = new Set<Listener>();

export const session = {
  getAccess: () => accessToken,
  getRefresh: () => storage.get(REFRESH_KEY),
  setTokens(access: string, refresh: string) {
    accessToken = access;
    storage.set(REFRESH_KEY, refresh);
  },
  clear() {
    accessToken = null;
    storage.remove(REFRESH_KEY);
  },
  getOrg: () => storage.get(ORG_KEY),
  setOrg: (id: string | null) => (id ? storage.set(ORG_KEY, id) : storage.remove(ORG_KEY)),
  onLogout(fn: Listener) {
    logoutListeners.add(fn);
    return () => logoutListeners.delete(fn);
  },
  emitLogout() {
    logoutListeners.forEach((fn) => fn());
  },
};
