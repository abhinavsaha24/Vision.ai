# Release Branching Strategy

## Branch Model

- `main`: production-ready only. Protected branch with required CI checks.
- `develop`: integration branch for validated feature branches.
- `feature/*`: short-lived branches for isolated work items.

## Merge Policy

1. Open PR from `feature/*` to `develop`.
2. Require green CI (`backend`, `frontend`) before merge.
3. Squash merge to keep history compact.
4. Promote `develop` to `main` only via release PR with changelog.

## Release Checklist

- CI green on release PR
- `docker compose -f deployment/docker-compose.quant.yml up --build` smoke test passes
- Security audits pass (`pip_audit`, `npm audit --omit=dev`)
- README and deployment docs updated for any config changes

## Hotfix Flow

- Branch from `main` as `hotfix/*`
- Merge hotfix into `main` and back-merge to `develop`
