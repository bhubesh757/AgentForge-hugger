"""Host-side sandbox launcher used by the tool-worker (Docker SDK).

Every tool run gets a fresh, hardened, ephemeral container. The Docker socket is never mounted
into the sandbox; only the tool-worker talks to the daemon.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any

from sandbox.policies.static_checks import check_tool_code

RESULT_MARKER = "__AGENTFORGE_RESULT__"
MAX_PAYLOAD_BYTES = 512 * 1024
SANDBOX_UID = "10001:10001"


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxSettings:
    image: str = "agentforge-sandbox:1.0.1"
    timeout_seconds: float = 30.0
    memory_mb: int = 256
    cpus: float = 0.5
    network: str = "none"
    pids_limit: int = 64
    allowed_packages: str = "requests,httpx,pydantic,python-dateutil"

    @classmethod
    def from_env(cls) -> SandboxSettings:
        e = os.environ
        return cls(
            image=e.get("SANDBOX_IMAGE", cls.image),
            timeout_seconds=float(e.get("SANDBOX_TIMEOUT_SECONDS", cls.timeout_seconds)),
            memory_mb=int(e.get("SANDBOX_MEMORY_MB", cls.memory_mb)),
            cpus=float(e.get("SANDBOX_CPUS", cls.cpus)),
            network=e.get("SANDBOX_NETWORK", cls.network) or "none",
            pids_limit=int(e.get("SANDBOX_PIDS_LIMIT", cls.pids_limit)),
            allowed_packages=e.get("SANDBOX_ALLOWED_PACKAGES", cls.allowed_packages),
        )


def build_container_config(settings: SandboxSettings, payload_b64: str) -> dict[str, Any]:
    """kwargs for ``docker.containers.create`` — the single place where isolation flags live."""
    if settings.network in ("host",) or settings.network.startswith("container:"):
        raise SandboxError(f"SANDBOX_NETWORK={settings.network} is not permitted")
    return {
        "image": settings.image,
        "environment": {"AGENTFORGE_PAYLOAD": payload_b64, "PYTHONDONTWRITEBYTECODE": "1"},
        "user": SANDBOX_UID,
        "network_mode": settings.network,
        "mem_limit": f"{settings.memory_mb}m",
        "memswap_limit": f"{settings.memory_mb}m",
        "nano_cpus": int(settings.cpus * 1_000_000_000),
        "pids_limit": settings.pids_limit,
        "read_only": True,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=16m"},  # noqa: S108 - container-internal tmpfs
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "privileged": False,
        "volumes": {},  # never mount anything (esp. /var/run/docker.sock)
        "ipc_mode": "none",
        "detach": True,
        "stdin_open": False,
        "tty": False,
        "labels": {"agentforge.sandbox": "1"},
    }


def parse_output(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_MARKER):
            return json.loads(line[len(RESULT_MARKER):])
    return {"ok": False, "error": "sandbox produced no result", "error_type": "NoResult"}


class SandboxRunner:
    def __init__(self, settings: SandboxSettings | None = None, client: Any = None):
        self.settings = settings or SandboxSettings.from_env()
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import docker  # worker-only dependency (workers/requirements.txt)

            self._client = docker.from_env()
        return self._client

    def run(self, code: str, tool_input: Any) -> dict[str, Any]:
        """Blocking; call via ``asyncio.to_thread``. Returns {ok, output|error, ...}."""
        problems = check_tool_code(code, self.settings.allowed_packages)
        if problems:
            return {"ok": False, "error": "; ".join(problems), "error_type": "PolicyViolation"}
        raw = json.dumps({"code": code, "input": tool_input}, default=str).encode("utf-8")
        if len(raw) > MAX_PAYLOAD_BYTES:
            return {"ok": False, "error": "tool payload exceeds 512KB", "error_type": "PayloadTooLarge"}
        cfg = build_container_config(self.settings, base64.b64encode(raw).decode("ascii"))
        container = self.client.containers.create(**cfg)
        try:
            container.start()
            try:
                status = container.wait(timeout=self.settings.timeout_seconds)
            except Exception:  # requests ReadTimeout / ConnectionError → treat as timeout
                try:
                    container.kill()
                except Exception:  # noqa: BLE001, S110
                    pass
                return {"ok": False, "error": f"tool timed out after {self.settings.timeout_seconds:g}s",
                        "error_type": "Timeout"}
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", "replace")
            result = parse_output(stdout)
            if status.get("StatusCode") == 137 and not result.get("ok"):
                result = {"ok": False, "error": "tool killed (memory limit?)", "error_type": "Killed"}
            return result
        finally:
            try:
                container.remove(force=True)
            except Exception:  # noqa: BLE001, S110
                pass
