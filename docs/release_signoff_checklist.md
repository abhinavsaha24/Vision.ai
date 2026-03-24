# Release Sign-Off Checklist

## Release Scope

- Repository: vision.ai
- Date: 2026-03-24
- Objective: production-hardening release sign-off with deployment smoke evidence and release packaging.

## Gate Matrix

| Gate                         | Requirement                                                           | Status                     | Evidence                                                                               |
| ---------------------------- | --------------------------------------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------- |
| CI quality gates             | Backend/frontend checks and security checks pass in CI                | PASS (previously verified) | `.github/workflows/ci.yml`                                                             |
| Backend production config    | Unified DB/port/runtime config is present                             | PASS (previously verified) | `backend/src/platform/config.py`, `backend/src/platform/api_service.py`                |
| Frontend service fallbacks   | API/WS fallbacks are deployment-safe and standardized                 | PASS (previously verified) | `frontend/src/services/api.ts`, `frontend/src/services/websocket.ts`                   |
| Dependency/security baseline | Declared dependencies and audit path present                          | PASS (previously verified) | `requirements.txt`, CI security jobs                                                   |
| Deployment artifacts         | Quant compose stack and Dockerfile exist                              | PASS                       | `deployment/docker-compose.quant.yml`, `deployment/Dockerfile.quant`                   |
| Local smoke deployment       | `docker compose -f deployment/docker-compose.quant.yml up -d --build` | PASS                       | Stack running; `/health` returned `200` with `{"status":"ok","service":"api-service"}` |

## Smoke Test Attempt Record

- Command run:
  - `docker compose -f deployment/docker-compose.quant.yml up -d --build`
  - `REDIS_PORT=6380 docker compose -f deployment/docker-compose.quant.yml up -d --build`
- Result:
  - Initial run failed because Docker daemon/engine was not reachable.
  - Docker Desktop was started and daemon verified with `docker info`.
  - Re-run built all quant images successfully but failed at container startup due host port bind collision:
    - `Bind for 0.0.0.0:6379 failed: port is already allocated`
  - After setting `REDIS_PORT=6380`, compose startup succeeded for all services.
  - Service verification succeeded:
    - `docker compose ... ps` shows `api-service`, `trading-engine`, `risk-engine`, `execution-engine`, `redis`, and `postgres` as `Up`.
    - `docker compose ... logs --tail=120 api-service` shows successful Uvicorn startup and application startup completion.
    - Health check response: `status=200`, body `{"status":"ok","service":"api-service"}`.

## Environment Unblock Steps

1. If host port `6379` is in use, run with alternate host Redis port:

- `REDIS_PORT=6380 docker compose -f deployment/docker-compose.quant.yml up -d --build`

2. Clean stack state when needed:
   - `docker compose -f deployment/docker-compose.quant.yml down`
3. Re-run smoke:
   - `docker compose -f deployment/docker-compose.quant.yml up -d --build`
4. Verify service health:
   - `docker compose -f deployment/docker-compose.quant.yml ps`
   - `docker compose -f deployment/docker-compose.quant.yml logs --tail=100 api-service`
   - `curl http://localhost:8080/health`

## Strict Release Decision

- Current decision: READY FOR RELEASE
- Reason: smoke gate completed successfully with all core services running and health endpoint returning `200`.
- Note: in environments where `6379` is occupied, set `REDIS_PORT` to a free host port.

## Commit Plan (Suggested)

1. `feat(platform): add event-driven live microstructure and worker pipeline`
2. `feat(research): add strict edge discovery and validation workflow`
3. `feat(deployment): add quant docker compose stack and fly process config`
4. `test: add platform API and pipeline integration coverage`
5. `docs: add architecture/refactor/release guidance and registry notes`

## PR Draft

### Title

`Production hardening and quant platform release baseline`

### Summary

- Introduces production-oriented platform modules for ingestion, signaling, risk, execution, and workerized orchestration.
- Adds research/validation stack for strict edge discovery, event-time microstructure evaluation, and capital-readiness outputs.
- Adds deployment assets for quant stack (`Dockerfile.quant`, compose stack, Fly process definitions).
- Adds tests and operational documentation for release and maintenance.

### Validation

- CI and static validation paths were previously verified.
- Local Docker smoke execution passed; stack startup and health checks were successful.
- Release sign-off criteria are satisfied.
