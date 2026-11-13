"""DB-free tests: static analysis, guardrails, health, OpenAPI, auth rejection."""

from app.guardrails.service import apply_guardrails
from app.tools.static_analysis import analyze

GOOD = "import json\n\ndef run(input: dict) -> dict:\n    return {'n': len(json.dumps(input))}\n"


def test_static_analysis_accepts_safe_tool():
    assert analyze(GOOD, ["httpx"]).ok


def test_static_analysis_rejects_os_import():
    res = analyze("import os\n\ndef run(input):\n    return {}\n")
    assert not res.ok and any("os" in i for i in res.issues)


def test_static_analysis_rejects_eval_dunder_and_bad_requirement():
    res = analyze("def run(input):\n    return eval('1').__class__\n", ["numpy"])
    joined = " ".join(res.issues)
    assert "eval" in joined and "__class__" in joined and "numpy" in joined


def test_static_analysis_requires_run_and_valid_syntax():
    assert not analyze("def main(x):\n    return x\n").ok
    assert not analyze("def run(:\n").ok


def test_guardrails_redact_and_truncate():
    out = apply_guardrails("mail a@b.com or 123-45-6789", block_pii=True, max_output_chars=200)
    assert "a@b.com" not in out and "123-45-6789" not in out
    assert apply_guardrails("abcdef", max_output_chars=3) == "abc"


async def test_health_and_openapi(plain_client):
    for path in ("/health", "/api/v1/health"):
        r = await plain_client.get(path)
        assert r.status_code == 200 and r.json()["status"] == "ok"
        assert r.headers.get("x-request-id")
    spec = (await plain_client.get("/openapi.json")).json()
    for p in (
        "/api/v1/agents",
        "/api/v1/workflows/{workflow_id}/validate",
        "/api/v1/executions/{execution_id}/stream",
        "/api/v1/llm/providers/connect",
        "/api/v1/audit-logs",
        "/api/v1/monitoring/summary",
    ):
        assert p in spec["paths"], p
    assert (await plain_client.get("/metrics")).status_code == 200


async def test_requires_auth(plain_client):
    r = await plain_client.get("/api/v1/agents")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
