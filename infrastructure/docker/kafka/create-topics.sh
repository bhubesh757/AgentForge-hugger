#!/usr/bin/env bash
# Idempotently create all AgentForge topics (API_CONTRACTS §14).
# Usage: KAFKA_BOOTSTRAP_SERVERS=kafka:9092 ./create-topics.sh
# Works inside the apache/kafka or bitnami/kafka image (kafka-topics.sh on PATH or under /opt/kafka/bin).
set -euo pipefail
BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"
PARTITIONS="${KAFKA_TOPIC_PARTITIONS:-3}"
RF="${KAFKA_REPLICATION_FACTOR:-1}"
KT="$(command -v kafka-topics.sh || echo /opt/kafka/bin/kafka-topics.sh)"

TOPICS=(
  agent.execution.requested workflow.execution.requested tool.execution.requested
  agent.execution.started agent.execution.completed agent.execution.failed
  workflow.execution.events tool.execution.events security.audit.events
  agent.execution.requested.dlq workflow.execution.requested.dlq tool.execution.requested.dlq
)

for i in $(seq 1 30); do
  "$KT" --bootstrap-server "$BOOTSTRAP" --list >/dev/null 2>&1 && break
  echo "waiting for kafka at $BOOTSTRAP ($i/30)"; sleep 2
done

for t in "${TOPICS[@]}"; do
  retention=604800000            # 7 days
  [[ "$t" == *.dlq ]] && retention=2592000000   # 30 days for DLQ
  "$KT" --bootstrap-server "$BOOTSTRAP" --create --if-not-exists --topic "$t" \
    --partitions "$PARTITIONS" --replication-factor "$RF" \
    --config retention.ms="$retention" --config cleanup.policy=delete
done
"$KT" --bootstrap-server "$BOOTSTRAP" --list
