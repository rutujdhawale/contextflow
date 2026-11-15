# Distributed System Architecture & Incident Runbook

## Overview
This document specifies the core services, dependency topologies, and operational failure mitigations for the ContextFlow platform.

## Service Dependencies
- **API Gateway (Edge Router)**: Directs external client HTTPS requests to internal microservices. Routes all commerce traffic to `checkout-api`.
- **Checkout API (`checkout-api`)**: Orchestrates customer orders, cart verification, and payment processing.
  - Dependencies: Calls `auth-service` for bearer token validation and `payment-client` to dispatch charges to Stripe/Adyen.
  - Ownership: Maintained by the **Payments-Platform** engineering team (Lead: `@alex-payments`).
- **Inventory Service**: Manages stock counts with optimistic concurrency locking and PostgreSQL persistence.

## Known Incident History & Causal Paths
### Incident INC-1042: Checkout API Latency Spike (Sev-1)
- **Root Cause**: Deployment `deploy-8842` introduced commit `commit-771` in `payment-client.py`, which caused a connection leak during Stripe webhook retries.
- **Affected Endpoints**: `/v1/checkout/charge` and `/v1/orders/confirm`.
- **Mitigation Procedure**:
  1. Trigger immediate rollback to previous stable deployment `deploy-8841`.
  2. Follow the operational runbook at `runbook-checkout`: run `kubectl rollout undo deployment/checkout-api`.
  3. Precedent: Similar incident `INC-991` was mitigated in under 4 minutes using mitigation playbook `mit-77`.

## Database Schema & Integrity Constraints
- The transactional store relies on relation schemas with strict primary key constraints.
- Foreign keys between `Orders` and `Customers` are enforced at the database engine tier to prevent orphaned records.
- Eventual consistency is maintained via Kafka change-data-capture (CDC) topics.
