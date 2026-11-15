# Site Reliability Engineering & Distributed System Resiliency

## 1. Site Reliability Principles: SLIs, SLOs & Error Budgets
Service Level Indicators (SLIs) are quantitative measurements of service behavior, typically availability, latency, throughput, or error rate. A Service Level Objective (SLO) specifies a target threshold for an SLI (e.g. 99.9% of requests served in under 150ms over 30 days). The Error Budget is the allowed unreliability: 100% minus the SLO (e.g. 0.1% = 43.8 minutes of downtime per month). Error budgets govern development velocity: when exhausted, product releases halt in favor of reliability engineering.

## 2. Distributed Consensus: The Raft Algorithm
Raft is a distributed consensus algorithm designed for understandability and operational resilience. Raft divides consensus into three subproblems: 1) Leader Election, where servers transition from Follower to Candidate and require a majority quorum of votes; 2) Log Replication, where the Leader accepts log entries from clients, replicates them across Followers, and commits once a majority acknowledges; 3) Safety, which ensures that if a server commits a log entry at a given index, no other server can commit a different entry for that index.

## 3. Fault Tolerance: Circuit Breakers, Bulkheads & Retries
Cascading failures occur when an outage in one downstream service exhausts thread pools and network connections across upstream callers. Circuit breakers prevent cascading failure by monitoring error rates: in Closed state requests flow normally; upon tripping an error threshold the breaker transitions to Open, immediately rejecting calls without invoking downstream systems; after a cooldown period it enters Half-Open to test recovery. Bulkheads isolate resources into dedicated execution pools to prevent one noisy neighbor from exhausting system-wide memory.

## 4. Incident Response & Automated Rollback Runbooks
Operational incident response follows a structured protocol: Detection, Triage, Containment, Mitigation, and Post-Mortem. Containment prioritizes restoring user SLOs over root-cause analysis: automated rollbacks revert recent deployments to the last known healthy revision using kubectl rollout undo deployment/<service>. Feature flags are toggled off. Post-mortem reviews adhere to blameless culture, identifying structural failure paths rather than human error.

## 5. Event Streaming, Change Data Capture (CDC) & Outbox Pattern
Microservices maintain data isolation by avoiding shared transactional databases. To achieve cross-service consistency without distributed two-phase commits, systems use the Transactional Outbox Pattern: business entities and domain events are written to the local database within the same atomic transaction. A Change Data Capture (CDC) process (such as Debezium reading Postgres write-ahead logs) captures outbox records and streams them to Kafka topics for asynchronous consumer ingestion.
