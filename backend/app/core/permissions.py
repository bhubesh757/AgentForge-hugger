"""RBAC matrix (API_CONTRACTS.md section 2). Seeded into roles/permissions tables by migration 0001."""

from __future__ import annotations

ORG_MANAGE = "org.manage"
LLM_MANAGE = "llm.manage"
RESOURCE_WRITE = "resource.write"
EXECUTION_RUN = "execution.run"
RESOURCE_READ = "resource.read"

PERMISSIONS: dict[str, str] = {
    ORG_MANAGE: "Update organization and manage members",
    LLM_MANAGE: "Connect/activate/delete LLM providers and credentials",
    RESOURCE_WRITE: "Create/update/generate/publish agents, tools, workflows",
    EXECUTION_RUN: "Execute/test/cancel and chat",
    RESOURCE_READ: "Read organization resources",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(PERMISSIONS),
    "admin": frozenset(PERMISSIONS),
    "developer": frozenset({RESOURCE_WRITE, EXECUTION_RUN, RESOURCE_READ}),
    "operator": frozenset({EXECUTION_RUN, RESOURCE_READ}),
    "viewer": frozenset({RESOURCE_READ}),
}
ROLES = tuple(ROLE_PERMISSIONS)
