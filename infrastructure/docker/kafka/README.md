# Kafka (KRaft, single node) — dev/CI

Compose service `kafka` (profile `kafka`), image `apache/kafka:3.8.0` recommended. Suggested env (owned by DevOps in compose):

```
KAFKA_NODE_ID=1
KAFKA_PROCESS_ROLES=broker,controller
KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093
KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092
KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER
KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka:9093
KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1
KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1
KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1
KAFKA_AUTO_CREATE_TOPICS_ENABLE=false
```

Topics are created by `create-topics.sh` (one-shot `kafka-init` container or `docker compose exec kafka /scripts/create-topics.sh`).
Production: ≥3 brokers, RF=3, `min.insync.replicas=2`, SASL/TLS. See `docs/architecture/KAFKA_ARCHITECTURE.md`.
