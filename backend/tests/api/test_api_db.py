"""DB-backed API tests (skipped when the test Postgres is unavailable)."""

from tests.conftest import register

API = "/api/v1"
WF = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "s", "type": "start", "position": {"x": 0, "y": 0}, "data": {"label": "S", "config": {}}},
        {
            "id": "l",
            "type": "llm",
            "position": {"x": 1, "y": 0},
            "data": {"label": "L", "config": {"prompt_template": "{{input}}"}},
        },
        {"id": "e", "type": "end", "position": {"x": 2, "y": 0}, "data": {"label": "E", "config": {}}},
    ],
    "edges": [{"id": "e1", "source": "s", "target": "l"}, {"id": "e2", "source": "l", "target": "e"}],
    "viewport": {"x": 0, "y": 0, "zoom": 1},
}


async def test_auth_flow_refresh_rotation_and_reuse(client):
    u = await register(client, "alice@example.com")
    assert u["me"]["email"] == "alice@example.com"
    r = await client.post(
        f"{API}/auth/login", json={"email": "alice@example.com", "password": "S3cure-password!"}
    )
    assert r.status_code == 200
    old = r.json()["refresh_token"]
    r2 = await client.post(f"{API}/auth/refresh", json={"refresh_token": old})
    assert r2.status_code == 200 and r2.json()["refresh_token"] != old
    assert (await client.post(f"{API}/auth/refresh", json={"refresh_token": old})).status_code == 401
    # reuse detection revokes the rotated family too
    assert (
        await client.post(f"{API}/auth/refresh", json={"refresh_token": r2.json()["refresh_token"]})
    ).status_code == 401
    bad = await client.post(
        f"{API}/auth/login", json={"email": "alice@example.com", "password": "wrong-password"}
    )
    assert bad.status_code == 401


async def test_org_membership_rbac_and_cross_tenant(client):
    a = await register(client, "owner@example.com", "OrgA")
    b = await register(client, "other@example.com", "OrgB")
    v = await register(client, "viewer@example.com", None)
    org_a = a["headers"]["X-Organization-ID"]
    r = await client.post(
        f"{API}/organizations/{org_a}/members",
        headers=a["headers"],
        json={"email": "viewer@example.com", "role": "viewer"},
    )
    assert r.status_code == 201, r.text
    vh = {**v["headers"], "X-Organization-ID": org_a}
    assert (await client.get(f"{API}/agents", headers=vh)).status_code == 200
    denied = await client.post(f"{API}/agents", headers=vh, json={"name": "x"})
    assert denied.status_code == 403
    agent = (await client.post(f"{API}/agents", headers=a["headers"], json={"name": "A1"})).json()
    assert (await client.get(f"{API}/agents/{agent['id']}", headers=b["headers"])).status_code == 404
    assert (
        await client.get(f"{API}/agents", headers={**b["headers"], "X-Organization-ID": org_a})
    ).status_code == 403
    no_hdr = {"Authorization": a["headers"]["Authorization"]}
    assert (await client.get(f"{API}/agents", headers=no_hdr)).json()["error"][
        "code"
    ] == "ORG_HEADER_REQUIRED"


async def test_provider_connect_mock_key_never_echoed(client):
    a = await register(client, "llm@example.com")
    key = "mock-secret-key-123456"
    r = await client.post(
        f"{API}/llm/providers/connect", headers=a["headers"], json={"provider": "gemini", "api_key": key}
    )
    assert r.status_code == 201 and key not in r.text
    p = r.json()
    assert p["status"] == "valid" and p["key_hint"].endswith("3456")
    act = await client.post(f"{API}/llm/providers/{p['id']}/activate", headers=a["headers"], json={})
    assert act.json()["status"] == "active" and act.json()["is_default"]
    assert key not in (await client.get(f"{API}/llm/providers", headers=a["headers"])).text


async def test_tool_static_analysis_enforced(client):
    a = await register(client, "tool@example.com")
    bad = await client.post(
        f"{API}/tools",
        headers=a["headers"],
        json={"name": "bad", "source_code": "import os\ndef run(input):\n    return {}\n"},
    )
    assert bad.status_code == 422
    ok = await client.post(
        f"{API}/tools",
        headers=a["headers"],
        json={"name": "good", "source_code": "def run(input: dict) -> dict:\n    return input\n"},
    )
    assert ok.status_code == 201


async def test_workflow_crud_validate_and_execute(client):
    a = await register(client, "wf@example.com")
    h = a["headers"]
    w = (await client.post(f"{API}/workflows", headers=h, json={"name": "W", "definition": WF})).json()
    upd = await client.put(f"{API}/workflows/{w['id']}", headers=h, json={"description": "d"})
    assert upd.status_code == 200
    res = (await client.post(f"{API}/workflows/{w['id']}/validate", headers=h, json={})).json()
    assert res == {"valid": True, "issues": []}
    broken = {
        **WF,
        "nodes": [
            *WF["nodes"],
            {
                "id": "ag",
                "type": "agent",
                "position": {"x": 0, "y": 0},
                "data": {"label": "A", "config": {"agent_id": "00000000-0000-0000-0000-000000000000"}},
            },
        ],
    }
    bad = (
        await client.post(f"{API}/workflows/{w['id']}/validate", headers=h, json={"definition": broken})
    ).json()
    assert not bad["valid"]
    ex = await client.post(f"{API}/workflows/{w['id']}/execute", headers=h, json={"input": "hi"})
    assert ex.status_code == 202 and ex.json()["status"] == "queued" and ex.json()["kind"] == "workflow"
    events = (await client.get(f"{API}/executions/{ex.json()['id']}/events", headers=h)).json()["items"]
    assert events[0]["event_type"] == "execution.queued" and events[0]["sequence"] == 1
    cancel = await client.post(f"{API}/executions/{ex.json()['id']}/cancel", headers=h)
    assert cancel.json()["status"] == "cancelled" and cancel.json()["finished_at"]
    versions = (await client.get(f"{API}/workflows/{w['id']}/versions", headers=h)).json()
    assert versions["total"] == 1


async def test_agent_execute_and_chat(client):
    a = await register(client, "chat@example.com")
    h = a["headers"]
    agent = (
        await client.post(f"{API}/agents", headers=h, json={"name": "Bot", "config": {"instructions": "hi"}})
    ).json()
    ex = await client.post(f"{API}/agents/{agent['id']}/execute", headers=h, json={"input": "hello"})
    assert ex.status_code == 202 and ex.json()["kind"] == "agent"
    s = (
        await client.post(
            f"{API}/chat/sessions", headers=h, json={"target_type": "agent", "target_id": agent["id"]}
        )
    ).json()
    m = await client.post(f"{API}/chat/sessions/{s['id']}/messages", headers=h, json={"content": "hey"})
    assert m.status_code == 202
    assert m.json()["execution"]["input"] == {"session_id": s["id"], "message": "hey"}


async def test_ready_ok(client):
    r = await client.get("/ready")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"
