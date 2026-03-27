# Institutional Cybersecurity and Architecture Audit (2026-03-27)

## Scope

Repository-wide review of runtime security posture, auth/session controls, deployment config consistency, and operational resilience.

## Executive Summary

Vision-AI has strong progress on auth hardening (cookie sessions, MFA step-up hooks, strict production guardrails, and deployment config alignment). The top unresolved risk is secret hygiene in local environment files and missing advanced controls expected in institutional stacks.

## Findings by Severity

### Critical

1. Secret hygiene risk in local environment file.

- Impact: Real-looking provider and exchange credentials in `.env` can lead to account takeover, data abuse, and financial impact if leaked.
- Required action: Rotate all keys immediately and keep only placeholders in `.env` where possible.

### High

1. CSRF protections for cookie-backed state-changing routes are not explicitly enforced.

- Impact: Browser-authenticated users may be vulnerable to cross-site request attempts on sensitive POST routes.
- Required action: Add CSRF token middleware and enforce `X-CSRF-Token` validation for all state-changing endpoints.

2. Stateless JWT logout revocation is limited by token lifetime.

- Impact: Stolen token remains usable until expiry.
- Required action: Add JTI claim + revocation table (or short TTL + rotating refresh with revocation).

3. Public `/news` endpoint is unauthenticated.

- Impact: API quota abuse and endpoint reconnaissance risk.
- Required action: Add auth dependency or stricter endpoint-specific throttling.

### Medium

1. Missing dedicated security tests for CSRF/session replay/idempotency races.

- Required action: Add focused tests for CSRF rejection, replay rejection, and idempotency concurrency.

2. Limited policy-as-code enforcement for privileged route classes.

- Required action: Introduce centralized policy engine (OPA/Rego) for admin/live-trading actions.

## Hardening Changes Applied in This Pass

1. Render start command corrected to canonical API surface.
2. WebSocket query-token fallback now defaults to disabled in code.
3. Critical endpoint rate limits tightened (`/live-trading/*`, `/trading/*`, `/emergency/*`).
4. Frontend API proxy fails fast in production when backend URL env is missing.
5. Security regression tests expanded for strict critical route throttling.

## Institutional Target Architecture (BlackRock/Citadel-Style)

### Control Plane

1. Identity and trust

- SSO/IdP + phishing-resistant MFA for all operators.
- Device/session risk scoring and continuous re-auth for privileged actions.

2. Authorization

- Centralized policy decision point (PDP) with policy-as-code.
- Explicit action-level permissions for live trading, kill-switch, and model promotion.

3. Session lifecycle

- Short-lived access tokens + refresh rotation + revocation list.
- CSRF and anti-replay protections for browser clients.

### Trading Safety Plane

1. Deterministic pre-trade checks with signed policy snapshots.
2. Two-person rule for live enable, kill reset, and production model promotion.
3. Full order lifecycle audit with immutable retention.

### Detection and Response Plane

1. Unified telemetry to SIEM (auth, risk, orders, infra).
2. Alerting on anomalous admin actions and burst trading mutations.
3. Quarterly game days for identity outage, exchange outage, and replay attack drills.

### Delivery and Supply Chain Plane

1. Mandatory SAST/SCA/secrets scanning gates.
2. Signed artifacts and SBOM generation.
3. Environment policy conformance check before release.

## 30-Day Remediation Plan

1. Week 1

- Rotate all local/provider secrets and enforce placeholders in `.env`.
- Implement CSRF middleware for state-changing routes.

2. Week 2

- Add JWT revocation via JTI store and logout invalidation.
- Add endpoint-specific throttles for unauthenticated public data routes.

3. Week 3

- Add idempotency and replay/security regression test suites.
- Wire audit events to centralized sink.

4. Week 4

- Introduce policy-as-code pilot for privileged actions.
- Conduct tabletop + technical drill for compromise/rollback workflow.

## Exit Criteria

1. No plaintext active secrets in local tracked artifacts.
2. All privileged actions enforce MFA + policy + audit trail.
3. CSRF and replay controls validated by automated tests.
4. Production deploys fail closed on security config drift.
