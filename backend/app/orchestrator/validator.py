"""Pure structural validation of workflow definitions (API_CONTRACTS §8.1).

Org-scoped existence checks for referenced agents/tools need the DB and are done by the
API layer using :func:`referenced_resources`.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from pydantic import ValidationError

from app.orchestrator.safe_eval import UnsafeExpressionError, compile_expression
from app.orchestrator.schemas import CONFIG_MODELS, NODE_TYPES, ValidationIssue


def _issue(
    code: str, message: str, node_id: str | None = None, edge_id: str | None = None
) -> ValidationIssue:
    return ValidationIssue(node_id=node_id, edge_id=edge_id, code=code, message=message)


def validate_definition(definition: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(definition, dict):
        return [_issue("invalid_definition", "definition must be an object")]
    nodes_raw = definition.get("nodes")
    edges_raw = definition.get("edges", [])
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        return [_issue("invalid_definition", "'nodes' and 'edges' must be arrays")]

    nodes: dict[str, dict[str, Any]] = {}
    for idx, n in enumerate(nodes_raw):
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not n.get("id"):
            issues.append(_issue("invalid_node", f"node at index {idx} is missing a string 'id'"))
            continue
        nid = n["id"]
        if nid in nodes:
            issues.append(_issue("duplicate_node_id", f"duplicate node id '{nid}'", node_id=nid))
            continue
        ntype = n.get("type")
        if ntype not in NODE_TYPES:
            issues.append(_issue("invalid_node_type", f"unknown node type '{ntype}'", node_id=nid))
            continue
        nodes[nid] = n
        data = n.get("data") or {}
        config = data.get("config") if isinstance(data, dict) else None
        config = config if isinstance(config, dict) else {}
        try:
            CONFIG_MODELS[ntype].model_validate(config)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "config"
                issues.append(_issue("invalid_config", f"{ntype} config '{loc}': {err['msg']}", node_id=nid))
        if (
            ntype == "condition"
            and isinstance(config.get("expression"), str)
            and config["expression"].strip()
        ):
            try:
                compile_expression(config["expression"])
            except UnsafeExpressionError as exc:
                issues.append(_issue("invalid_expression", str(exc), node_id=nid))

    starts = [nid for nid, n in nodes.items() if n["type"] == "start"]
    ends = [nid for nid, n in nodes.items() if n["type"] == "end"]
    if len(starts) != 1:
        issues.append(
            _issue("start_count", f"workflow must have exactly one start node (found {len(starts)})")
        )
    if not ends:
        issues.append(_issue("missing_end", "workflow must have at least one end node"))

    adj: dict[str, list[str]] = defaultdict(list)
    out_handles: dict[str, list[str | None]] = defaultdict(list)
    seen_edges: set[str] = set()
    for idx, e in enumerate(edges_raw):
        if not isinstance(e, dict) or not isinstance(e.get("id"), str):
            issues.append(_issue("invalid_edge", f"edge at index {idx} is missing a string 'id'"))
            continue
        eid = e["id"]
        if eid in seen_edges:
            issues.append(_issue("duplicate_edge_id", f"duplicate edge id '{eid}'", edge_id=eid))
            continue
        seen_edges.add(eid)
        src, tgt = e.get("source"), e.get("target")
        bad = False
        for label, ref in (("source", src), ("target", tgt)):
            if ref not in nodes:
                issues.append(_issue("dangling_edge", f"edge {label} '{ref}' does not exist", edge_id=eid))
                bad = True
        if bad:
            continue
        if src == tgt:
            issues.append(_issue("self_loop", "edge connects a node to itself", node_id=src, edge_id=eid))
            continue
        if nodes[src]["type"] == "end":
            issues.append(
                _issue("end_has_outgoing", "end node cannot have outgoing edges", node_id=src, edge_id=eid)
            )
        if nodes[tgt]["type"] == "start":
            issues.append(
                _issue(
                    "start_has_incoming", "start node cannot have incoming edges", node_id=tgt, edge_id=eid
                )
            )
        handle = e.get("source_handle")
        if nodes[src]["type"] == "condition" and handle not in ("true", "false"):
            issues.append(
                _issue(
                    "condition_handle",
                    "condition edges must use source_handle 'true' or 'false'",
                    node_id=src,
                    edge_id=eid,
                )
            )
        adj[src].append(tgt)
        out_handles[src].append(handle)

    for nid, n in nodes.items():
        if n["type"] != "end" and not adj.get(nid):
            issues.append(
                _issue("no_outgoing_edge", "non-end node must have at least one outgoing edge", node_id=nid)
            )
        if n["type"] == "condition":
            hs = out_handles.get(nid, [])
            if hs.count("true") != 1 or hs.count("false") != 1:
                issues.append(
                    _issue(
                        "condition_branches",
                        "condition node needs exactly one 'true' and one 'false' edge",
                        node_id=nid,
                    )
                )
        elif n["type"] != "end" and len(adj.get(nid, [])) > 1:
            issues.append(
                _issue(
                    "multiple_outgoing",
                    "only condition nodes may branch (parallel fan-out is not supported)",
                    node_id=nid,
                )
            )

    if len(starts) == 1:
        reachable = {starts[0]}
        queue = deque([starts[0]])
        while queue:
            for nxt in adj.get(queue.popleft(), []):
                if nxt not in reachable:
                    reachable.add(nxt)
                    queue.append(nxt)
        for nid in nodes:
            if nid not in reachable:
                issues.append(_issue("unreachable_node", "node is not reachable from start", node_id=nid))

    cycle_node = _find_cycle(nodes.keys(), adj)
    if cycle_node is not None:
        issues.append(
            _issue(
                "cycle_detected", "workflow contains a cycle (loops are not supported)", node_id=cycle_node
            )
        )
    return issues


def _find_cycle(node_ids, adj: dict[str, list[str]]) -> str | None:
    """Iterative 3-colour DFS; returns a node on a cycle or None."""
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(node_ids, white)
    for root in list(color):
        if color[root] != white:
            continue
        stack = [(root, iter(adj.get(root, [])))]
        color[root] = grey
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = black
                stack.pop()
            elif color.get(nxt, black) == grey:
                return nxt
            elif color.get(nxt) == white:
                color[nxt] = grey
                stack.append((nxt, iter(adj.get(nxt, []))))
    return None


def referenced_resources(definition: dict) -> dict[str, set[str]]:
    """Return ``{"agents": {...ids}, "tools": {...ids}}`` for org-scoped existence checks."""
    out: dict[str, set[str]] = {"agents": set(), "tools": set()}
    for n in definition.get("nodes", []) if isinstance(definition, dict) else []:
        if not isinstance(n, dict):
            continue
        cfg = ((n.get("data") or {}).get("config") or {}) if isinstance(n.get("data"), dict) else {}
        if n.get("type") == "agent" and cfg.get("agent_id"):
            out["agents"].add(str(cfg["agent_id"]))
        elif n.get("type") == "tool" and cfg.get("tool_id"):
            out["tools"].add(str(cfg["tool_id"]))
    return out
