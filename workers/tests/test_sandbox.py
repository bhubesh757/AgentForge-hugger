import json
import subprocess
import sys
import base64
import os

import pytest

from sandbox.executor.host import SandboxRunner, SandboxSettings, build_container_config, parse_output
from sandbox.policies.static_checks import check_tool_code

GOOD = "import json\n\ndef run(input):\n    print('log line')\n    return {'echo': input}\n"
RUNNER = os.path.join(os.path.dirname(__file__), "..", "..", "sandbox", "executor", "runner.py")


def test_container_config_hardening():
    cfg = build_container_config(SandboxSettings(), "e30=")
    assert cfg["network_mode"] == "none" and cfg["read_only"] is True
    assert cfg["user"] == "10001:10001" and cfg["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in cfg["security_opt"] and cfg["privileged"] is False
    assert cfg["volumes"] == {} and "docker.sock" not in json.dumps(cfg)
    assert cfg["mem_limit"] == "256m" and cfg["nano_cpus"] == 500_000_000 and cfg["pids_limit"] == 64
    assert "/tmp" in cfg["tmpfs"]


def test_host_network_rejected():
    with pytest.raises(RuntimeError):
        build_container_config(SandboxSettings(network="host"), "")


@pytest.mark.parametrize("code", ["import os\ndef run(i): return 1", "import subprocess\ndef run(i): pass",
                                  "def run(i): return eval('1')", "def run(i): return ().__class__",
                                  "def other(i): pass", "def run(:"])
def test_static_checks_reject(code):
    assert check_tool_code(code)


def test_static_checks_accept():
    assert check_tool_code(GOOD) == []
    assert check_tool_code("import httpx\nfrom dateutil import parser\ndef run(i): return 1") == []


def test_policy_violation_short_circuits_docker():
    r = SandboxRunner(SandboxSettings(), client=object())
    assert r.run("import os\ndef run(i): return 1", {})["error_type"] == "PolicyViolation"


def _run_runner(code, inp):
    payload = base64.b64encode(json.dumps({"code": code, "input": inp}).encode()).decode()
    out = subprocess.run([sys.executable, "-I", RUNNER], capture_output=True, text=True, timeout=30,
                         env={"AGENTFORGE_PAYLOAD": payload}, check=False)
    return parse_output(out.stdout)


def test_runner_locally():
    assert _run_runner(GOOD, {"a": 1}) == {"ok": True, "output": {"echo": {"a": 1}}, "logs": "log line\n"}
    bad = _run_runner("def run(i):\n    raise ValueError('nope')", None)
    assert bad["ok"] is False and bad["error_type"] == "ValueError"
