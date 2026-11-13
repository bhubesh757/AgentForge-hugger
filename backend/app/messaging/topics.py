"""Kafka topic names and consumer groups (API_CONTRACTS §14)."""

AGENT_EXECUTION_REQUESTED = "agent.execution.requested"
WORKFLOW_EXECUTION_REQUESTED = "workflow.execution.requested"
TOOL_EXECUTION_REQUESTED = "tool.execution.requested"
AGENT_EXECUTION_STARTED = "agent.execution.started"
AGENT_EXECUTION_COMPLETED = "agent.execution.completed"
AGENT_EXECUTION_FAILED = "agent.execution.failed"
WORKFLOW_EXECUTION_EVENTS = "workflow.execution.events"
TOOL_EXECUTION_EVENTS = "tool.execution.events"
SECURITY_AUDIT_EVENTS = "security.audit.events"

DLQ_SUFFIX = ".dlq"

REQUEST_TOPICS = (AGENT_EXECUTION_REQUESTED, WORKFLOW_EXECUTION_REQUESTED, TOOL_EXECUTION_REQUESTED)
ALL_TOPICS = (
    *REQUEST_TOPICS,
    AGENT_EXECUTION_STARTED,
    AGENT_EXECUTION_COMPLETED,
    AGENT_EXECUTION_FAILED,
    WORKFLOW_EXECUTION_EVENTS,
    TOOL_EXECUTION_EVENTS,
    SECURITY_AUDIT_EVENTS,
)
DLQ_TOPICS = tuple(t + DLQ_SUFFIX for t in REQUEST_TOPICS)

GROUP_AGENT_WORKER = "agentforge-agent-worker"
GROUP_WORKFLOW_WORKER = "agentforge-workflow-worker"
GROUP_TOOL_WORKER = "agentforge-tool-worker"


def dlq_topic(topic: str) -> str:
    return topic + DLQ_SUFFIX


def request_topic_for(kind: str, target_type: str | None = None) -> str:
    """Route an execution kind to its request topic."""
    if kind in ("agent", "agent_test"):
        return AGENT_EXECUTION_REQUESTED
    if kind == "workflow":
        return WORKFLOW_EXECUTION_REQUESTED
    if kind == "tool_test":
        return TOOL_EXECUTION_REQUESTED
    if kind == "chat":
        return WORKFLOW_EXECUTION_REQUESTED if target_type == "workflow" else AGENT_EXECUTION_REQUESTED
    raise ValueError(f"unknown execution kind {kind!r}")


def resource_type_for(kind: str, target_type: str | None = None) -> str:
    if kind in ("agent", "agent_test"):
        return "agent"
    if kind == "workflow":
        return "workflow"
    if kind == "tool_test":
        return "tool"
    return "workflow" if target_type == "workflow" else "agent"
