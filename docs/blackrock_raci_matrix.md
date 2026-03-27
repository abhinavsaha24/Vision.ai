# BlackRock Program RACI Matrix

## Purpose

Defines clear ownership for delivery, control operation, and release decisions across the institutional architecture program.

## Roles

- Platform Engineering (PE)
- Quant Research (QR)
- Risk Engineering (RE)
- Security Engineering (SE)
- Data Engineering (DE)
- SRE/Operations (SRE)
- Product/Program Management (PM)
- Compliance/Governance (CG)

## RACI Definitions

- Responsible: Executes the work.
- Accountable: Final decision owner.
- Consulted: Provides required input.
- Informed: Receives status updates.

## Workstream RACI

| Workstream                                | PE  | QR  | RE  | SE  | DE  | SRE | PM  | CG  |
| ----------------------------------------- | --- | --- | --- | --- | --- | --- | --- | --- |
| Identity/session hardening                | R   | I   | C   | A   | I   | C   | I   | C   |
| Policy engine and authorization           | R   | C   | C   | A   | I   | C   | I   | C   |
| Pre/in/post-trade risk controls           | C   | C   | A/R | C   | I   | C   | I   | C   |
| Data governance and lineage               | C   | C   | C   | C   | A/R | I   | I   | C   |
| Observability and incident detection      | C   | I   | C   | C   | I   | A/R | I   | C   |
| CI/CD security gates and SBOM/signing     | R   | I   | I   | A   | I   | C   | I   | C   |
| Resilience drills and recovery validation | C   | I   | C   | C   | I   | A/R | I   | C   |
| Model promotion governance                | C   | A/R | C   | C   | C   | I   | I   | C   |
| Release readiness and go/no-go            | C   | C   | C   | C   | C   | C   | A   | C   |
| Audit evidence and regulatory response    | I   | I   | C   | C   | C   | I   | C   | A/R |

## Approval Authorities

| Decision                           | Required Approvers |
| ---------------------------------- | ------------------ |
| Production live-trading enablement | PM + RE + SE       |
| Emergency kill reset               | RE + SRE + SE      |
| Model promotion to production      | QR + RE + CG       |
| Security exception (time-bound)    | SE + CG            |

## Escalation Path

1. Workstream owner attempts mitigation within SLA.
2. Escalate to Accountable owner if SLA breach risk.
3. Escalate to PM for cross-team sequencing impact.
4. Escalate to CG for policy/regulatory risk.

## Cadence

- Daily: Workstream status + blockers.
- Weekly: Risk, controls, and validation review.
- Per release: Go/no-go meeting with recorded decisions.
- Monthly: Governance and residual risk review.
