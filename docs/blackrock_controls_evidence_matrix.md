# Vision-AI Controls and Evidence Matrix

## Purpose

Defines control objectives, implementation targets, required evidence, and verification methods for institutional readiness.

## Control Matrix

| Control ID | Domain           | Objective                                         | Implementation Target                                                | Evidence Artifact                                | Verification Method                              | Frequency     |
| ---------- | ---------------- | ------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------ | ------------- |
| IAM-01     | Identity         | Enforce MFA for privileged operations             | MFA step-up on admin/trading critical endpoints                      | API policy export + request logs with MFA checks | Negative-path integration tests and audit sample | Continuous    |
| IAM-02     | Session          | Prevent browser token exfiltration risk           | HttpOnly cookie sessions, no browser-readable credential persistence | Session config snapshot + client auth code audit | Security test + code scan                        | Per release   |
| IAM-03     | AuthZ            | Least privilege with explicit role policy         | RBAC + ABAC for high-impact operations                               | Policy definitions + role-to-action matrix       | Policy unit tests                                | Per change    |
| API-01     | Perimeter        | Block malformed and malicious traffic             | API gateway schema/WAF/rate controls                                 | Gateway policy bundle + blocked traffic reports  | Synthetic abuse traffic tests                    | Weekly        |
| API-02     | Policy           | Centralized authorization decisions               | OPA/Rego policy evaluation on privileged routes                      | Decision logs + policy test results              | Regression policy suite                          | Per commit    |
| DATA-01    | Secrets          | Remove static secret exposure                     | Vault-managed secrets and rotation                                   | Rotation logs + secret inventory                 | Rotation rehearsal                               | Monthly       |
| DATA-02    | DB Security      | Protect data in transit and at rest               | TLS + role-separated DB users + key management                       | DB config + cert state + role map                | Config compliance checks                         | Daily         |
| DATA-03    | Backup           | Ensure recoverability and integrity               | Immutable backups + restore drill process                            | Backup manifest + restore report                 | Recovery exercise                                | Quarterly     |
| RISK-01    | Trading Safety   | Enforce deterministic pre/in/post-trade checks    | Separate risk service and hard blocks                                | Risk policy snapshots + block event logs         | Scenario replay tests                            | Continuous    |
| RISK-02    | Dual Control     | Prevent single-party high-impact changes          | Two-person approval for live enable/kill reset/promotion             | Approval records + audit logs                    | Workflow audit                                   | Per action    |
| OBS-01     | Detection        | Detect auth and trading anomalies quickly         | SIEM + UEBA rules for suspicious behavior                            | Alert tuning records + incidents                 | Detection simulation                             | Monthly       |
| OBS-02     | Audit Integrity  | Preserve tamper-evident forensic trail            | WORM-capable audit stream retention                                  | Retention policy + integrity checks              | Evidence sampling                                | Quarterly     |
| SDLC-01    | Supply Chain     | Prevent compromised dependency flow               | SBOM + signed artifacts + registry allow-list                        | SBOM output + signature verification logs        | CI gate checks                                   | Per build     |
| SDLC-02    | Secure Delivery  | Block unsafe releases                             | SAST/SCA/secrets/IaC mandatory CI gates                              | CI run records + exception log                   | Release gate review                              | Per release   |
| RES-01     | Resilience       | Maintain safe operation under dependency failures | Risk-off degraded modes + failover paths                             | Chaos test reports + incident metrics            | Game-day exercises                               | Quarterly     |
| GOV-01     | Model Governance | Govern model promotion and rollback               | Signed model artifacts + approval workflow                           | Registry approvals + lineage bundle              | Governance board review                          | Per promotion |

## Evidence Quality Rules

1. Evidence must be timestamped and immutable or tamper-evident.
2. Evidence must include owner and control ID linkage.
3. Sampling must include both pass and fail-path records where applicable.
4. Exceptions must include expiration and compensating controls.

## Residual Risk Log (Template)

| Risk ID | Related Control | Residual Risk         | Compensating Control  | Owner | Review Date | Status |
| ------- | --------------- | --------------------- | --------------------- | ----- | ----------- | ------ |
| RR-001  | IAM-02          | Example residual risk | Additional monitoring | TBD   | YYYY-MM-DD  | Open   |
