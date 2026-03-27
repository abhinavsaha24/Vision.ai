# Vision-AI Security Audit (2026-03-27)

## Scope

This audit reviewed security-relevant code paths and runtime settings across:

- backend API/auth/database/config layers
- frontend authentication/session/proxy layers
- deployment/runtime configuration in repository docs and env examples

This is a source-level review plus existing security test execution (`tests/test_security_hardening.py`).

## Summary Risk Rating

- Current posture: **Moderate to High** for internet-facing production use.
- Primary strength: baseline hardening controls exist (JWT checks, security headers, CORS allow-listing, websocket auth gates, audit log table, rate limiting).
- Primary gaps: browser token storage model, auth assurance level (no MFA), supply-chain trust assumptions for frontend scripts, and missing enterprise IAM/session controls.

## Findings

### Critical

1. Browser-accessible session token storage.

- Evidence: token persisted in localStorage and non-HttpOnly cookie in `frontend/src/store/authStore.ts`.
- Risk: XSS can directly exfiltrate long-lived bearer tokens.
- Recommendation: move to backend-issued `HttpOnly; Secure; SameSite=Strict` session cookie and remove localStorage token usage.

### High

1. No phishing-resistant MFA / step-up authentication for sensitive controls.

- Evidence: auth supports password and now Google sign-in, but no MFA enforcement in `backend/src/api/auth_routes.py`.
- Risk: single-factor account takeover can unlock trading controls.
- Recommendation: require MFA for admin and live-trading actions; add policy engine for step-up auth.

2. API proxy accepts auth from browser cookie value and forwards bearer token.

- Evidence: `frontend/src/app/api/[...path]/route.ts` maps `vision_ai_token` cookie to Authorization header.
- Risk: if cookie handling is not hardened end-to-end, CSRF and token replay attack surface increases.
- Recommendation: migrate to HttpOnly cookie + CSRF token + origin-bound session checks.

3. CSP permits third-party script CDNs.

- Evidence: CSP in `backend/src/api/main.py` allows `https://unpkg.com` and `https://cdn.jsdelivr.net`.
- Risk: external dependency compromise can execute arbitrary client code.
- Recommendation: self-host static JS dependencies where possible and tighten `script-src`.

### Medium

1. Account lifecycle controls are minimal.

- Evidence: no password reset, no lockout policy surfaced in auth routes (`backend/src/api/auth_routes.py`).
- Risk: weaker account recovery and brute-force handling posture.
- Recommendation: add lockout thresholds, challenge flow, secure reset tokens, and anomaly detections.

2. JWT key lifecycle is static.

- Evidence: single-secret HS256 strategy in `backend/src/auth/auth_service.py`.
- Risk: secret compromise requires coordinated global token invalidation.
- Recommendation: move to asymmetric signing with KID-based rotation (JWKS).

3. Auth event telemetry is incomplete.

- Evidence: audit table exists (`backend/src/database/db.py`) but auth route actions are not comprehensively logged.
- Risk: slower incident response and weaker forensics.
- Recommendation: add structured auth event logging with correlation IDs and risk attributes.

### Low

1. Security headers include legacy `X-XSS-Protection` header.

- Evidence: `backend/src/api/main.py`.
- Risk: low direct impact; mostly modernization debt.
- Recommendation: keep modern CSP focus; remove deprecated browser-era controls over time.

## New Changes Implemented In This Pass

1. Removed Google OAuth login surface for early-stage simplification.

- Deleted backend endpoint and verification flow for `/auth/google`.
- Removed Google sign-in UI and API client calls from frontend auth screens.
- Removed Google OAuth config/dependency references from runtime setup.

2. Kept hardened credential/session path as the single auth entry.

- Password policy remains enforced on signup.
- Session cookie auth path remains active for browser sessions.
- MFA step-up remains available for privileged actions.

## Immediate Hardening Plan (Next 14 Days)

1. Replace localStorage token auth with HttpOnly secure cookie sessions.
2. Add CSRF protections for state-changing routes.
3. Introduce MFA for admin and live-trading enable/kill actions.
4. Add auth event auditing for signup/login/logout failures and step-up attempts.
5. Introduce secret rotation strategy and short-lived access tokens with refresh rotation.

## Validation Executed

- Backend security tests: `19 passed` via `tests/test_security_hardening.py`.
- Frontend compile/build: successful production build.

## Residual Risk Statement

The platform is materially stronger than baseline retail implementations, but not yet equivalent to top-tier institutional controls for internet-exposed live-trading operations until session architecture, MFA, and key/session lifecycle controls are upgraded.
