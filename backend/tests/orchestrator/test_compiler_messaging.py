import json
import uuid
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.messaging.consumer import BaseConsumer
from app.messaging.kafka import EventEnvelope
from app.messaging.topics import dlq_topic, request_topic_for
from app.orchestrator.compiler import check_url_allowed, compile_workflow


class FakeCtx:
    execution_id = "e"
    organization_id = "o"

    def __init__(self, responses):
        self.events = []
        self.model = FakeListChatModel(responses=responses)

    async def emit(self, event_type, payload, node_id=None):
        self.events.append((event_type, node_id))

    async def get_chat_model(self, provider_id, model):
        return self.model

    async def is_cancelled(self):
        return False

    def allow_private_network(self):
        return False


def graph_def(expr):
    return {"nodes": [
        {"id": "start", "type": "start"},
        {"id": "llm", "type": "llm", "data": {"config": {"prompt_template": "classify {{input}}"}}},
        {"id": "cond", "type": "condition", "data": {"config": {"expression": expr}}},
        {"id": "hi", "type": "end", "data": {"config": {"output_key": "high"}}},
        {"id": "lo", "type": "end"}],
        "edges": [{"id": "1", "source": "start", "target": "llm"}, {"id": "2", "source": "llm", "target": "cond"},
                  {"id": "3", "source": "cond", "target": "hi", "source_handle": "true"},
                  {"id": "4", "source": "cond", "target": "lo", "source_handle": "false"}]}


@pytest.mark.parametrize("severity,branch", [("high", "hi"), ("low", "lo")])
async def test_compiled_graph_end_to_end(severity, branch):
    ctx = FakeCtx([json.dumps({"severity": severity})])
    g = compile_workflow(graph_def("state['last_output'].get('severity') == 'high'"), ctx)
    out = await g.ainvoke({"input": "disk full", "outputs": {}, "trace": []})
    assert out["trace"] == ["start", "llm", "cond", branch]
    assert out["outputs"]["llm"] == {"severity": severity}
    if branch == "hi":
        assert out["last_output"] == {"high": {"severity": severity}}
    types = [e[0] for e in ctx.events]
    assert types.count("node.started") == 4 and types.count("node.completed") == 4
    assert "llm.token" in types


def test_ssrf_block():
    for url in ("http://127.0.0.1/x", "http://169.254.169.254/latest", "file:///etc/passwd", "http://10.0.0.1"):
        with pytest.raises(ValueError):
            check_url_allowed(url, allow_private=False)
    check_url_allowed("http://127.0.0.1/x", allow_private=True)


def env_dict(**kw):
    base = dict(event_type="agent.execution.requested", organization_id=str(uuid.uuid4()),
                execution_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()), resource_type="agent",
                resource_id=str(uuid.uuid4()), resource_version=1, kind="agent")
    base.update(kw)
    return base


def test_envelope_roundtrip_and_validation():
    env = EventEnvelope.model_validate(env_dict())
    again = EventEnvelope.from_bytes(env.to_bytes())
    assert again == env and env.key == str(env.execution_id).encode()
    for bad in (dict(kind="nope"), dict(resource_type="x"), dict(schema_version="2.0"), dict(extra=1),
                dict(execution_id="not-a-uuid"), dict(attempt=0)):
        with pytest.raises(ValueError):
            EventEnvelope.model_validate(env_dict(**bad))
    assert request_topic_for("chat", "workflow") == "workflow.execution.requested"
    assert request_topic_for("tool_test") == "tool.execution.requested"


class FakeRedis:
    def __init__(self):
        self.d = {}

    async def exists(self, k):
        return int(k in self.d)

    async def set(self, k, v, ex=None):
        self.d[k] = v


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def send_and_wait(self, topic, value=None, key=None):
        self.sent.append((topic, value))


def make_consumer(handler):
    sleeps = []

    async def sleep(s):
        sleeps.append(s)

    c = BaseConsumer(["agent.execution.requested"], "g", handler, consumer=object(), producer=FakeProducer(),
                     redis=FakeRedis(), sleep=sleep)
    return c, sleeps


def msg(value):
    return SimpleNamespace(topic="agent.execution.requested", value=value, key=b"k")


async def test_consumer_retry_then_dlq():
    calls = []

    async def handler(env):
        calls.append(env.attempt)
        raise RuntimeError("boom")

    c, sleeps = make_consumer(handler)
    raw = EventEnvelope.model_validate(env_dict()).to_bytes()
    assert await c.process_message(msg(raw)) == "dlq"
    assert calls == [1, 2, 3, 4] and sleeps == [1.0, 4.0, 16.0]
    topic, body = c._producer.sent[0]
    assert topic == dlq_topic("agent.execution.requested") and "boom" in json.loads(body)["error"]
    assert await c.process_message(msg(raw)) == "skipped"  # idempotent after DLQ


async def test_consumer_success_after_retry_and_idempotency():
    calls = []

    async def handler(env):
        calls.append(env.attempt)
        if len(calls) == 1:
            raise RuntimeError("transient")

    c, sleeps = make_consumer(handler)
    raw = EventEnvelope.model_validate(env_dict()).to_bytes()
    assert await c.process_message(msg(raw)) == "processed"
    assert await c.process_message(msg(raw)) == "skipped"
    assert calls == [1, 2] and sleeps == [1.0] and c._producer.sent == []


async def test_consumer_poison_message_to_dlq():
    c, _ = make_consumer(None)
    assert await c.process_message(msg(b"{not json")) == "dlq"
