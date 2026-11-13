import copy

import pytest

from app.orchestrator.safe_eval import UnsafeExpressionError, evaluate_condition
from app.orchestrator.templates import render_template, render_value
from app.orchestrator.validator import referenced_resources, validate_definition

STATE = {"input": {"q": "hi"}, "last_output": {"severity": "high", "n": 3},
         "outputs": {"a": {"x": [1, 2]}}}

VALID = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "s", "type": "start", "data": {"config": {}}},
        {"id": "l", "type": "llm", "data": {"config": {"prompt_template": "{{input}}"}}},
        {"id": "c", "type": "condition", "data": {"config": {"expression": "state['last_output'] == 'x'"}}},
        {"id": "e1", "type": "end", "data": {"config": {}}},
        {"id": "e2", "type": "end", "data": {"config": {}}},
    ],
    "edges": [
        {"id": "1", "source": "s", "target": "l"},
        {"id": "2", "source": "l", "target": "c"},
        {"id": "3", "source": "c", "target": "e1", "source_handle": "true"},
        {"id": "4", "source": "c", "target": "e2", "source_handle": "false"},
    ],
}


def codes(d):
    return {i.code for i in validate_definition(d)}


def test_valid_definition():
    assert validate_definition(VALID) == []


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d["nodes"].pop(0), "start_count"),
    (lambda d: d["nodes"].append({"id": "s2", "type": "start"}), "start_count"),
    (lambda d: [d["nodes"].pop(), d["nodes"].pop(), d["edges"].pop(), d["edges"].pop()], "missing_end"),
    (lambda d: d["edges"].append({"id": "x", "source": "l", "target": "nope"}), "dangling_edge"),
    (lambda d: d["nodes"].append({"id": "orphan", "type": "end"}), "unreachable_node"),
    (lambda d: d["edges"].pop(1), "no_outgoing_edge"),
    (lambda d: d["edges"].pop(), "condition_branches"),
    (lambda d: d["edges"][2].update(source_handle=None), "condition_handle"),
    (lambda d: d["edges"].append({"id": "cy", "source": "l", "target": "s"}), "start_has_incoming"),
    (lambda d: d["nodes"][2]["data"]["config"].update(expression="__import__('os')"), "invalid_expression"),
    (lambda d: d["nodes"][1]["data"]["config"].pop("prompt_template"), "invalid_config"),
    (lambda d: d["nodes"].append({"id": "z", "type": "bogus"}), "invalid_node_type"),
    (lambda d: d["nodes"].append({"id": "s", "type": "end"}), "duplicate_node_id"),
])
def test_validation_rules(mutate, code):
    d = copy.deepcopy(VALID)
    mutate(d)
    assert code in codes(d)


def test_cycle_detection():
    d = copy.deepcopy(VALID)
    d["nodes"].insert(2, {"id": "l2", "type": "llm", "data": {"config": {"prompt_template": "x"}}})
    d["edges"][1] = {"id": "2", "source": "l", "target": "l2"}
    d["edges"].append({"id": "5", "source": "l2", "target": "l"})
    assert "cycle_detected" in codes(d)


def test_referenced_resources():
    d = {"nodes": [{"id": "a", "type": "agent", "data": {"config": {"agent_id": "A"}}},
                   {"id": "t", "type": "tool", "data": {"config": {"tool_id": "T"}}}]}
    assert referenced_resources(d) == {"agents": {"A"}, "tools": {"T"}}


@pytest.mark.parametrize("expr,expected", [
    ("state['last_output'].get('severity') == 'high'", True),
    ("state['last_output']['n'] >= 3 and not state['input']['q'] == 'no'", True),
    ("'hi' in [state['input']['q'], 'x']", True),
    ("state['last_output'].get('missing', 5) == 5 or False", True),
    ("state['outputs']['a']['x'][0] == 1", True),
    ("state['last_output']['n'] < -1", False),
    ("state.get('last_output') is None", False),
    ("'b' not in ('a', 'c')", True),
])
def test_safe_eval_accepts(expr, expected):
    assert evaluate_condition(expr, STATE) is expected


@pytest.mark.parametrize("expr", [
    "__import__('os').system('id')",
    "state.__class__.__mro__",
    "().__class__.__bases__[0].__subclasses__()",
    "open('/etc/passwd')",
    "eval('1')",
    "exec('x=1')",
    "lambda: 1",
    "[x for x in state]",
    "state['a'] + 1",
    "os.system('ls')",
    "state.keys()",
    "state.get(**{})",
    "f'{state}'",
    "state['a'][1:2]",
    "x := 1",
    "1 if state else 2",
    "",
    "a" * 2000,
    "b'bytes' == state",
])
def test_safe_eval_rejects(expr):
    with pytest.raises(UnsafeExpressionError):
        evaluate_condition(expr, STATE)


def test_templates():
    assert render_template("Q: {{input.q}} / {{ last_output.severity }}", STATE) == "Q: hi / high"
    assert render_template("{{outputs.a}}", STATE) == '{"x": [1, 2]}'
    assert render_template("{{outputs.a.x.1}}|{{unknown}}|{{outputs.zz}}", STATE) == "2||"
    assert render_value({"v": "{{outputs.a.x}}", "s": "n={{last_output.n}}"}, STATE) == {"v": [1, 2], "s": "n=3"}
