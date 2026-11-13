# AgentForge tool sandbox image (agentforge-sandbox:1.0.1)
# Hardening is enforced at runtime by sandbox/executor/host.py:
#   --network none, --read-only, --tmpfs /tmp, --cap-drop ALL, --security-opt no-new-privileges,
#   --pids-limit, --memory, --cpus, --user 10001. The Docker socket is NEVER mounted.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Only allowlisted third-party packages (mirror SANDBOX_ALLOWED_PACKAGES).
COPY policies/requirements-sandbox.txt /tmp/requirements-sandbox.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.txt \
    && rm -f /tmp/requirements-sandbox.txt \
    && pip uninstall -y pip setuptools wheel || true

RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin sandbox

COPY executor/runner.py /opt/executor/runner.py
RUN chmod 0555 /opt/executor && chmod 0444 /opt/executor/runner.py

USER 10001:10001
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/opt/executor/runner.py"]
