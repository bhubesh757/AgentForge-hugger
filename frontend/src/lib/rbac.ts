import type { Role } from '@/types/api';

export type Permission = 'org.manage' | 'llm.manage' | 'resource.write' | 'execution.run' | 'resource.read';

export const ROLES: Role[] = ['owner', 'admin', 'developer', 'operator', 'viewer'];
export const PERMISSIONS: Permission[] = ['org.manage', 'llm.manage', 'resource.write', 'execution.run', 'resource.read'];

/** Contract §2 RBAC matrix. */
export const RBAC: Record<Permission, Role[]> = {
  'org.manage': ['owner', 'admin'],
  'llm.manage': ['owner', 'admin'],
  'resource.write': ['owner', 'admin', 'developer'],
  'execution.run': ['owner', 'admin', 'developer', 'operator'],
  'resource.read': ['owner', 'admin', 'developer', 'operator', 'viewer'],
};

export function can(role: Role | null | undefined, perm: Permission): boolean {
  return !!role && RBAC[perm].includes(role);
}
