# Vision-AI BlackRock Program Tracker

## Purpose

Operational tracker for executing the institutional blueprint in controlled phases with explicit ownership, deadlines, and evidence links.

## Program Rules

1. No phase can close without all exit criteria marked passed.
2. Every control item must include an evidence artifact link.
3. High-impact control changes require dual approval from Engineering and Risk owners.
4. Any temporary bypass must include expiration date and postmortem reference.

## Status Legend

- not_started
- in_progress
- blocked
- complete

## Phase 0 - Stabilize Control Baseline (0-14 days)

### Work Items

| ID    | Work Item                                         | Owner                 | Due        | Status      | Evidence | Notes                                        |
| ----- | ------------------------------------------------- | --------------------- | ---------- | ----------- | -------- | -------------------------------------------- |
| P0-01 | Trust-boundary architecture map                   | Security Architecture | YYYY-MM-DD | not_started | TBD      | Include data flows and external dependencies |
| P0-02 | Privileged endpoint inventory + criticality tiers | Platform Engineering  | YYYY-MM-DD | not_started | TBD      | Include admin/trading/control-plane routes   |
| P0-03 | AuthN/AuthZ sequence diagrams                     | Backend Engineering   | YYYY-MM-DD | not_started | TBD      | Login, MFA step-up, websocket auth           |
| P0-04 | Security test-to-control objective mapping        | QA + Security         | YYYY-MM-DD | not_started | TBD      | Map tests to control IDs                     |

### Exit Criteria

- complete inventory approved by Engineering and Risk
- 100% privileged endpoints mapped to assurance level

## Phase 1 - Identity and Session Hardening (15-45 days)

### Work Items

| ID    | Work Item                                    | Owner                | Due        | Status      | Evidence | Notes                                    |
| ----- | -------------------------------------------- | -------------------- | ---------- | ----------- | -------- | ---------------------------------------- |
| P1-01 | Cookie-only session model across HTTP + WS   | Backend + Frontend   | YYYY-MM-DD | in_progress | TBD      | Remove residual bearer assumptions       |
| P1-02 | MFA step-up coverage to all critical actions | Security Engineering | YYYY-MM-DD | in_progress | TBD      | Include UI prompt and header propagation |
| P1-03 | Auth audit event standardization             | Backend Engineering  | YYYY-MM-DD | in_progress | TBD      | Ensure request/session/user linkage      |
| P1-04 | Account risk controls (lockout/anomaly)      | Identity Engineering | YYYY-MM-DD | not_started | TBD      | Add detection and remediation flow       |

### Exit Criteria

- internal red-team auth campaign shows no critical findings
- 100% critical actions require required assurance level

## Phase 2 - Perimeter and Policy Enforcement (46-90 days)

### Work Items

| ID    | Work Item                                        | Owner             | Due        | Status      | Evidence | Notes                                        |
| ----- | ------------------------------------------------ | ----------------- | ---------- | ----------- | -------- | -------------------------------------------- |
| P2-01 | API gateway in front of all external ingress     | Platform Security | YYYY-MM-DD | not_started | TBD      | Include schema enforcement and rate controls |
| P2-02 | Policy-as-code authorization engine              | Security Platform | YYYY-MM-DD | not_started | TBD      | OPA/Rego with decision logs                  |
| P2-03 | Secrets vault migration + rotation               | SRE + Security    | YYYY-MM-DD | not_started | TBD      | Remove static secret exposure                |
| P2-04 | SIEM ingestion for auth/risk/execution telemetry | SecOps            | YYYY-MM-DD | not_started | TBD      | Alert routing and tuning                     |

### Exit Criteria

- all external API traffic traverses gateway controls
- no privileged route bypasses policy engine

## Phase 3 - Runtime Isolation and Resilience (91-150 days)

### Work Items

| ID    | Work Item                                    | Owner                   | Due        | Status      | Evidence | Notes                                       |
| ----- | -------------------------------------------- | ----------------------- | ---------- | ----------- | -------- | ------------------------------------------- |
| P3-01 | Service mesh mTLS and workload identity      | Platform Engineering    | YYYY-MM-DD | not_started | TBD      | Enforce strict east-west trust              |
| P3-02 | Network segmentation deny-by-default         | SRE                     | YYYY-MM-DD | not_started | TBD      | Validate no lateral movement                |
| P3-03 | Multi-region failover + DR playbooks         | SRE + Risk Ops          | YYYY-MM-DD | not_started | TBD      | Include RTO/RPO tests                       |
| P3-04 | Chaos suite for dependency failure scenarios | Reliability Engineering | YYYY-MM-DD | not_started | TBD      | Identity, market data, exchange API outages |

### Exit Criteria

- two consecutive resilience game-days meet SLOs
- incident response runbooks validated by on-call team

## Phase 4 - Governance and Assurance Maturity (151-210 days)

### Work Items

| ID    | Work Item                                          | Owner                 | Due        | Status      | Evidence | Notes                              |
| ----- | -------------------------------------------------- | --------------------- | ---------- | ----------- | -------- | ---------------------------------- |
| P4-01 | Model governance board + signed promotion workflow | Quant Platform + Risk | YYYY-MM-DD | not_started | TBD      | Promotion and rollback approvals   |
| P4-02 | End-to-end lineage proof generation                | Data Platform         | YYYY-MM-DD | not_started | TBD      | Data -> signal -> execution -> PnL |
| P4-03 | Compliance evidence pipeline mapping               | GRC                   | YYYY-MM-DD | not_started | TBD      | SOC2/ISO27001/NIST mapping         |
| P4-04 | Executive risk dashboard publication               | SecOps + Risk         | YYYY-MM-DD | not_started | TBD      | Quarterly review package           |

### Exit Criteria

- no unresolved high-severity assurance findings
- > =95% evidence coverage on critical controls

## Phase 5 - Continuous Excellence (211+ days)

### Work Items

| ID    | Work Item                       | Owner                  | Cadence | Status      | Evidence | Notes                            |
| ----- | ------------------------------- | ---------------------- | ------- | ----------- | -------- | -------------------------------- |
| P5-01 | Continuous threat model refresh | Security Architecture  | Monthly | not_started | TBD      | Update risk assumptions          |
| P5-02 | Detection tuning program        | SecOps                 | Monthly | not_started | TBD      | Track precision/recall trends    |
| P5-03 | Architecture stress review      | Engineering Leadership | Annual  | not_started | TBD      | Validate future-state resilience |
| P5-04 | Institutional benchmark review  | CISO Office            | Annual  | not_started | TBD      | Compare peer controls and gaps   |

## Change Log

| Date       | Change                  | Author         |
| ---------- | ----------------------- | -------------- |
| 2026-03-27 | Initial tracker created | GitHub Copilot |
